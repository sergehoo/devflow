/**
 * Fiche projet complète : `/api/v1/projects/<id>/detail-tabs/` (contexte de ProjectDetailView côté Django).
 * Les montants sont des chaînes (Decimal) ; `null` = donnée financière non autorisée par Django.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, actionBody } from "@/services/api";

type Money = string;
type Restricted = string | null;

export type TabKey =
  | "planification" | "budget_estimatif" | "budget_previsionnel" | "facturation_client" | "depenses"
  | "equipes" | "evolution" | "taches" | "kpi_roi" | "documents" | "meetings";

export interface ProjectHeader {
  id: number; name: string; code: string; category: string;
  status: string; status_label: string; priority: string; priority_label: string;
  health_status: string; health_status_label: string; methodology: string; methodology_label: string;
  progress_percent: number; risk_score: number; ai_risk_label: string; description_html: string;
  owner: string; product_manager: string; workspace: string; workspace_id: number;
  start_date: string | null; target_date: string | null; delivered_at: string | null;
  team: string; team_id: number | null; tech_stack: string;
  labels: { id: number; name: string; color: string }[];
  budget_id: number | null; budget_status_label: string;
}

export interface Dependencies {
  count: number; blocking: number; related: number;
  items: { id: number; from_task: { id: number; title: string }; to_task: { id: number; title: string }; type: string; type_label: string }[];
}

export interface PlanningTab {
  key: "planification";
  stats: Record<"milestones_count" | "releases_count" | "sprints_count" | "backlog_count" | "roadmap_items_count" | "planning_items_count", number>;
  milestones: { id: number; name: string; due_date: string | null; owner: string; status: string; status_label: string; progress_percent: number }[];
  sprints: { id: number; name: string; start_date: string | null; end_date: string | null; status: string; status_label: string; tasks_count: number; backlog_count: number; metrics_count: number }[];
  releases: { id: number; name: string; release_date: string | null; tag: string; status: string; status_label: string }[];
  roadmap_items: { id: number; title: string; color: string; status: string; status_label: string; roadmap: string; roadmap_id: number | null; start_date: string | null; end_date: string | null; duration_days: number; milestone: string; bar_percent: number }[];
  backlog: { id: number; title: string; item_type_label: string; sprint: string; story_points: number; reporter: string }[];
  dependencies: Dependencies;
  ai_alerts: { id: number; title: string; summary: string; recommendation: string; severity: string; severity_label: string }[];
}

export interface EstimateTab {
  key: "budget_estimatif"; currency: string; budget_id: number | null;
  cards: Record<"labor_cost" | "software_cost" | "infra_cost" | "subcontract_cost" | "total_estimated", Money>;
  markup_percent: Money; total_estimated_sale: Money; planned_revenue: Money; total_estimated_margin: Money;
  baseline_cost: Money; forecast_cost: Money; raf_cost: Money;
  lines: { id: number; label: string; category: string; budget_stage_label: string; source_type_label: string; quantity: Money; cost_unit_amount: Money; cost_amount: Money; sale_amount: Money; margin_amount: Money }[];
}

export interface ForecastTab {
  key: "budget_previsionnel"; currency: string; budget_id: number | null;
  approved_budget: Money; planned_revenue: Money; actual_cost: Money; forecast_margin: Money;
  target_margin_percent: number; profit_margin_percent: number; expense_ratio_percent: number;
  invoiced_revenue: Money; received_revenue: Money; remaining_to_invoice: Money; remaining_to_collect: Money;
  revenues: { id: number; title: string; revenue_type_label: string; amount: Money; invoiced_amount: Money; received_amount: Money; currency: string; expected_date: string | null; is_received: boolean }[];
}

export interface ExpensesTab {
  key: "depenses"; currency: string;
  stats: Record<"total_expenses" | "estimated_expenses" | "forecast_expenses" | "committed_expenses" | "accrued_expenses" | "paid_expenses" | "rejected_expenses" | "labor_cost" | "direct_cost" | "other_cost" | "validated_expenses" | "draft_expenses", Money>;
  expenses: { id: number; expense_date: string | null; created_at: string | null; title: string; description: string; reference: string; is_direct_cost: boolean; is_labor_cost: boolean; status: string; status_label: string; approval_state: string; approval_state_label: string; amount: Money; currency: string; can_be_edited: boolean }[];
}

export interface BillingTab {
  key: "facturation_client"; currency: string;
  invoice_summary: { total_ttc: Money; total_paid: Money; total_due: Money; count_total: number; count_overdue: number; count_draft: number; count_paid: number };
  invoices: { id: number; number: string; billing_mode_label: string; client: string; issue_date: string | null; due_date: string | null; total_ttc: Money; paid_amount: Money; currency: string; status: string; status_label: string }[];
  invoices_total: number;
  /** RBAC `invoice.create` (Django) : génération de facture autorisée. */
  can_generate_invoice: boolean;
  billing: { planned_revenue: Money; invoiced_revenue: Money; received_revenue: Money; remaining_to_invoice: Money; remaining_to_collect: Money; collection_rate_percent: number; invoicing_rate_percent: number };
  revenues: { id: number; title: string; notes: string; revenue_type_label: string; amount: Money; currency: string; invoiced_amount: Money; received_amount: Money; remaining_to_invoice: Money; remaining_to_collect: Money; expected_date: string | null; status: string; status_label: string }[];
}

