import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, Trash2, UserCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { MEETINGS_KEY, messagesOf, useMeetingAction, useRecordingStatus, type RecordingStatus } from "./api";
import { PIPELINE_STEPS, humanSeconds, progressTone, relative } from "./constants";

/** Barre + jalons du pipeline (équivalent du fragment htmx `recording_status_fragment.html`). */
export function PipelineBar({ s }: { s: RecordingStatus }) {
  const tone = progressTone(s.status);
  return (
    <div className="rounded-2xl border bg-muted/40 p-4">
      <div className="mb-2 flex items-center justify-between gap-3 text-xs">
        <span className="flex min-w-0 items-center gap-1.5 font-medium text-foreground">
          {s.status === "failed" ? <AlertTriangle className="size-4 shrink-0 text-destructive" aria-hidden="true" />
            : s.status === "completed" ? <CheckCircle2 className="size-4 shrink-0 text-success" aria-hidden="true" />
              : s.status === "waiting_speaker_mapping" ? <UserCheck className="size-4 shrink-0 text-primary" aria-hidden="true" />
                : <Loader2 className="size-4 shrink-0 animate-spin text-primary" aria-hidden="true" />}
          <span className="truncate">{s.progress_label || s.status_label}</span>
        </span>
        <span className="shrink-0 whitespace-nowrap font-mono font-bold tabular-nums">{s.progress_percent} %</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-card" role="progressbar" aria-valuemin={0} aria-valuemax={100}
        aria-valuenow={s.progress_percent} aria-label="Progression du traitement">
        <div className={cn("h-2 rounded-full transition-all duration-500", tone)} style={{ width: `${s.progress_percent}%` }} />
      </div>
      <ol className="mt-3 grid grid-cols-5 gap-1 text-center text-[10px] text-muted-foreground">
        {PIPELINE_STEPS.map(([threshold, label]) => (
          <li key={label} className={cn("min-w-0 truncate", s.progress_percent >= threshold && "font-medium text-foreground")}>
            <div className={cn("mb-1 h-1 rounded", s.progress_percent >= threshold ? tone : "bg-card")} />
            {label}
          </li>
        ))}
      </ol>
      {s.started_at && (
        <p className="mt-2 text-[11px] text-muted-foreground">
          Lancé {relative(s.started_at)}
          {s.duration_seconds ? ` · Durée audio : ${humanSeconds(s.duration_seconds)}` : ""}
          {s.transcription_provider ? ` · Transcription : ${s.transcription_provider}` : ""}
        </p>
      )}
    </div>
  );
}

/**
 * Suivi en direct d'un enregistrement (polling 3 s jusqu'à l'état final) avec
 * l'appel à l'action de l'étape : identifier les voix, voir le résumé, relancer.
 */
export function RecordingProgress({ recordingId, meetingId, initial, compact, onDeleted }: {
  recordingId: number; meetingId: number; initial?: RecordingStatus; compact?: boolean; onDeleted?: (recordingId: number) => void;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const status = useRecordingStatus(recordingId);
  const action = useMeetingAction();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const s = status.data ?? initial;
  const last = useRef<string | undefined>(s?.status);

  useEffect(() => {
    // Changement d'étape : la fiche (liste des enregistrements) et la page CR sont rafraîchies.
    if (s && last.current && last.current !== s.status) {
      void qc.invalidateQueries({ queryKey: [...MEETINGS_KEY, meetingId] });
      void qc.invalidateQueries({ queryKey: [...MEETINGS_KEY, "recording", recordingId], exact: true });
    }
    last.current = s?.status;
  }, [s, qc, meetingId, recordingId]);

  if (!s) {
    return (
      <div className="flex items-center gap-2 rounded-2xl border bg-muted/40 p-3 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden="true" />Démarrage du pipeline IA…
      </div>
    );
  }
  const link = `/meetings/${meetingId}/recordings/${recordingId}`;
  const run = (path: string, after?: () => void) => action.mutate({ path }, {
    onSuccess: (r) => { messagesOf(r, "Action effectuée.").forEach((m) => toast.success(m)); after?.(); void status.refetch(); },
    onError: (e) => toast.error(e.message),
  });

  return (
    <div className="space-y-3" aria-live="polite">
      <PipelineBar s={s} />
      {s.status === "waiting_speaker_mapping" && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-success/30 bg-success/10 p-3 text-sm">
          <span className="text-success"><strong>Voix détectées !</strong> Identifiez chaque intervenant{compact ? " ci-dessous" : ""} pour finaliser le compte-rendu.</span>
          {!compact && <Button size="sm" asChild><Link to={link}>Identifier les voix</Link></Button>}
        </div>
      )}
      {s.status === "completed" && !compact && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-success/30 bg-success/10 p-3 text-sm">
          <span className="font-semibold text-success">Compte-rendu prêt !</span>
          <Button size="sm" asChild><Link to={link}>Voir le résumé</Link></Button>
        </div>
      )}
      {s.status === "failed" && (
        <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <strong>Échec :</strong> {s.error_message || "Erreur inconnue. Consultez les journaux du traitement."}
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" disabled={action.isPending} onClick={() => run(`meetings/recordings/${recordingId}/regenerate/`)}>
              <RefreshCw />Réessayer la synthèse
            </Button>
            <Button size="sm" variant="outline" className="text-destructive" onClick={() => setConfirmDelete(true)}><Trash2 />Supprimer</Button>
          </div>
        </div>
      )}
      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} destructive pending={action.isPending}
        title="Supprimer cet enregistrement ?" description="L'audio, la transcription et le compte-rendu seront supprimés définitivement."
        confirmLabel="Supprimer" onConfirm={() => run(`meetings/recordings/${recordingId}/delete/`, () => {
          setConfirmDelete(false);
          onDeleted?.(recordingId);
          void qc.invalidateQueries({ queryKey: [...MEETINGS_KEY, meetingId] });
          // Sur la page de l'enregistrement supprimé : retour à la liste de la réunion.
          if (compact) navigate(`/meetings/${meetingId}?tab=recordings`, { replace: true });
        })} />
    </div>
  );
}
