/** Colonnes du board (mêmes statuts et ordre que TaskListView). */
export const STATUS_COLUMNS = [
  { value: "TODO", label: "À faire", dot: "bg-subtle-foreground" },
  { value: "IN_PROGRESS", label: "En cours", dot: "bg-primary" },
  { value: "REVIEW", label: "Review", dot: "bg-warning" },
  { value: "DONE", label: "Terminé", dot: "bg-success" },
  { value: "BLOCKED", label: "Bloqué", dot: "bg-destructive" },
  { value: "CANCELLED", label: "Annulé", dot: "bg-muted-foreground/40" },
] as const;

export const STATUS_BADGE: Record<string, string> = {
  IN_PROGRESS: "bg-primary/10 text-primary", REVIEW: "bg-warning/15 text-warning", DONE: "bg-success/15 text-success",
  BLOCKED: "bg-destructive/10 text-destructive",
};

export const isOverdue = (due: string | null, status: string) =>
  !!due && !["DONE", "CANCELLED"].includes(status) && new Date(`${due}T23:59:59`) < new Date();