export interface TeamTab {
  key: "equipes";
  /** Ajout / modification / retrait d'affectations autorisés (mêmes droits que les vues Django ProjectMember*). */
  can_manage_members: boolean;
  /** Droits financiers sans `billing.view` : coûts TJM non servis par Django. */
  member_costs_restricted: boolean;
  members: { id: number; user_id: number; name: string; team: string; role: string; allocation_percent: number; is_primary: boolean }[];
  team_summary: { team_id: number | null; team: string; members_count: number; primary_count: number }[];
  primary_total: number; allocation_average: number;
  timesheet_stats: { total_entries: number; total_hours: Money; approved_hours: Money; submitted_hours: Money };
  member_costs: null | {
    currency: string;
    summary: { count: number; project_working_days: number; daily_cost_total: Money; daily_sale_total: Money; monthly_cost_total: Money; monthly_sale_total: Money; project_cost_total: Money; project_sale_total: Money; project_margin_total: Money };
    rows: { member_id: number; name: string; allocation_percent: Money; daily_cost: Money; daily_sale: Money; allocated_daily_cost: Money; allocated_monthly_cost: Money; allocated_project_cost: Money; allocated_project_sale: Money }[];
  };
}

export interface EvolutionTab {
  key: "evolution";
  summary: { activities_count: number; pull_requests_count: number; risks_count: number; insights_count: number };
  activities: { id: number; title: string; description: string; created_at: string | null; actor: string }[];
  pull_requests: { id: number; title: string; repository: string; branch_name: string; author: string; status_label: string; url: string }[];
  risks: { id: number; title: string; severity: string; severity_label: string; status_label: string; owner: string }[];
  insights: { id: number; title: string; summary: string; task: string; task_id: number | null; sprint: string; insight_type_label: string; severity: string; severity_label: string; is_dismissed: boolean }[];
}

export interface TasksTab {
  key: "taches";
  stats: { total: number; todo: number; in_progress: number; review: number; done: number; blocked: number; cancelled: number; overdue: number; flagged: number; total_estimate_hours: Money; total_spent_hours: Money };
  has_board: boolean;
  /** Board Kanban du projet (colonnes BoardColumn, tâches regroupées par Django selon `mapped_status`). */
  board: { id: number; name: string; mapped_status: string; color: string; wip_limit: number | null; is_done_column: boolean; count: number; over_wip: boolean; task_ids: number[] }[];
  tasks: { id: number; title: string; backlog_item: string; parent: string; parent_id: number | null; status: string; status_label: string; priority: string; priority_label: string; assignee: string; assignee_id: number | null; estimate_hours: Money; spent_hours: Money; due_date: string | null }[];
  dependencies: Dependencies;
}

