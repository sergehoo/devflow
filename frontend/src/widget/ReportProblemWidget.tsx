/**
 * Widget « Signaler un problème » — composant React autonome, intégrable dans
 * toute application compatible (voir TICKETING_INTEGRATION.md).
 *
 * SÉCURITÉ :
 *  - le widget n'appelle JAMAIS l'API DevFlow directement et ne contient aucun
 *    secret : il envoie au BACKEND de l'application hôte (``submitUrl``), qui
 *    signe la requête (HMAC) et la relaie vers DevFlow ;
 *  - aucune capture automatique : pas de cookies, stockage, champs de saisie
 *    ni paramètres d'URL ; capture d'écran uniquement sur action explicite
 *    (sélection de l'écran par l'utilisateur), prévisualisable et supprimable.
 */
import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from "react";
import { technicalContext } from "./context";

export interface ReportProblemWidgetProps {
  /** Endpoint du backend de l'application (proxy signé vers DevFlow). */
  submitUrl: string;
  /** Endpoint backend de consultation : GET `${statusUrl}/${externalId}`. */
  statusUrl?: string;
  appVersion?: string;
  environment?: string;
  /** Contexte additionnel explicitement autorisé (jamais de donnée personnelle ou secrète). */
  context?: Record<string, string | number | boolean>;
  /** En-têtes propres à l'application hôte (ex. jeton CSRF de SA session). */
  headers?: Record<string, string>;
  fetchImpl?: typeof fetch;
  buttonLabel?: string;
}

const ALLOWED = ["image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain", "video/mp4", "video/webm"];
const MAX_FILES = 3;
const MAX_MB = 10;
const CATEGORIES: [string, string][] = [["BUG", "Anomalie"], ["INCIDENT", "Incident / panne"], ["QUESTION", "Question"], ["FEATURE", "Suggestion"], ["ACCESS", "Accès / compte"], ["OTHER", "Autre"]];
const SEVERITIES: [string, string][] = [["MINOR", "Gêne mineure"], ["MAJOR", "Bloque une partie de mon travail"], ["CRITICAL", "Bloque complètement"], ["TRIVIAL", "Cosmétique"]];

const s: Record<string, CSSProperties> = {
  fab: { position: "fixed", right: 20, bottom: 20, zIndex: 2147483000, border: 0, borderRadius: 999, padding: "12px 18px", background: "#FFD44F", color: "#202020", fontWeight: 600, fontFamily: "Inter, system-ui, sans-serif", boxShadow: "0 8px 24px rgba(32,32,32,.18)", cursor: "pointer" },
  panel: { position: "fixed", right: 20, bottom: 80, zIndex: 2147483000, width: "min(420px, calc(100vw - 40px))", maxHeight: "calc(100vh - 120px)", overflowY: "auto", background: "#fff", color: "#202020", borderRadius: 22, padding: 20, boxShadow: "0 12px 40px rgba(32,32,32,.2)", fontFamily: "Inter, system-ui, sans-serif", fontSize: 14 },
  label: { display: "block", fontSize: 12, fontWeight: 600, color: "#77736D", margin: "10px 0 4px" },
  input: { width: "100%", boxSizing: "border-box", border: "1px solid #EAE6DE", borderRadius: 12, padding: "9px 12px", font: "inherit", background: "#fff", color: "#202020" },
  primary: { border: 0, borderRadius: 999, padding: "10px 16px", background: "#FFD44F", color: "#202020", fontWeight: 600, cursor: "pointer" },
  ghost: { border: "1px solid #EAE6DE", borderRadius: 999, padding: "8px 14px", background: "#fff", color: "#202020", cursor: "pointer" },
  error: { marginTop: 10, color: "#B42318", fontSize: 13 },
  muted: { color: "#77736D", fontSize: 12 },
};

