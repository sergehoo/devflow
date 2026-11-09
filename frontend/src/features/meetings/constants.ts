/** Couleurs (tokens du thème) des statuts — miroir des `status_color` / `*_badge_color` Django. */
const GREEN = "bg-success/15 text-success";
const RED = "bg-destructive/10 text-destructive";
const AMBER = "bg-warning/15 text-warning";
const CYAN = "bg-info/15 text-info";
const ORANGE = "bg-primary/10 text-brand";

export const MEETING_STATUS_BADGE: Record<string, string> = { PLANNED: CYAN, HELD: GREEN, CANCELLED: RED, POSTPONED: AMBER };
export const AGENDA_STATUS_BADGE: Record<string, string> = { PENDING: AMBER, IN_PROGRESS: CYAN, DONE: GREEN, POSTPONED: RED, SKIPPED: "" };
export const RSVP_BADGE: Record<string, string> = { INVITED: AMBER, ACCEPTED: GREEN, DECLINED: RED, TENTATIVE: CYAN };
export const ATTENDANCE_BADGE: Record<string, string> = { UNKNOWN: AMBER, PRESENT: GREEN, ABSENT: RED, LATE: AMBER, LEFT_EARLY: AMBER };
export const PRIORITY_BADGE: Record<string, string> = { CRITICAL: RED, HIGH: RED, MEDIUM: AMBER, LOW: CYAN };
export const ACTION_STATUS_BADGE: Record<string, string> = { DONE: GREEN, CANCELLED: RED, OPEN: CYAN, IN_PROGRESS: CYAN };
export const DECISION_STATUS_BADGE: Record<string, string> = { VALIDATED: ORANGE, EXECUTED: GREEN, PENDING: AMBER, REVERSED: RED };
export const RECORDING_STATUS_BADGE: Record<string, string> = { completed: GREEN, failed: RED, cancelled: AMBER, waiting_speaker_mapping: AMBER };

/** Barre de progression du pipeline (même code couleur que `progress_color`). */
export function progressTone(status: string): string {
  if (status === "failed") return "bg-destructive";
  if (status === "cancelled") return "bg-warning";
  if (status === "completed") return "bg-success";
  return "bg-primary";
}

/** Jalons du pipeline (fragment `recording_status_fragment.html`). */
export const PIPELINE_STEPS: [number, string][] = [[15, "Upload"], [35, "Transcr."], [55, "Voix"], [70, "Mapping"], [88, "Synthèse"]];

export const TABS = [
  { id: "notes", label: "Notes & ordre du jour" },
  { id: "decisions", label: "Décisions" },
  { id: "actions", label: "Actions" },
  { id: "participants", label: "Participants" },
  { id: "reviews", label: "Tour de table" },
  { id: "recordings", label: "Enregistrements" },
] as const;
export type TabId = (typeof TABS)[number]["id"];

const dateFmt = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" });
const timeFmt = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });
const longFmt = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

export const fmtDate = (v: string | null | undefined) => (v ? dateFmt.format(new Date(v)) : "—");
export const fmtTime = (v: string | null | undefined) => (v ? timeFmt.format(new Date(v)) : "");
export const fmtDateTime = (v: string | null | undefined) => (v ? `${fmtDate(v)} ${fmtTime(v)}` : "—");
export const fmtLong = (v: string | null | undefined) => (v ? longFmt.format(new Date(v)) : "—");

/** « dans 3 jours » / « il y a 2 h » (équivalent de `timeuntil` / `naturaltime`). */
export function relative(v: string | null | undefined, now = Date.now()): string {
  if (!v) return "";
  const diff = new Date(v).getTime() - now;
  const abs = Math.abs(diff) / 1000;
  const rtf = new Intl.RelativeTimeFormat("fr-FR", { numeric: "auto" });
  const sign = diff < 0 ? -1 : 1;
  if (abs < 60) return rtf.format(sign * Math.round(abs), "second");
  if (abs < 3600) return rtf.format(sign * Math.round(abs / 60), "minute");
  if (abs < 86400) return rtf.format(sign * Math.round(abs / 3600), "hour");
  if (abs < 86400 * 30) return rtf.format(sign * Math.round(abs / 86400), "day");
  if (abs < 86400 * 365) return rtf.format(sign * Math.round(abs / (86400 * 30)), "month");
  return rtf.format(sign * Math.round(abs / (86400 * 365)), "year");
}

/** mm:ss (chronomètre de l'enregistreur). */
export function formatDuration(ms: number): string {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/** Secondes → « 1 h 05 min » / « 12 min » / « 40 s ». */
export function humanSeconds(seconds: number | null | undefined): string {
  const s = Math.round(seconds ?? 0);
  if (s < 60) return `${s} s`;
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  return h ? `${h} h ${String(m).padStart(2, "0")} min` : `${m} min`;
}

/**
 * Anciennes pages génériques `/m/meeting…` (pont ressources) → pages réunions dédiées.
 * Conserve les liens déjà partagés et les liens « ressource » des autres modules.
 */
export function meetingModuleTarget(pathname: string, search = ""): string {
  const m = pathname.match(/\/m\/(meeting|meeting-series|meeting-decision)(?:\/(new|\d+))?(\/edit)?\/?$/);
  if (!m) return "/meetings";
  const [, kind, id, edit] = m;
  const base = kind === "meeting-series" ? "/meetings/series" : kind === "meeting-decision" ? "/meetings/decisions" : "/meetings";
  if (kind === "meeting-decision" || !id) return `${base}${search}`;
  return `${base}/${id}${edit ? "/edit" : ""}${id === "new" ? search : ""}`;
}
