/**
 * Chantier « ai » — structuration automatique des projets (Genesis, propositions IA,
 * import documentaire, copilote). Toutes les règles restent côté Django
 * (`project/api/views_ai.py` exécute les vues et services existants).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FormFieldSchema } from "@/components/forms/schema";
import { api, actionBody } from "@/services/api";

export interface AIStatus { available: boolean; provider: string }
export interface Ref { id: number; name: string }
export interface Choice { value: string; label: string }

export interface ProposalRow {
  id: number;
  status: string;
  status_label: string;
  project: Ref;
  items_count: number;
  used_provider: string;
  triggered_by: string;
  created_at: string;
  running: boolean;
}

export interface ProposalItem {
  id: number;
  kind: string;
  kind_label: string;
  item_status: string;
  item_status_label: string;
  local_ref: string;
  title: string;
  description: string;
  order_index: number;
  priority: string;
  complexity: string;
  estimate_hours: number;
  recommended_profile: string;
  recommended_assignee: { id: number; name: string } | null;
  sprint_ref: string;
  milestone_ref: string;
  depends_on_refs: string[];
  acceptance_criteria: string[];
  start_date: string | null;
  end_date: string | null;
  velocity_target: number;
  edited_by: string;
  edited_at: string | null;
  applied: { model: string; id: number; link: string | null } | null;
}

export interface ProposalLog { id: number; action: string; action_label: string; actor: string; message: string; created_at: string }

export interface ProposalDetail {
  id: number;
  status: string;
  status_label: string;
  project: Ref;
  summary: string;
  risks_summary: string;
  recommendations: string[];
  used_provider: string;
  used_model: string;
  tokens_used: number;
  error_message: string;
  triggered_by: string;
  validated_by: string;
  validated_at: string | null;
  applied_at: string | null;
  rejected_at: string | null;
  created_at: string;
  updated_at: string;
  running: boolean;
  /** Droits de l'utilisateur (RBAC côté Django) : valider, rejeter, modifier, appliquer. */
  can_edit: boolean;
  editable: boolean;
  can_validate_all: boolean;
  can_apply: boolean;
  can_reject: boolean;
  /** Droits de génération IA sur le projet (régénérer). */
  can_regenerate: boolean;
  counts: { total: number; validated: number; by_kind: Record<string, number>; applied_by_kind: Record<string, number> };
  coherence: {
    total_hours: number;
    unassigned_tasks: number;
    broken_dependencies: { task: string; missing: string }[];
    load_rows: { user_id: number; label: string; hours: number }[];
  };
  kinds: Choice[];
  items: ProposalItem[];
  logs: ProposalLog[];
}

export interface GenerationStatus {
  proposal_id?: number;
  status: string | null;
  status_label?: string;
  progress: number;
  step_label: string;
  eta_seconds: number;
  is_terminal?: boolean;
  used_provider?: string;
}

export interface GenesisResult {
  project: Ref;
  proposal: { id: number; status: string; status_label: string };
  applied: boolean;
  used_provider: string;
  counts: Record<string, unknown>;
  messages: string[];
}

export interface ImportRow {
  id: number;
  file_name: string;
  file_ext: string;
  file_url: string;
  status: string;
  status_label: string;
  project: Ref | null;
  workspace: string;
  uploaded_by: string;
  created_at: string;
  has_error: boolean;
  /** Message d'erreur sinon début du texte extrait (comme la liste historique). */
  excerpt: string;
  /** « tracking_sheet » : classeur de suivi, traité par l'assistant d'import du suivi. */
  kind?: string;
}

export interface ImportList {
  results: ImportRow[];
  count: number;
  page: number;
  num_pages: number;
  stats: Partial<Record<"total" | "uploaded" | "processing" | "completed" | "failed", number>>;
  status_choices: Choice[];
  projects: Ref[];
  workspace: Ref | null;
  workspaces: Ref[];
}

export interface ImportDetail extends ImportRow {
  extracted_text: string;
  ai_payload: Record<string, unknown> | null;
  error_message: string;
  updated_at: string;
  related: ImportRow[];
  proposal: { id: number; status: string; status_label: string; project_id: number } | null;
  analysis_running: boolean;
  /** Analyse possible : aucune en cours et droits suffisants (403 côté Django sinon). */
  can_analyze: boolean;
  ai: AIStatus;
}

export interface AnalyzeResult {
  import_id: number;
  project: Ref;
  proposal: { id: number; status: string; status_label: string };
  applied: boolean;
  used_provider: string;
  counts: Record<string, unknown>;
}

export interface CopilotAction { tool: string; args?: Record<string, unknown>; result?: Record<string, unknown>; status?: string; log_id: number; link?: string | null }
export interface CopilotReply {
  type: "reply" | "tool_result" | "tool_error" | "error";
  message: string;
  tool_name?: string;
  actions_executed: CopilotAction[];
}

export interface CopilotLog {
  id: number;
  created_at: string;
  tool_name: string;
  user: string;
  status: string;
  status_label: string;
  duration_ms: number;
  error_message: string;
  affected: { type: string; id: number | null; link: string | null } | null;
}

export interface CopilotLogs {
  project: Ref & { methodology: string; methodology_label: string };
  ai: AIStatus;
  logs: CopilotLog[];
}

export const AI_KEY = ["ai"] as const;
const PROPOSALS = [...AI_KEY, "proposals"] as const;

export const useAIStatus = () =>
  useQuery({ queryKey: [...AI_KEY, "status"], queryFn: ({ signal }) => api<AIStatus>("ai/status/", { signal }), staleTime: 60_000 });

