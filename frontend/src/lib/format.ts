const nf = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 });
const df = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
const dtf = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

export const formatNumber = (v: number | string | null | undefined) => nf.format(Number(v ?? 0));

export const formatMoney = (v: number | string | null | undefined, currency = "XOF") =>
  `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(Number(v ?? 0))} ${currency}`;

export const formatHours = (v: number | string | null | undefined) => `${nf.format(Number(v ?? 0))} h`;

/** Dates ISO « YYYY-MM-DD » interprétées en local (pas de décalage UTC). */
export function parseISODate(value: string): Date {
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  return new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1);
}

export const formatDate = (v: string | null | undefined) => (v ? df.format(parseISODate(v)) : "—");
export const formatDateTime = (v: string | null | undefined) => (v ? dtf.format(new Date(v)) : "—");

export function toISODate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