const newId = () => (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`);

async function captureScreen(): Promise<Blob | null> {
  if (!navigator.mediaDevices?.getDisplayMedia) return null;
  const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
  try {
    const video = document.createElement("video");
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    return await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
  } finally {
    stream.getTracks().forEach((t) => t.stop());
  }
}

export function ReportProblemWidget(props: ReportProblemWidgetProps) {
  const { submitUrl, statusUrl, appVersion, environment, context, headers, fetchImpl = fetch, buttonLabel = "Signaler un problème" } = props;
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("BUG");
  const [severity, setSeverity] = useState("MINOR");
  const [includeContext, setIncludeContext] = useState(true);
  const [files, setFiles] = useState<File[]>([]);
  const [shot, setShot] = useState<{ blob: Blob; url: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<{ reference: string; external_id: string; status_label: string } | null>(null);
  const [lookup, setLookup] = useState("");
  const [status, setStatus] = useState<string>("");
  const pending = useRef<string>(newId()); // identifiant stable : un nouvel essai ne crée pas de doublon

  useEffect(() => () => { if (shot) URL.revokeObjectURL(shot.url); }, [shot]);

  const pickFiles = (list: FileList | null) => {
    const picked = Array.from(list ?? []);
    const bad = picked.find((f) => !ALLOWED.includes(f.type) || f.size > MAX_MB * 1024 * 1024);
    if (bad) return setError(`« ${bad.name} » : type non autorisé ou taille supérieure à ${MAX_MB} Mo.`);
    setError("");
    setFiles(picked.slice(0, MAX_FILES));
  };

  const screenshot = async () => {
    setError("");
    try {
      const blob = await captureScreen();
      if (!blob) return setError("La capture d'écran n'est pas disponible sur ce navigateur.");
      if (shot) URL.revokeObjectURL(shot.url);
      setShot({ blob, url: URL.createObjectURL(blob) });
    } catch {
      setError("Capture annulée.");
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    const fd = new FormData();
    fd.append("external_id", pending.current);
    fd.append("title", title.trim());
    fd.append("description", description.trim());
    fd.append("category", category);
    fd.append("severity", severity);
    if (environment) fd.append("environment", environment);
    if (appVersion) fd.append("app_version", appVersion);
    if (includeContext) {
      const ctx = technicalContext(context);
      fd.append("url", ctx.page);
      fd.append("metadata", JSON.stringify(ctx.metadata));
    }
    files.forEach((f) => fd.append("attachments", f));
    if (shot) fd.append("attachments", new File([shot.blob], "capture-ecran.png", { type: "image/png" }));
    try {
      const res = await fetchImpl(submitUrl, { method: "POST", body: fd, credentials: "same-origin", headers: { "Idempotency-Key": pending.current, ...headers } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Envoi impossible. Réessayez dans un instant.");
      setDone({ reference: data.reference, external_id: data.external_id, status_label: data.status_label });
      pending.current = newId();
      setTitle(""); setDescription(""); setFiles([]); setShot(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const checkStatus = async (e: FormEvent) => {
    e.preventDefault();
    if (!statusUrl || !lookup.trim()) return;
    setStatus("…");
    try {
      const res = await fetchImpl(`${statusUrl.replace(/\/$/, "")}/${encodeURIComponent(lookup.trim())}`, { credentials: "same-origin", headers });
      const data = await res.json();
      setStatus(res.ok ? `${data.reference} : ${data.status_label}` : (data.detail || "Ticket introuvable."));
    } catch {
      setStatus("Consultation impossible.");
    }
  };

  return (
    <>
      <button type="button" style={s.fab} onClick={() => setOpen((o) => !o)} aria-expanded={open}>{buttonLabel}</button>
      {open && (
        <section role="dialog" aria-label={buttonLabel} style={s.panel}>
          {done ? (
            <div role="status">
              <p style={{ fontSize: 17, fontWeight: 600, margin: 0 }}>Merci, votre signalement est enregistré.</p>
              <p style={{ margin: "8px 0" }}>Numéro de ticket : <strong>{done.reference}</strong> ({done.status_label})</p>
              <p style={s.muted}>Conservez ce numéro pour suivre la résolution.</p>
              <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                <button type="button" style={s.ghost} onClick={() => { setLookup(done.external_id); setDone(null); }}>Nouveau signalement</button>
                <button type="button" style={s.primary} onClick={() => setOpen(false)}>Fermer</button>
              </div>
            </div>
          ) : (
            <form onSubmit={submit}>
              <p style={{ fontSize: 17, fontWeight: 600, margin: 0 }}>{buttonLabel}</p>
              <p style={s.muted}>N'indiquez jamais de mot de passe ni de donnée confidentielle.</p>
              <label style={s.label} htmlFor="rp-title">Résumé</label>
              <input id="rp-title" style={s.input} required minLength={3} maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
              <label style={s.label} htmlFor="rp-desc">Que s'est-il passé ?</label>
              <textarea id="rp-desc" style={{ ...s.input, minHeight: 90 }} maxLength={5000} value={description} onChange={(e) => setDescription(e.target.value)} />
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <div>
                  <label style={s.label} htmlFor="rp-cat">Type</label>
                  <select id="rp-cat" style={s.input} value={category} onChange={(e) => setCategory(e.target.value)}>
                    {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
                <div>
                  <label style={s.label} htmlFor="rp-sev">Impact</label>
                  <select id="rp-sev" style={s.input} value={severity} onChange={(e) => setSeverity(e.target.value)}>
                    {SEVERITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
              </div>
              <label style={s.label} htmlFor="rp-files">Pièces jointes ({MAX_FILES} max, {MAX_MB} Mo)</label>
              <input id="rp-files" type="file" multiple accept={ALLOWED.join(",")} onChange={(e) => pickFiles(e.target.files)} />
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10 }}>
                <button type="button" style={s.ghost} onClick={() => void screenshot()}>Capturer l'écran</button>
                {shot && <><img src={shot.url} alt="Aperçu de la capture" style={{ height: 40, borderRadius: 6 }} />
                  <button type="button" style={s.ghost} onClick={() => setShot(null)}>Retirer</button></>}
              </div>
              <label style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 12, fontSize: 13 }}>
                <input type="checkbox" checked={includeContext} onChange={(e) => setIncludeContext(e.target.checked)} />
                <span>Joindre le contexte technique : page (sans paramètres), navigateur, langue, taille d'écran{appVersion ? `, version ${appVersion}` : ""}.</span>
              </label>
              {error && <p role="alert" style={s.error}>{error}</p>}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
                <button type="button" style={s.ghost} onClick={() => setOpen(false)}>Annuler</button>
                <button type="submit" style={s.primary} disabled={busy}>{busy ? "Envoi…" : "Envoyer"}</button>
              </div>
            </form>
          )}
          {statusUrl && (
            <form onSubmit={checkStatus} style={{ borderTop: "1px solid #EAE6DE", marginTop: 16, paddingTop: 12 }}>
              <label style={s.label} htmlFor="rp-lookup">Suivre un signalement (identifiant)</label>
              <div style={{ display: "flex", gap: 8 }}>
                <input id="rp-lookup" style={s.input} value={lookup} onChange={(e) => setLookup(e.target.value)} />
                <button type="submit" style={s.ghost}>Voir</button>
              </div>
              {status && <p role="status" style={{ ...s.muted, marginTop: 6 }}>{status}</p>}
            </form>
          )}
        </section>
      )}
    </>
  );
}