export interface KpiTab {
  key: "kpi_roi";
  kpi_summary: { count: number; modules_count: number };
  roi_summary: { count: number; global_roi_percent: Money; total_cost: Restricted; total_revenue: Restricted };
  kpis: { id: number; name: string; module_name: string; value: Money | null; value_text: string; unit: string }[];
  module_rois: { id: number; module_name: string; roi_percent: Money; estimated_cost: Restricted; estimated_revenue: Restricted }[];
  sprint_finance: { count: number; total_estimated_cost: Money } | null;
  feature_finance: { count: number; total_estimated_cost: Money; total_estimated_revenue: Money; global_roi_percent: Money } | null;
}

export interface ProjectDocument {
  id: number; name: string; url: string | null; ext: string; type_label: string; has_text: boolean;
  status: string; status_label: string; uploaded_by: string; created_at: string | null; error_message: string;
}

export interface DocumentsTab {
  key: "documents";
  summary: { count: number; completed: number; processing: number; failed: number };
  documents: ProjectDocument[];
}

export interface MeetingsTab {
  key: "meetings"; count: number;
  meetings: { id: number; title: string; scheduled_at: string | null; meeting_type_label: string; status: string; status_label: string; status_color: string; action_items_count: number }[];
}

export type TabData = PlanningTab | EstimateTab | ForecastTab | ExpensesTab | BillingTab | TeamTab | EvolutionTab | TasksTab | KpiTab | DocumentsTab | MeetingsTab;

export type ModeData =
  | { kind: "waterfall"; phases: { id: number; name: string; description: string; gate_required: boolean; status: string; status_label: string; start_date: string | null; end_date: string | null; owner: string; progress_percent: number }[] }
  | { kind: "field"; reports: { id: number; report_date: string | null; location_name: string; location: string; weather: string; weather_label: string; workforce_count: number; notes: string; incidents: string; reporter: string; created_at: string | null; photos_count: number; photos: { id: number; url: string | null; caption: string }[] }[] }
  | { kind: "real_estate"; groups: { status: string; label: string; count: number }[]; lots: { id: number; lot_number: string; floor: string; surface_m2: Money; bedrooms: number; price: Money | null; currency: string; status: string; status_label: string; buyer_name: string }[] }
  | { kind: "administrative"; cases: { id: number; reference: string; title: string; applicant: string; document_type: string; status: string; status_label: string; deadline: string | null; sla_days: number | null; is_overdue: boolean; assignee: string }[] };

export interface ProjectDetail {
  project: ProjectHeader;
  can_view_financials: boolean;
  kpis: { progress_percent: number; risk_score: number; tasks_total: number; members_count: number; actual_cost: Restricted; received_revenue: Restricted; currency: string };
  band: { todo: number; in_progress: number; blocked: number; overdue: number; imports: number; imports_completed: number; insights_total: number; insights_critical: number; approved_budget: Restricted; actual_cost: Restricted; forecast_margin: Restricted };
  mode: ModeData | null;
  tabs: { key: TabKey; label: string; count: number }[];
  active_tab: TabKey;
  tab: TabData;
}

export const projetKey = (id: number) => ["projet", id] as const;

export const useProjectDetail = (id: number, tab: string) =>
  useQuery({
    queryKey: [...projetKey(id), "detail", tab],
    queryFn: ({ signal }) => api<ProjectDetail>(`projects/${id}/detail-tabs/`, { signal, params: { tab } }),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });

