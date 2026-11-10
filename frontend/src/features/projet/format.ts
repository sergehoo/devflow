/** Correspondances d'affichage (statuts → couleurs du thème) et formats de la fiche projet. */
import { formatMoney } from "@/lib/format";

export const TONE = {
  success: "bg-success/15 text-success",
  warning: "bg-warning/15 text-warning",
  danger: "bg-destructive/10 text-destructive",
  info: "bg-info/15 text-info",
  primary: "bg-primary/10 text-brand",
  muted: "",
} as const;
export type Tone = keyof typeof TONE;

/** Couleurs des statuts : mêmes correspondances que les partials historiques. */
export const severityTone = (s: string): Tone => (s === "CRITICAL" || s === "HIGH" ? "danger" : s === "MEDIUM" ? "warning" : "info");
export const expenseTone = (s: string): Tone =>
  ({ PAID: "success", VALIDATED: "success", COMMITTED: "warning", ACCRUED: "info", REJECTED: "danger" } as Record<string, Tone>)[s] ?? "muted";
export const approvalTone = (s: string): Tone =>
  ({ LEVEL2_APPROVED: "success", LEVEL1_APPROVED: "info", REJECTED: "danger" } as Record<string, Tone>)[s] ?? "muted";
export const invoiceTone = (s: string): Tone =>
  ({ PAID: "success", OVERDUE: "danger", DRAFT: "muted" } as Record<string, Tone>)[s] ?? "info";
export const revenueTone = (s: string): Tone =>
  ({ PAID: "success", PARTIALLY_PAID: "info", INVOICED: "primary", CANCELLED: "danger" } as Record<string, Tone>)[s] ?? "warning";
export const colorTone = (c: string): Tone =>
  ({ green: "success", red: "danger", amber: "warning", cyan: "info", purple: "primary" } as Record<string, Tone>)[c] ?? "muted";

/** Montant autorisé par Django, sinon masqué (`null` = pas de droit financier). */
export const money = (v: string | null | undefined, currency = "XOF") => (v == null ? "••••" : formatMoney(v, currency));
export const percent = (v: string | number | null | undefined, digits = 0) =>
  `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: digits }).format(Number(v ?? 0))} %`;

