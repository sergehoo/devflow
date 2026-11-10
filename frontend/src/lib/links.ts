/**
 * Traduit une URL de l'ancien frontend (notifications, e-mails…) vers la route React
 * équivalente quand le module est migré ; sinon renvoie l'URL legacy.
 * Seuls les chemins relatifs du même site sont acceptés (pas de redirection ouverte).
 */
import { resourceRoute } from "@/features/resources/registry";
import { legacyUrl } from "@/lib/utils";

export type ResolvedLink = { kind: "app"; to: string } | { kind: "legacy"; href: string };

const RULES: [RegExp, (m: RegExpMatchArray, query: URLSearchParams) => string][] = [
  [/^\/$/, () => "/"],
  // --- projet --- fiche projet : onglet conservé (`?tab=`), modification → formulaire React.
  [/^\/projects\/(\d+)\/?$/, (m, q) => (q.get("tab") ? `/projects/${m[1]}?tab=${encodeURIComponent(q.get("tab")!)}` : `/projects/${m[1]}`)],
  [/^\/projects\/(\d+)\/update\/?$/, (m) => `/projects/${m[1]}/edit`],
  // Tableau de bord méthodologie et espaces Scrum / Kanban / Waterfall : intégrés à la fiche (`?space=`).
  [/^\/projects\/(\d+)\/dashboard\/?$/, (m) => `/projects/${m[1]}?space=dashboard`],
  [/^\/projects\/(\d+)\/(scrum|kanban|waterfall)\/?$/, (m) => `/projects/${m[1]}?space=workspace`],
  // --- fin projet ---
  [/^\/(tasks|projects|teams|workspaces)\/(\d+)\/?$/, (m) => `/${m[1]}/${m[2]}`],
  [/^\/(tasks|projects|teams|workspaces)\/?$/, (m) => `/${m[1]}`],
  [/^\/chat\/?$/, (_m, q) => (q.get("channel") ? `/messenger?channel=${encodeURIComponent(q.get("channel")!)}` : "/messenger")],
  [/^\/channels\/(\d+)\/?$/, (m) => `/messenger?channel=${m[1]}`],
  [/^\/timesheets\/?$/, () => "/timesheets"],
  // /timesheets/list/ = toutes les semaines visibles (soi + N-1…) quel que soit le statut.
  [/^\/timesheets\/list\/?$/, () => "/timesheets/validation?scope=all&status="],
  [/^\/notifications\/?$/, () => "/notifications"],
  [/^\/my-day\/?$/, () => "/my-day"],
  [/^\/billing\/branding\/?$/, () => "/branding"],
  [/^\/team-memberships\/?$/, () => "/members"],
  [/^\/profile\/(?:update\/|password\/)?$/, () => "/profile"],
  // --- finance ---
  [/^\/workspaces\/\d+\/financial-ai\/portfolio\/?$/, () => "/finance/portfolio"],
  [/^\/workspaces\/\d+\/financial-ai\/allocation\/view\/?$/, () => "/finance/allocation"],
  [/^\/billing\/invoices\/(\d+)\/(?:update\/)?$/, (m) => `/invoices/${m[1]}`],
  // --- tickets ---
  [/^\/tickets\/(\d+)\/?$/, (m) => `/tickets/${m[1]}`],
  [/^\/tickets\/email\/?$/, () => "/tickets/email"],
  // --- meetings --- (avant le pont générique : pages réunions dédiées)
  [/^\/meetings\/?$/, (_m, q) => withQuery("/meetings", q, ["project", "type", "status", "q", "page"])],
  [/^\/meetings\/create\/?$/, (_m, q) => withQuery("/meetings/new", q, ["project"])],
  [/^\/meetings\/dashboard\/?$/, () => "/meetings/dashboard"],
  [/^\/meetings\/decisions\/?$/, (_m, q) => withQuery("/meetings/decisions", q, ["status", "category"])],
  [/^\/meetings\/series\/?$/, () => "/meetings/series"],
  [/^\/meetings\/series\/create\/?$/, () => "/meetings/series/new"],
  [/^\/meetings\/series\/(\d+)\/?$/, (m) => `/meetings/series/${m[1]}`],
  [/^\/meetings\/series\/(\d+)\/update\/?$/, (m) => `/meetings/series/${m[1]}/edit`],
  [/^\/meetings\/(\d+)\/?$/, (m) => `/meetings/${m[1]}`],
  [/^\/meetings\/(\d+)\/update\/?$/, (m) => `/meetings/${m[1]}/edit`],
  [/^\/meetings\/(\d+)\/recordings\/?$/, (m) => `/meetings/${m[1]}?tab=recordings`],
  [/^\/meetings\/(\d+)\/recordings\/(\d+)\/(?:summary|speakers)\/?$/, (m) => `/meetings/${m[1]}/recordings/${m[2]}`],
  // --- fin meetings ---
  // --- ai --- Genesis, propositions IA, imports documentaires, copilote
  [/^\/ai\/genesis\/?$/, () => "/projects/genesis"],
  [/^\/ai-proposals\/(\d+)(?:\/(?:regenerate|items\/\d+\/edit))?\/?$/, (m) => `/ai-proposals/${m[1]}`],
  [/^\/ai-proposals\/?$/, (_m, q) => {
    const keep = new URLSearchParams([...q].filter(([k, v]) => (k === "status" || k === "project") && v));
    return keep.toString() ? `/ai-proposals?${keep}` : "/ai-proposals";
  }],
  [/^\/projects\/(\d+)\/ai-proposals\/?$/, (m) => `/projects/${m[1]}/ai-proposals`],
  [/^\/projects\/(\d+)\/copilot\/logs\/?$/, (m) => `/projects/${m[1]}/copilot?tab=logs`],
  [/^\/project-imports\/(\d+)\/?$/, (m) => `/imports/${m[1]}`],
  [/^\/project-imports\/create\/?$/, (_m, q) => (/^\d+$/.test(q.get("project") ?? "") ? `/imports?new=1&project=${q.get("project")}` : "/imports?new=1")],
  [/^\/project-imports\/?$/, () => "/imports"],
  // --- fin ai ---
];

/** Recopie les paramètres GET utiles (`?project=12`) dans la route React. */
function withQuery(path: string, query: URLSearchParams, keys: string[]): string {
  const kept = new URLSearchParams();
  keys.forEach((k) => { const v = query.get(k); if (v) kept.set(k, v); });
  const qs = kept.toString();
  return qs ? `${path}?${qs}` : path;
}

export function resolveLegacyLink(url: string | null | undefined): ResolvedLink | null {
  if (!url || !url.startsWith("/") || url.startsWith("//") || url.startsWith("/\\")) return null;
  const parsed = new URL(url, "http://devflow.local");
  for (const [pattern, build] of RULES) {
    const match = parsed.pathname.match(pattern);
    if (match) return { kind: "app", to: build(match, parsed.searchParams) };
  }
  const module = resourceRoute(parsed.pathname);
  if (module) return { kind: "app", to: module };
  return { kind: "legacy", href: legacyUrl(parsed.pathname + parsed.search + parsed.hash) };
}
