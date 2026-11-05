export const STATUS_TONE: Record<string, string> = {
  SUBMITTED: "bg-info/15 text-info", APPROVED: "bg-success/15 text-success", REJECTED: "bg-destructive/10 text-destructive",
};

/** Libellés de l'interface Django (liste des semaines, aide du module) : semaine Brouillon / Soumise / Validée / Rejetée. */
export const APPROVAL_STATUSES = [
  { value: "DRAFT", label: "Brouillon" }, { value: "SUBMITTED", label: "Soumise" },
  { value: "APPROVED", label: "Validée" }, { value: "REJECTED", label: "Rejetée" },
];
const LABELS: Record<string, string> = Object.fromEntries(APPROVAL_STATUSES.map((s) => [s.value, s.label]));
export const statusLabel = (status: string, fallback = "") => LABELS[status] ?? fallback;

/** Bandeau de la semaine en cours, identique au calendrier Django. */
export const WEEK_BANNER: Record<string, string> = {
  DRAFT: "Brouillon", SUBMITTED: "En attente de validation",
  APPROVED: "Validée — verrouillée", REJECTED: "Rejetée — corrigez et re-soumettez",
};
