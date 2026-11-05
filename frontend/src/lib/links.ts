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
];

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
