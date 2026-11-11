/**
 * Pilotage — « Suivi Pôle Développement ».
 * Vue consolidée des projets, tâches, risques, décisions et du journal existants : toutes
 * les règles (périmètre RBAC, filtres, calculs) sont appliquées par Django
 * (`project/api/views_tracking.py`). Ce module ne fait que lire et transmettre.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/services/api";

export interface Ref { id: number; name: string }
export interface Choice { value: string; label: string }
export type StatusKey = "en_cours" | "suspendu" | "realise" | "annule";

export interface TrackingAlert {
  id: number;
  type: "risk" | "decision";
  kind: string;
  kind_label: string;
  severity: string | null;
  severity_label: string;
  text: string;
}

export interface TrackingRow {
  id: string;
  kind: "project" | "task";
  pk: number;
  workspace: Ref;
  project: Ref;
  title: string;
  companies: string[];
  owners: { name: string; user_id: number | null }[];
  contacts: string[];
  progress: number;
  status: string;
  status_label: string;
  status_key: StatusKey;
  sheet_status: string;
  start: string | null;
  end: string | null;
  late: boolean;
  days_late: number;
  due_soon: boolean;
  stale: boolean;
  done: { text: string; date: string | null; source: string; id?: number }[];
  done_count: number;
  next: { id: number; text: string; due: string | null; status: string; late: boolean }[];
  next_count: number;
  alerts: TrackingAlert[];
  blocked: boolean;
  pending_decisions: number;
  updated_at: string | null;
  url: string;
}

export interface TrackingKpis {
  projects_total: number;
  projects_active: number;
  projects_done: number;
  projects_suspended: number;
  projects_late: number;
  due_soon: number;
  progress_avg: number;
  projects_blocked: number;
  pending_decisions: number;
  tasks_open: number;
  tasks_late: number;
  activities_total: number;
}

export interface ChartPoint { key?: string; label: string; value: number }

export interface TrackingBoard {
  rows: TrackingRow[];
  count: number;
  total: number;
  kpis: TrackingKpis;
  charts: {
    by_company: ChartPoint[];
    by_status: ChartPoint[];
    progress: ChartPoint[];
    deadlines: ChartPoint[];
    workload: { label: string; projects: number; tasks: number }[];
    alerts: ChartPoint[];
  };
  options: {
    companies: string[];
    owners: Choice[];
    projects: Choice[];
    workspaces: Choice[];
    statuses: Choice[];
    alerts: Choice[];
  };
  /** Filtres actifs, formulés par Django (repris tels quels dans les exports). */
  filters: string[];
  scope: { label: string; restricted: boolean };
  can_import: boolean;
  generated_at: string;
}

/** Filtres de l'écran : mêmes noms que les paramètres de l'API et des exports. */
export const FILTER_KEYS = [
  "q", "section", "workspace", "company", "project", "owner", "status", "from", "to", "late", "alert", "progress_min", "progress_max",
] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
export type TrackingFilters = Partial<Record<FilterKey, string>>;

export function filtersFrom(search: URLSearchParams): TrackingFilters {
  const filters: TrackingFilters = {};
  FILTER_KEYS.forEach((key) => {
    const value = search.get(key);
    if (value) filters[key] = value;
  });
  return filters;
}

export type ExportVariant = "direction" | "weekly" | "monthly";

/** Lien d'export : les filtres actifs sont transmis, le périmètre reste calculé par Django. */
export function trackingExportUrl(filters: TrackingFilters = {}, fmt: "xlsx" | "pdf" = "xlsx", variant?: ExportVariant): string {
  const query = new URLSearchParams();
  query.set("fmt", fmt);
  if (variant) query.set("variant", variant);
  FILTER_KEYS.forEach((key) => {
    const value = filters[key];
    if (value) query.set(key, value);
  });
  return `/api/v1/tracking/export/?${query.toString()}`;
}

const KEY = ["tracking"] as const;

export function useTrackingBoard(filters: TrackingFilters) {
  return useQuery({
    queryKey: [...KEY, "board", filters],
    queryFn: ({ signal }) => api<TrackingBoard>("tracking/board/", { signal, params: filters }),
    placeholderData: keepPreviousData,
  });
}