export const useGenesisSchema = () =>
  useQuery({
    queryKey: [...AI_KEY, "genesis"],
    queryFn: ({ signal }) => api<{ fields: FormFieldSchema[]; ai: AIStatus; can_create: boolean }>("ai/genesis/", { signal }),
    staleTime: 0,
  });

export function useGenesis() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api<GenesisResult>("ai/genesis/", { method: "POST", body }),
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: ["projects"] }), qc.invalidateQueries({ queryKey: PROPOSALS })]),
  });
}

export const useProposalList = (params: Record<string, string>) =>
  useQuery({
    queryKey: [...PROPOSALS, "list", params],
    queryFn: ({ signal }) => api<{ results: ProposalRow[]; count: number; page: number; num_pages: number; status_choices: Choice[] }>(
      "ai-proposals/", { signal, params }),
    placeholderData: keepPreviousData,
  });

export const useProjectProposals = (projectId: number) =>
  useQuery({
    queryKey: [...PROPOSALS, "project", projectId],
    queryFn: ({ signal }) => api<{ project: Ref & { methodology_label: string }; proposals: ProposalRow[]; ai: AIStatus; can_trigger: boolean }>(
      `projects/${projectId}/ai-proposals/`, { signal }),
  });

/** Aperçu : rafraîchi toutes les 3 s tant que la génération est en cours. */
export const useProposal = (id: number) =>
  useQuery({
    queryKey: [...PROPOSALS, id],
    queryFn: ({ signal }) => api<ProposalDetail>(`ai-proposals/${id}/`, { signal }),
    refetchInterval: (q) => (q.state.data?.running ? 3000 : false),
  });

export const useGenerationStatus = (projectId: number | undefined, enabled: boolean) =>
  useQuery({
    queryKey: [...PROPOSALS, "status", projectId],
    queryFn: ({ signal }) => api<GenerationStatus>(`projects/${projectId}/ai-proposals/status/`, { signal }),
    enabled: enabled && !!projectId,
    refetchInterval: enabled ? 3000 : false,
  });

export function useTriggerProposal(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ success: boolean; proposal_id: number; status: string }>(
      `projects/${projectId}/ai-proposals/trigger/`, { method: "POST", body: actionBody() }),
    onSuccess: () => qc.invalidateQueries({ queryKey: PROPOSALS }),
  });
}

export type ProposalAction = "validate-all" | "apply" | "reject" | "regenerate";

export function useProposalAction(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ action, data }: { action: ProposalAction; data?: Record<string, string> }) =>
      api<{ messages?: string[]; id?: number; project_id?: number; applied_by_kind?: Record<string, number> }>(
        `ai-proposals/${id}/${action}/`, { method: "POST", body: actionBody(data) }),
    onSuccess: () => Promise.all([
      qc.invalidateQueries({ queryKey: PROPOSALS }),
      qc.invalidateQueries({ queryKey: ["projects"] }),
      qc.invalidateQueries({ queryKey: ["tasks"] }),
    ]),
  });
}

export function useItemAction(proposalId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, action }: { itemId: number; action: "validate" | "reject" }) =>
      api<{ messages?: string[]; item: ProposalItem; proposal_status: string }>(
        `ai-proposals/${proposalId}/items/${itemId}/${action}/`, { method: "POST", body: actionBody() }),
    onSuccess: () => qc.invalidateQueries({ queryKey: PROPOSALS }),
  });
}

export const useItemForm = (proposalId: number, itemId: number) =>
  useQuery({
    queryKey: [...PROPOSALS, proposalId, "item-form", itemId],
    queryFn: ({ signal }) => api<{ fields: FormFieldSchema[]; item: ProposalItem }>(
      `ai-proposals/${proposalId}/items/${itemId}/form/`, { signal }),
    staleTime: 0,
  });

const IMPORTS = [...AI_KEY, "imports"] as const;

export const useImports = (params: Record<string, string>) =>
  useQuery({
    queryKey: [...IMPORTS, "list", params],
    queryFn: ({ signal }) => api<ImportList>("imports/", { signal, params }),
    placeholderData: keepPreviousData,
  });

export const useImport = (id: number) =>
  useQuery({ queryKey: [...IMPORTS, id], queryFn: ({ signal }) => api<ImportDetail>(`imports/${id}/`, { signal }) });

export function useAnalyzeImport(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name?: string; use_ai: boolean; auto_apply: boolean }) =>
      api<AnalyzeResult>(`imports/${id}/analyze/`, { method: "POST", body }),
    onSettled: () => Promise.all([
      qc.invalidateQueries({ queryKey: IMPORTS }),
      qc.invalidateQueries({ queryKey: PROPOSALS }),
      qc.invalidateQueries({ queryKey: ["projects"] }),
    ]),
  });
}

export const useCopilotLogs = (projectId: number) =>
  useQuery({
    queryKey: [...AI_KEY, "copilot", projectId, "logs"],
    queryFn: ({ signal }) => api<CopilotLogs>(`projects/${projectId}/copilot/logs/`, { signal }),
  });

export function useCopilotChat(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { message: string; history: { role: string; content: string }[] }) =>
      api<CopilotReply>(`projects/${projectId}/copilot/`, { method: "POST", body }),
    onSuccess: (reply) => {
      if (reply.actions_executed?.length) {
        void qc.invalidateQueries({ queryKey: [...AI_KEY, "copilot", projectId] });
        void qc.invalidateQueries({ queryKey: ["projects"] });
        void qc.invalidateQueries({ queryKey: ["tasks"] });
      }
    },
  });
}
