import { useQueryClient } from "@tanstack/react-query";
import { Circle, CloudUpload, History, Mic, Pause, Play, Square, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useBlocker, type BlockerFunction } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { MEETINGS_KEY, uploadRecording } from "./api";
import { formatDuration } from "./constants";
import { clearPendingSession, loadPendingSession, savePendingSession, savedAgo } from "./pendingStore";

type Phase = "idle" | "recording" | "uploading";

interface Recovered { blob: Blob; durationMs: number; sizeBytes: number; savedAgo: string }

const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
const AUDIO_EXT = /\.(mp3|wav|m4a|ogg|webm|flac|aac|opus|oga)$/i;
const AUTOSAVE_MS = 30_000;
const LEVEL_BARS = 10;

function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") return "";
  return MIME_CANDIDATES.find((c) => MediaRecorder.isTypeSupported(c)) ?? "";
}

function micError(err: unknown): string {
  const e = err as { name?: string; message?: string };
  if (e?.name === "NotAllowedError" || e?.name === "SecurityError") return "Permission micro refusée — activez-la dans le navigateur.";
  if (e?.name === "NotFoundError") return "Aucun micro détecté sur cet appareil.";
  return `Impossible d'accéder au micro : ${e?.message ?? String(err)}`;
}

function estimateDuration(file: File): Promise<number> {
  return new Promise((resolve, reject) => {
    try {
      const audio = document.createElement("audio");
      audio.preload = "metadata";
      const url = URL.createObjectURL(file);
      audio.onloadedmetadata = () => { URL.revokeObjectURL(url); resolve(Number.isFinite(audio.duration) ? audio.duration : 0); };
      audio.onerror = () => { URL.revokeObjectURL(url); reject(new Error("métadonnées audio illisibles")); };
      audio.src = url;
    } catch (e) {
      reject(e);
    }
  });
}

/**
 * Enregistreur de réunion (MediaRecorder) — reproduit `recorder_widget.html` :
 * consentement obligatoire, permission micro, chronomètre, niveau sonore,
 * pause / reprise, arrêt puis envoi (progression) vers l'endpoint historique,
 * import d'un fichier audio, sauvegarde locale périodique (IndexedDB) et
 * récupération d'une capture interrompue. Le suivi du traitement IA est affiché
 * par le parent (`onUploaded`).
 */