export interface TrackingBrief {
  generated_at: string;
  facts: { kind: string; text: string; rows: string[] }[];
  text: string;
  source: "rules" | "ai";
}

export function useTrackingBrief(filters: TrackingFilters, enabled = true) {
  return useQuery({
    queryKey: [...KEY, "brief", filters],
    queryFn: ({ signal }) => api<TrackingBrief>("tracking/brief/", { signal, params: filters }),
    enabled,
  });
}

/** Reformulation par l'IA DevFlow des constats déjà calculés (aucune donnée inventée). */
export function useAiBrief(filters: TrackingFilters) {
  return useMutation({
    mutationFn: () => api<TrackingBrief>("tracking/brief/", { method: "POST", params: filters, body: {} }),
  });
}

export interface ProjectTracking {
  row: TrackingRow | null;
  activities: TrackingRow[];
  recent: { id: number; title: string; actor: string; type: string; created_at: string }[];
}

export function useProjectTracking(projectId: number) {
  return useQuery({
    queryKey: [...KEY, "project", projectId],
    queryFn: ({ signal }) => api<ProjectTracking>(`tracking/projects/${projectId}/`, { signal }),
    retry: false,
  });
}

// ---------------------------------------------------------------------------
// Assistant d'import du classeur de suivi
// ---------------------------------------------------------------------------
export type ImportState = "uploaded" | "analyzed" | "applied" | "rolled_back";
export type RowAction = "skip" | "create" | "link" | "update";

export interface ImportStats {
  projects: number;
  tasks: number;
  actions_done: number;
  actions_next: number;
  alerts: number;
  companies: number;
  people: number;
  unresolved_people: number;
  ambiguities: number;
  warnings: number;
}

export interface ImportSummary {
  id: number;
  file_name: string;
  workspace: Ref;
  uploaded_by: string;
  created_at: string;
  state: ImportState;
  stats: Partial<ImportStats>;
  applied_at: string | null;
  applied_by: Ref | null;
  rolled_back_at: string | null;
  rolled_back_by: Ref | null;
}

export interface ImportWarning { row: string; line: number; field: string; code: string; message: string }

export interface AnalysisItem {
  id: string;
  text: string;
  start?: string | null;
  due?: string | null;
  match: { id: number } | null;
  default: { action: "create" | "link" | "skip"; target_id: number | null };
}

export interface AnalysisAlert {
  id: string;
  text: string;
  kind: string;
  severity: string;
  match: { id: number } | null;
  default: { action: "create" | "link" | "skip"; target_id: number | null; kind: string; severity: string };
}

export interface AnalysisRow {
  id: string;
  section: "projects" | "tasks";
  row: number;
  title: string;
  companies: string[];
  owners: string[];
  contacts: string[];
  done: { id: string; text: string }[];
  next: AnalysisItem[];
  alerts: AnalysisAlert[];
  start: string | null;
  end: string | null;
  progress: number | null;
  progress_raw: string;
  status_raw: string;
  status_key: StatusKey | null;
  raw: Record<string, string>;
  warnings: ImportWarning[];
  match: { id: number; name: string; archived: boolean } | null;
  default: { action: RowAction; target_id: number | null; project_id?: number | null };
}

export interface Ambiguity {
  id: string;
  row: string;
  line: number;
  field: string;
  message: string;
  options: { value: string | number | null; label: string }[];
  default: string | number | null;
  suggestion?: string | number | null;
}

export interface ImportAnalysis {
  analyzed_at: string;
  sections: { kind: "projects" | "tasks"; sheet: string; title: string; header_row: number; first_row: number | null; last_row: number | null; rows: number }[];
  rows: AnalysisRow[];
  companies: { key: string; name: string; rows: string[]; ambiguous: boolean; match: { id: number; name: string; kind: string } | null; default: { action: "link" | "create"; label_id: number | null } }[];
  people: { key: string; name: string; roles: string[]; rows: string[]; match: Ref | null; candidates: Ref[]; unresolved: boolean; default: { user_id: number | null } }[];
  statuses: { key: string; raw: string; known: StatusKey | null; rows: number; default: { project: string | null; task: string | null } }[];
  container: { default: { mode: "existing" | "create"; project_id: number | null; name: string } };
  ambiguities: Ambiguity[];
  warnings: ImportWarning[];
  stats: ImportStats;
  unresolved_members: string[];
}

