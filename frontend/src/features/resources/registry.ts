/**
 * Modules servis par le pont générique `/api/v1/resources/` (vues Django CRUD existantes).
 * Chemin legacy de liste → nom de ressource : sert à la navigation et à la traduction des liens.
 */
export const RESOURCE_PATHS: Record<string, string> = {
  "/roadmaps/": "roadmap", "/roadmap-items/": "roadmap-item", "/milestones/": "milestone",
  "/milestone-tasks/": "milestone-task", "/releases/": "release", "/objectives/": "objective",
  "/key-results/": "key-result", "/risks/": "risk", "/project-members/": "project-member",
  "/project-labels/": "project-label", "/project-imports/": "project-import", "/ai-insights/": "ai-insight",
  "/ai-proposals/": "ai-proposal", "/backlog-items/": "backlog-item", "/sprints/": "sprint",
  "/sprint-reviews/": "sprint-review", "/sprint-retrospectives/": "sprint-retrospective",
  "/sprint-metrics/": "sprint-metric", "/board-columns/": "board-column", "/pull-requests/": "pull-request",
  "/task-checklists/": "task-checklist", "/checklist-items/": "checklist-item",
  "/task-dependencies/": "task-dependency", "/task-labels/": "task-label", "/task-assignments/": "task-assignment",
  "/project-expenses/": "project-expense", "/billing/invoices/": "invoice", "/billing/clients/": "invoice-client",
  "/meetings/": "meeting", "/meetings/series/": "meeting-series", "/meetings/decisions/": "meeting-decision",
  "/workspace-settings/": "workspace-settings", "/workspace-invitations/": "workspace-invitation",
  "/labels/": "label", "/integrations/": "integration", "/webhooks/": "webhook", "/api-keys/": "api-key",
  "/admin/methodologies/": "methodology", "/activity-logs/": "activity-log",
};

/** `/sprints/12/` → `/m/sprint/12` ; `/sprints/` → `/m/sprint`. */
export function resourceRoute(pathname: string): string | null {
  const m = pathname.match(/^(\/.*?\/)(?:(\d+)\/?)?$/);
  if (!m) return null;
  const name = m[1] ? RESOURCE_PATHS[m[1]] : undefined;
  if (!name) return null;
  return m[2] ? `/m/${name}/${m[2]}` : `/m/${name}`;
}
