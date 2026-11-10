export const STATUSES = [
  { value: "NEW", label: "Nouveau", dot: "bg-info" },
  { value: "QUALIFIED", label: "Qualifié", dot: "bg-subtle-foreground" },
  { value: "ASSIGNED", label: "Assigné", dot: "bg-primary-strong" },
  { value: "IN_PROGRESS", label: "En cours", dot: "bg-primary" },
  { value: "WAITING", label: "En attente", dot: "bg-warning" },
  { value: "RESOLVED", label: "Résolu", dot: "bg-success" },
  { value: "CLOSED", label: "Clôturé", dot: "bg-muted-foreground" },
  { value: "CANCELLED", label: "Annulé", dot: "bg-destructive" },
] as const;

export const OPEN_STATUSES = ["NEW", "QUALIFIED", "ASSIGNED", "IN_PROGRESS", "WAITING"];
export const BOARD_STATUSES = ["NEW", "QUALIFIED", "ASSIGNED", "IN_PROGRESS", "WAITING", "RESOLVED"];

export const PRIORITIES = [
  { value: "P1", label: "P1 — Urgente", pill: "bg-destructive/10 text-destructive" },
  { value: "P2", label: "P2 — Haute", pill: "bg-warning/10 text-warning" },
  { value: "P3", label: "P3 — Normale", pill: "bg-primary-faint text-brand" },
  { value: "P4", label: "P4 — Basse", pill: "bg-hover text-muted-foreground" },
] as const;

export const SEVERITIES = [
  { value: "CRITICAL", label: "Critique" }, { value: "MAJOR", label: "Majeure" },
  { value: "MINOR", label: "Mineure" }, { value: "TRIVIAL", label: "Triviale" },
] as const;

export const CATEGORIES = [
  { value: "BUG", label: "Anomalie" }, { value: "INCIDENT", label: "Incident" }, { value: "QUESTION", label: "Question" },
  { value: "FEATURE", label: "Demande d'évolution" }, { value: "ACCESS", label: "Accès / compte" }, { value: "OTHER", label: "Autre" },
] as const;

export const WEBHOOK_EVENTS = [
  "ticket.created", "ticket.assigned", "ticket.updated", "ticket.commented", "ticket.resolved", "ticket.closed", "ticket.reopened",
];

export const EVENT_LABELS: Record<string, string> = {
  created: "Ticket créé", assigned: "Affectation", status_changed: "Changement de statut", commented: "Commentaire",
  updated: "Qualification", escalated: "Escalade", sla_breached: "SLA dépassé", sla_warning: "Alerte SLA",
  task_created: "Tâche DevFlow créée", attachment_added: "Pièce jointe", unassigned_queue: "File non assignée",
  email_failed: "E-mail non délivré",
};

export const statusMeta = (v: string) => STATUSES.find((s) => s.value === v) ?? STATUSES[0];
export const priorityMeta = (v: string) => PRIORITIES.find((p) => p.value === v) ?? PRIORITIES[2];

/** Durée restante lisible (négative = dépassée). */
export function remaining(seconds: number | null): string {
  if (seconds == null) return "—";
  const abs = Math.abs(seconds);
  const h = Math.floor(abs / 3600), m = Math.floor((abs % 3600) / 60);
  const text = h >= 48 ? `${Math.round(h / 24)} j` : h ? `${h} h ${m.toString().padStart(2, "0")}` : `${m} min`;
  return seconds < 0 ? `dépassé de ${text}` : text;
}

export function dueIn(iso: string | null): number | null {
  return iso ? Math.round((new Date(iso).getTime() - Date.now()) / 1000) : null;
}

export const ATTACHMENT_ACCEPT =
  "image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain,text/csv,application/json,application/zip,video/mp4,video/webm";