/** Décisions de l'utilisateur : seules les différences avec les propositions sont envoyées. */
export interface ImportDecisions {
  people?: Record<string, { user_id: number | null }>;
  companies?: Record<string, { action: "link" | "create"; label_id: number | null }>;
  statuses?: Record<string, { project?: string | null; task?: string | null }>;
  rows?: Record<string, { action: RowAction; target_id?: number | null; project_id?: number | null }>;
  items?: Record<string, { action: "create" | "link" | "skip"; target_id?: number | null }>;
  alerts?: Record<string, { action?: "create" | "link" | "skip"; kind?: string; severity?: string }>;
  ambiguities?: Record<string, string | number | null>;
  container?: { mode: "existing" | "create"; project_id?: number | null; name?: string };
  done_as_tasks?: boolean;
}

export interface ImportReport {
  counts: Record<string, Record<string, number>>;
  unresolved_members: string[];
  ambiguities_kept: string[];
  warnings: number;
  records: number;
}

export interface ImportDetail extends ImportSummary {
  analysis: ImportAnalysis | null;
  decisions: ImportDecisions | null;
  report: ImportReport | null;
  rollback: Partial<Record<"archived" | "removed" | "restored", number>> | null;
  options: {
    users: Ref[];
    projects: (Ref & { container: boolean })[];
    labels: (Ref & { kind: string })[];
    project_statuses: Choice[];
    task_statuses: Choice[];
    alert_kinds: Choice[];
    severities: Choice[];
  };
}

export interface ImportRecord {
  id: number;
  section: string;
  row: number;
  field: string;
  index: number;
  text: string;
  action: string;
  action_label: string;
  target_model: string;
  target_id: number | null;
  rolled_back: boolean;
}

const IMPORTS = [...KEY, "imports"] as const;

export function useTrackingImports(enabled = true) {
  return useQuery({
    queryKey: [...IMPORTS, "list"],
    queryFn: ({ signal }) => api<{ results: ImportSummary[]; workspaces: Ref[] }>("tracking/imports/", { signal }),
    enabled,
    retry: false,
  });
}

export function useTrackingImport(id: number) {
  return useQuery({
    queryKey: [...IMPORTS, id],
    queryFn: ({ signal }) => api<ImportDetail>(`tracking/imports/${id}/`, { signal }),
    retry: false,
  });
}

export function useUploadTracking() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ workspace, file }: { workspace: number; file: File }) => {
      const body = new FormData();
      body.set("workspace", String(workspace));
      body.set("file", file);
      return api<ImportDetail>("tracking/imports/", { method: "POST", body });
    },
    onSuccess: (detail) => {
      client.setQueryData([...IMPORTS, detail.id], detail);
      void client.invalidateQueries({ queryKey: [...IMPORTS, "list"] });
    },
  });
}

/** `analyze` relance l'analyse, `apply` applique les décisions, `rollback` annule logiquement. */
export function useImportAction(id: number, action: "analyze" | "apply" | "rollback") {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (decisions?: ImportDecisions) =>
      api<ImportDetail>(`tracking/imports/${id}/${action}/`, { method: "POST", body: action === "apply" ? { decisions: decisions ?? {} } : {} }),
    onSuccess: (detail) => {
      client.setQueryData([...IMPORTS, id], detail);
      // Les données du suivi (et le journal d'audit) ont changé.
      void client.invalidateQueries({
        queryKey: KEY,
        predicate: (q) => !(q.queryKey[1] === "imports" && q.queryKey[2] === id && q.queryKey.length === 3),
      });
    },
  });
}

export function useImportRecords(id: number, page: number, enabled: boolean) {
  return useQuery({
    queryKey: [...IMPORTS, id, "records", page],
    queryFn: ({ signal }) =>
      api<{ count: number; page: number; num_pages: number; results: ImportRecord[] }>(`tracking/imports/${id}/records/`, { signal, params: { page } }),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useImportTaskSearch(id: number, q: string) {
  return useQuery({
    queryKey: [...IMPORTS, id, "tasks", q],
    queryFn: ({ signal }) =>
      api<{ results: { id: number; title: string; project: string }[] }>(`tracking/imports/${id}/tasks/`, { signal, params: { q } }),
    enabled: q.trim().length >= 2,
  });
}