/** Invalide la fiche (tous onglets) + listes projets / tâches dépendantes. */
export function useInvalidateProject(id: number) {
  const qc = useQueryClient();
  return () => Promise.all([
    qc.invalidateQueries({ queryKey: projetKey(id) }),
    qc.invalidateQueries({ queryKey: ["projects"] }),
  ]);
}

// ─── Génération IA de la structure (roadmap, jalons, sprints, backlog, tâches) ───
export interface GenerationStatus {
  proposal_id?: number; status: string | null; status_label?: string; label?: string; progress: number;
  step_label: string; eta_seconds: number; is_terminal?: boolean; used_provider?: string;
}

export const isGenerating = (s?: GenerationStatus) => !!s?.status && !s.is_terminal;

export function useGenerationStatus(id: number) {
  return useQuery({
    queryKey: [...projetKey(id), "ai-generation"],
    queryFn: ({ signal }) => api<GenerationStatus>(`projects/${id}/detail-tabs/ai-generation/`, { signal }),
    refetchInterval: (q) => (isGenerating(q.state.data) ? 3000 : false),
  });
}

export function useTriggerGeneration(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ proposal_id: number; status: string }>(`projects/${id}/detail-tabs/ai-generation/`, { method: "POST", body: actionBody() }),
    onSettled: () => qc.invalidateQueries({ queryKey: [...projetKey(id), "ai-generation"] }),
  });
}

// ─── IA financière (vues views_financial_ai) ───
export interface BudgetForecast {
  project_id: number; horizon_end: string; base_cost: Money; optimistic_cost: Money; pessimistic_cost: Money;
  base_revenue: Money; expected_margin: Money; expected_margin_percent: Money; overrun_risk_percent: number;
  confidence: string; drivers: string[]; ai_summary: string; ai_recommendations: string[]; used_provider: string;
}

export interface RiskAnalysis {
  project_id: number; ai_risk_label: string; risk_score: number;
  signals: { code: string; severity: string; title: string; description: string; score: number }[];
}

export function useAIForecast(id: number) {
  return useMutation({
    mutationFn: () => api<BudgetForecast>(`projects/${id}/detail-tabs/ai-forecast/`, { method: "POST", body: actionBody() }),
  });
}

export function useAIRiskAnalysis(id: number) {
  const invalidate = useInvalidateProject(id);
  return useMutation({
    mutationFn: () => api<RiskAnalysis>(`projects/${id}/detail-tabs/ai-risk-analysis/`, { method: "POST", body: actionBody() }),
    onSuccess: invalidate,
  });
}

/** Actions Django existantes (budget) : `/api/v1/actions/<nom>/<projet>/`. */
export function useProjectBudgetAction(id: number) {
  const invalidate = useInvalidateProject(id);
  return useMutation({
    mutationFn: (name: "project-generate-estimates" | "project-recalculate-budget" | "project-refresh-financials") =>
      api<{ messages?: string[] }>(`actions/${name}/${id}/`, { method: "POST", body: actionBody() }),
    onSuccess: invalidate,
  });
}

/**
 * Suppression via le pont générique (`resources/<nom>/<id>/delete/`, vue DeleteView Django).
 * `workspaceId` : workspace du projet (`?workspace=`, validé par Django) — la fiche peut afficher
 * un projet hors du workspace courant, que la vue Django filtrerait sinon (404).
 */
export function useResourceDelete(projectId: number, workspaceId?: number) {
  const invalidate = useInvalidateProject(projectId);
  return useMutation({
    mutationFn: ({ resource, id }: { resource: string; id: number }) =>
      api<{ messages?: string[] }>(`resources/${resource}/${id}/delete/`, { method: "POST", body: actionBody(), params: { workspace: workspaceId } }),
    onSuccess: invalidate,
  });
}

/** Modification du projet (formulaire Django) dans le workspace du projet (`?workspace=`). */
export const projectEditPath = (projectId: number, workspaceId?: number) =>
  workspaceId ? `/projects/${projectId}/edit?workspace=${workspaceId}` : `/projects/${projectId}/edit`;