export function MeetingRecorder({ meetingId, maxUploadMb, onUploaded }: {
  meetingId: number; maxUploadMb: number; onUploaded?: (recordingId: number) => void;
}) {
  const qc = useQueryClient();
  const [phase, setPhase] = useState<Phase>("idle");
  const [consent, setConsent] = useState(false);
  const [durationMs, setDurationMs] = useState(0);
  const [level, setLevel] = useState(0);
  const [paused, setPaused] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [recovered, setRecovered] = useState<Recovered | null>(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [hasSavedBlob, setHasSavedBlob] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const r = useRef({
    recorder: null as MediaRecorder | null,
    stream: null as MediaStream | null,
    chunks: [] as Blob[],
    startMs: 0,
    accumulatedMs: 0,
    durationMs: 0,
    timer: 0 as ReturnType<typeof setInterval> | 0,
    autosave: 0 as ReturnType<typeof setInterval> | 0,
    raf: 0,
    audioCtx: null as AudioContext | null,
    savedBlob: null as Blob | null,
    phase: "idle" as Phase,
  });
  useEffect(() => { r.current.phase = phase; }, [phase]);

  const setDuration = (ms: number) => { r.current.durationMs = ms; setDurationMs(ms); };

  // ── Capture interrompue (onglet fermé / rechargé) retrouvée en local ──
  useEffect(() => {
    let alive = true;
    void loadPendingSession(meetingId).then((s) => {
      if (alive && s) setRecovered({ blob: s.blob, durationMs: s.durationMs || 0, sizeBytes: s.sizeBytes || s.blob.size, savedAgo: savedAgo(s.savedAt) });
    });
    return () => { alive = false; };
  }, [meetingId]);

  const releaseDevices = useCallback(() => {
    const c = r.current;
    c.stream?.getTracks().forEach((t) => t.stop());
    if (c.timer) clearInterval(c.timer);
    if (c.raf) cancelAnimationFrame(c.raf);
    void c.audioCtx?.close().catch(() => undefined);
    c.timer = 0;
    c.raf = 0;
    c.audioCtx = null;
    c.recorder = null;
    c.stream = null;
    setLevel(0);
  }, []);

  const stopAutosave = useCallback(() => {
    if (r.current.autosave) clearInterval(r.current.autosave);
    r.current.autosave = 0;
  }, []);

  const saveNow = useCallback(() => {
    const c = r.current;
    if (!c.chunks.length) return Promise.resolve();
    const blob = new Blob(c.chunks, { type: c.recorder?.mimeType || "audio/webm" });
    return savePendingSession(meetingId, blob, c.durationMs);
  }, [meetingId]);

  // Démontage (navigation) : copie locale de la capture en cours puis libération du micro.
  useEffect(() => () => {
    if (r.current.phase === "recording") void saveNow();
    stopAutosave();
    releaseDevices();
  }, [releaseDevices, saveNow, stopAutosave]);

  const active = phase === "recording" || phase === "uploading";

  // Avertissement avant fermeture / rechargement de l'onglet pendant la capture ou l'envoi.
  useEffect(() => {
    if (!active) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "Un enregistrement est en cours — il sera sauvegardé localement, mais préférez Arrêter d'abord.";
      return e.returnValue;
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [active]);

  // Navigation vers une autre page pendant la capture ou l'envoi : confirmation.
  // Un booléen bloquerait aussi les changements de query string (onglets de la
  // fiche, `?tab=`), qui ne démontent pas l'enregistreur : seul un changement
  // de chemin est bloqué.
  const shouldBlock = useCallback<BlockerFunction>(
    ({ currentLocation, nextLocation }) => active && currentLocation.pathname !== nextLocation.pathname,
    [active],
  );
  const blocker = useBlocker(shouldBlock);

  const upload = async (blob: Blob, consentGiven: boolean) => {
    setPhase("uploading");
    setProgress(0);
    setError(null);
    r.current.savedBlob = blob;
    setHasSavedBlob(true);
    try {
      const res = await uploadRecording({
        meetingId, file: blob, durationSeconds: r.current.durationMs / 1000, consent: consentGiven, onProgress: setProgress,
      });
      r.current.savedBlob = null;
      setHasSavedBlob(false);
      setPhase("idle");
      setDuration(0);
      await clearPendingSession(meetingId);
      toast.success("Audio envoyé — transcription et analyse IA en cours.");
      onUploaded?.(Number(res.recording_id));
      void qc.invalidateQueries({ queryKey: [...MEETINGS_KEY, meetingId] });
    } catch (e) {
      setError((e as Error).message);
      setPhase("idle");
    }
  };

  const start = async () => {
    setError(null);
    if (!consent) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("L'enregistrement audio n'est pas pris en charge par ce navigateur — importez un fichier audio.");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (err) {
      setError(micError(err));
      return;
    }
    const mimeType = pickMimeType();
    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
    } catch (err) {
      stream.getTracks().forEach((t) => t.stop());
      setError(`Enregistrement impossible : ${(err as Error).message}`);
      return;
    }
    const c = r.current;
    c.stream = stream;
    c.recorder = recorder;
    c.chunks = [];
    recorder.ondataavailable = (ev) => { if (ev.data && ev.data.size > 0) c.chunks.push(ev.data); };
    recorder.start(5000);
    c.startMs = Date.now();
    c.accumulatedMs = 0;
    setDuration(0);
    c.timer = setInterval(() => setDuration(Date.now() - c.startMs + c.accumulatedMs), 200);
    try {
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (Ctx) {
        const ctx = new Ctx();
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        ctx.createMediaStreamSource(stream).connect(analyser);
        c.audioCtx = ctx;
        const data = new Uint8Array(analyser.fftSize);
        const loop = () => {
          if (!c.audioCtx) return;
          analyser.getByteTimeDomainData(data);
          let sum = 0;
          for (const v of data) { const x = (v - 128) / 128; sum += x * x; }
          setLevel(Math.sqrt(sum / data.length));
          c.raf = requestAnimationFrame(loop);
        };
        c.raf = requestAnimationFrame(loop);
      }
    } catch { /* niveau sonore facultatif */ }
    setPaused(false);
    setPhase("recording");
    stopAutosave();
    c.autosave = setInterval(() => { void saveNow(); }, AUTOSAVE_MS);
  };

  const pause = () => {
    const c = r.current;
    if (c.recorder?.state !== "recording") return;
    c.recorder.pause();
    c.accumulatedMs += Date.now() - c.startMs;
    if (c.timer) clearInterval(c.timer);
    c.timer = 0;
    setPaused(true);
  };

  const resume = () => {
    const c = r.current;
    if (c.recorder?.state !== "paused") return;
    c.recorder.resume();
    c.startMs = Date.now();
    c.timer = setInterval(() => setDuration(Date.now() - c.startMs + c.accumulatedMs), 200);
    setPaused(false);
  };

  const finalize = () => new Promise<Blob | null>((resolve) => {
    const c = r.current;
    const recorder = c.recorder;
    if (!recorder) { resolve(null); return; }
    if (c.recorder?.state === "recording" && c.startMs && !paused) setDuration(Date.now() - c.startMs + c.accumulatedMs);
    recorder.onstop = () => {
      const blob = new Blob(c.chunks, { type: recorder.mimeType || "audio/webm" });
      releaseDevices();
      resolve(blob.size ? blob : null);
    };
    try { recorder.stop(); } catch { releaseDevices(); resolve(null); }
  });

  const stop = async () => {
    const blob = await finalize();
    stopAutosave();
    if (!blob) {
      setPhase("idle");
      setError("Aucun son n'a été capté — vérifiez le micro puis recommencez.");
      return;
    }
    await savePendingSession(meetingId, blob, r.current.durationMs); // trace locale si l'envoi échoue
    await upload(blob, true);
  };

  const onFile = async (file: File | undefined) => {
    setError(null);
    if (!file) return;
    if (!consent) { setError("Cochez d'abord le consentement des participants."); return; }
    const sizeMb = file.size / 1024 / 1024;
    if (sizeMb > maxUploadMb) { setError(`Fichier trop volumineux (${sizeMb.toFixed(0)} Mo). Maximum : ${maxUploadMb} Mo.`); return; }
    if (!file.type.startsWith("audio/") && !AUDIO_EXT.test(file.name)) { setError(`Type de fichier non audio : ${file.type || file.name}`); return; }
    try { setDuration((await estimateDuration(file)) * 1000); } catch { setDuration(0); }
    r.current.chunks = [];
    await upload(file, true);
  };

  const sendRecovered = async () => {
    if (!recovered) return;
    setConsent(true); // consentement déjà donné lors de la capture
    setDuration(recovered.durationMs);
    const blob = recovered.blob;
    setRecovered(null);
    await upload(blob, true);
  };

  const discardRecovered = async () => {
    await clearPendingSession(meetingId);
    setRecovered(null);
    setConfirmDiscard(false);
  };

  const lit = Math.min(LEVEL_BARS, Math.round(level * LEVEL_BARS * 3));

  return (
    <Card>
      <CardHeader>
        <p className="flex items-center gap-1.5 text-[11px] font-extrabold uppercase tracking-[0.12em] text-brand"><Mic className="size-3.5" aria-hidden="true" />Enregistrement & CR IA</p>
        <CardTitle>Capter cette réunion</CardTitle>
        <CardDescription>L'audio est transcrit, les voix identifiées puis un compte-rendu est généré par l'IA.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {phase === "idle" && recovered && (
          <div className="space-y-3 rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm">
            <p className="flex items-start gap-2">
              <History className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
              <span><strong>Enregistrement précédent récupéré</strong> — {formatDuration(recovered.durationMs)} ({(recovered.sizeBytes / 1024 / 1024).toFixed(1)} Mo,
                sauvegardé {recovered.savedAgo}). Voulez-vous l'envoyer ou le supprimer ?</span>
            </p>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => void sendRecovered()}><CloudUpload />Envoyer cet enregistrement</Button>
              <Button size="sm" variant="outline" onClick={() => setConfirmDiscard(true)}><Trash2 />Supprimer</Button>
            </div>
          </div>
        )}

        {phase === "idle" && (
          <div className="space-y-3">
            <div className="rounded-xl border border-warning/30 bg-warning/10 p-3 text-sm">
              <p className="font-semibold text-warning">Consentement requis</p>
              <p className="mt-1 text-xs text-foreground/80">Cette réunion sera enregistrée à des fins de compte-rendu. Les participants doivent être informés AVANT le début.</p>
              <label className="mt-2 flex items-center gap-2 text-xs">
                <input type="checkbox" className="size-4 accent-primary" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                J'ai informé les participants et j'assume la responsabilité.
              </label>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button disabled={!consent} onClick={() => void start()}><Circle className="fill-current" />Démarrer l'enregistrement</Button>
              <Button variant="outline" disabled={!consent} onClick={() => fileInput.current?.click()}
                title="Envoyer un fichier audio déjà enregistré (mp3, wav, m4a, ogg, webm…)"><CloudUpload />Importer un audio</Button>
              <input ref={fileInput} type="file" className="hidden" aria-label="Fichier audio à importer"
                accept="audio/*,.mp3,.wav,.m4a,.ogg,.webm,.flac,.aac,.opus"
                onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; void onFile(f); }} />
            </div>
            <p className="text-[11px] text-muted-foreground">Astuce : si l'enregistrement en direct échoue, importez directement un fichier audio (max {maxUploadMb} Mo).</p>
          </div>
        )}

        {phase === "recording" && (
          <div className="flex flex-wrap items-center gap-3">
            <span className={cn("inline-block size-3 rounded-full bg-destructive", !paused && "animate-pulse")} aria-hidden="true" />
            <span className="font-mono text-lg font-bold tabular-nums" aria-label="Durée enregistrée">{formatDuration(durationMs)}</span>
            {paused && <span className="text-xs font-semibold text-warning">En pause</span>}
            <span className="flex gap-0.5" aria-hidden="true">
              {Array.from({ length: LEVEL_BARS }, (_, i) => <span key={i} className={cn("inline-block h-3 w-1 rounded", i < lit ? "bg-primary" : "bg-muted")} />)}
            </span>
            <span className="flex-1" />
            {paused
              ? <Button size="sm" variant="outline" onClick={resume}><Play />Reprendre</Button>
              : <Button size="sm" variant="outline" onClick={pause}><Pause />Pause</Button>}
            <Button size="sm" variant="destructive" onClick={() => void stop()}><Square className="fill-current" />Arrêter</Button>
          </div>
        )}

        {phase === "uploading" && (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">Envoi de l'audio…</p>
            <div className="h-2 w-full rounded-full bg-muted" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress} aria-label="Envoi de l'audio">
              <div className="h-2 rounded-full bg-primary transition-all" style={{ width: `${progress}%` }} />
            </div>
            <p className="text-xs text-muted-foreground">{progress} %</p>
          </div>
        )}

        {error && (
          <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <strong>Erreur :</strong> {error}
            {hasSavedBlob && (
              <div className="mt-2">
                <Button size="sm" variant="outline" onClick={() => { const b = r.current.savedBlob; if (b) void upload(b, true); }}>Réessayer l'envoi</Button>
              </div>
            )}
          </div>
        )}
      </CardContent>

      <ConfirmDialog open={confirmDiscard} onOpenChange={setConfirmDiscard} destructive title="Supprimer l'enregistrement local ?"
        description="Cet enregistrement n'a pas été envoyé : il sera définitivement perdu." confirmLabel="Supprimer" onConfirm={() => void discardRecovered()} />
      <ConfirmDialog open={blocker.state === "blocked"} onOpenChange={(o) => { if (!o) blocker.reset?.(); }}
        title="Quitter la page ?" description="L'enregistrement en cours sera interrompu (une copie locale est conservée et pourra être envoyée au retour sur la réunion)."
        confirmLabel="Quitter" destructive
        onConfirm={() => { void saveNow().finally(() => blocker.proceed?.()); }} />
    </Card>
  );
}
