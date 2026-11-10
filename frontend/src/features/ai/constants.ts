/** Constantes d'affichage du chantier « ai » (aucune règle métier : Django reste l'autorité). */

const tone = {
  info: "bg-info/15 text-info",
  warning: "bg-warning/15 text-warning",
  success: "bg-success/15 text-success",
  danger: "bg-destructive/15 text-destructive",
} as const;

/** Couleurs des statuts (ProjectAIProposal.Status, ProjectAIProposalItem.ItemStatus, imports, journal IA). */
export const STATUS_TONE: Record<string, string> = {
  PENDING: tone.info, GENERATING: tone.info, READY: tone.warning, PARTIALLY_VALIDATED: tone.warning,
  VALIDATED: tone.success, APPLIED: tone.success, REJECTED: tone.danger, FAILED: tone.danger,
  PROPOSED: tone.info, EDITED: tone.warning,
  UPLOADED: tone.warning, PROCESSING: tone.info, COMPLETED: tone.success,
  SUCCESS: tone.success, DENIED: tone.warning, UNDONE: tone.info,
};

/** Libellés des éléments générés (compteurs de ProposalApplyService / Genesis). */
export const COUNT_LABELS: Record<string, string> = {
  roadmap: "phase(s) de roadmap", milestones: "jalon(s)", sprints: "sprint(s)", backlog: "élément(s) de backlog",
  tasks: "tâche(s)", dependencies: "dépendance(s)", assignments: "affectation(s)",
};

/** Types d'éléments d'une proposition (ProjectAIProposalItem.Kind) : onglet + libellé pluriel. */
export const KIND_TABS: { kind: string; tab: string; plural: string }[] = [
  { kind: "TASK", tab: "Tâches", plural: "tâche(s)" },
  { kind: "SPRINT", tab: "Sprints", plural: "sprint(s)" },
  { kind: "MILESTONE", tab: "Jalons", plural: "jalon(s)" },
  { kind: "ROADMAP_ITEM", tab: "Roadmap", plural: "phase(s) de roadmap" },
  { kind: "BACKLOG", tab: "Backlog", plural: "élément(s) de backlog" },
  { kind: "DEPENDENCY", tab: "Dépendances", plural: "dépendance(s)" },
  { kind: "ASSIGNMENT", tab: "Affectations", plural: "affectation(s)" },
];

/** Statuts d'élément (filtre de l'aperçu). */
export const ITEM_STATUSES = [
  { value: "PROPOSED", label: "Proposés" }, { value: "EDITED", label: "Modifiés" }, { value: "VALIDATED", label: "Validés" },
  { value: "REJECTED", label: "Rejetés" }, { value: "APPLIED", label: "Appliqués" },
];

/** Champs d'édition pertinents par type d'élément ; les autres sont renvoyés inchangés (formulaire Django complet). */
export const ITEM_VISIBLE_FIELDS: Record<string, string[]> = {
  TASK: ["title", "description", "priority", "complexity", "estimate_hours", "recommended_profile", "recommended_assignee", "sprint_ref", "milestone_ref"],
  SPRINT: ["title", "description", "start_date", "end_date", "velocity_target"],
  MILESTONE: ["title", "description", "end_date"],
  ROADMAP_ITEM: ["title", "description", "start_date", "end_date"],
  BACKLOG: ["title", "description", "priority", "estimate_hours"],
};

/** Suggestions du copilote (identiques au panneau historique). */
export const COPILOT_SUGGESTIONS = [
  { label: "Crée-moi le prochain sprint", prompt: "Crée-moi le prochain sprint avec une durée de 2 semaines" },
  { label: "Quels sont les risques actuels ?", prompt: "Quels sont les risques actuels du projet ?" },
  { label: "Qui est surchargé dans l'équipe ?", prompt: "Qui est surchargé dans l'équipe ?" },
  { label: "Analyse la santé globale du projet", prompt: "Analyse la santé globale du projet" },
];

/** Au-delà, le suivi de génération cesse d'interroger le serveur (génération bloquée / worker indisponible). */
export const MAX_POLL_MS = 6 * 60_000;
