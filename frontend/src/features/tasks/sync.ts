import { useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";

/**
 * Écrans qui affichent des tâches. Côté Django il n'y a qu'une tâche (`dm.Task`) : la liste
 * et la fiche tâche, le timesheet, la fiche projet, la liste des projets, le tableau de bord,
 * « Ma journée » et le Suivi Pôle Développement la lisent tous. Une écriture sur une tâche,
 * une affectation ou une saisie de temps doit donc les invalider ensemble — sinon l'écran
 * resté en cache contredit les autres.
 */
export const TASK_VIEW_KEYS: readonly QueryKey[] = [
  ["tasks"], ["timesheet"], ["projet"], ["projects"], ["dashboard"], ["me", "today"],
];

/** Suivi : tout sauf l'assistant d'import, dont les écrans gèrent leur propre état. */
const isTrackingView = (key: QueryKey) => key[0] === "tracking" && key[1] !== "imports";

export function invalidateTaskViews(qc: QueryClient) {
  return Promise.all([
    ...TASK_VIEW_KEYS.map((queryKey) => qc.invalidateQueries({ queryKey })),
    qc.invalidateQueries({ queryKey: ["tracking"], predicate: (q) => isTrackingView(q.queryKey) }),
  ]);
}

export function useInvalidateTaskViews() {
  const qc = useQueryClient();
  return () => invalidateTaskViews(qc);
}
