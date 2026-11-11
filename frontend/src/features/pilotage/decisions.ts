/**
 * Décisions de l'assistant d'import : la valeur effective est la proposition de l'analyse,
 * remplacée par le choix explicite de l'utilisateur. Rien n'est corrigé d'office.
 */
import type { Ambiguity, ImportAnalysis, ImportDecisions } from "./api";

export type Group = "people" | "companies" | "statuses" | "rows" | "items" | "alerts";

export function withPatch(decisions: ImportDecisions, group: Group, key: string, value: object): ImportDecisions {
  const current = (decisions[group] ?? {}) as Record<string, object>;
  return { ...decisions, [group]: { ...current, [key]: { ...current[key], ...value } } };
}

export function chosen<T extends object>(decisions: ImportDecisions, group: Group, key: string, fallback: T): T {
  return { ...fallback, ...((decisions[group] ?? {}) as Record<string, Partial<T>>)[key] };
}

/** `null` est un choix valide (« ne pas renseigner ») : on teste la présence de la clé. */
export function ambiguityValue(decisions: ImportDecisions, ambiguity: Ambiguity) {
  return decisions.ambiguities && ambiguity.id in decisions.ambiguities ? decisions.ambiguities[ambiguity.id] : ambiguity.default;
}

const counter = () => ({ create: 0, link: 0, update: 0, skip: 0 });

/** Ce que l'import fera avec les décisions courantes (récapitulatif avant application). */
export function planOf(analysis: ImportAnalysis, decisions: ImportDecisions) {
  const plan = { projects: counter(), tasks: counter(), items: counter(), alerts: counter() };
  analysis.rows.forEach((row) => {
    const { action } = chosen(decisions, "rows", row.id, row.default);
    plan[row.section][action] += 1;
    if (action === "skip") return;
    row.next.forEach((item) => { plan.items[chosen(decisions, "items", item.id, item.default).action] += 1; });
    row.alerts.forEach((alert) => { plan.alerts[chosen(decisions, "alerts", alert.id, alert.default).action] += 1; });
  });
  return {
    ...plan,
    unresolved: analysis.people
      .filter((p) => p.roles.includes("PORTEUR") && chosen(decisions, "people", p.key, p.default).user_id == null)
      .map((p) => p.name),
    ambiguitiesKept: analysis.ambiguities.filter((a) => ambiguityValue(decisions, a) === a.default).length,
  };
}
