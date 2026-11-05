import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/services/api";
import type { Paginated } from "@/types/api";

export interface Project {
  id: number;
  workspace: number;
  team: number | null;
  team_name: string;
  name: string;
  code: string;
  description: string;
  tech_stack: string;
  owner: number | null;
  owner_name: string;
  product_manager: number | null;
  product_manager_name: string;
  status: string;
  status_label: string;
  priority: string;
  priority_label: string;
  health_status: string;
  health_status_label: string;
  methodology: string;
  methodology_label: string;
  progress_percent: number;
  risk_score: number | null;
  ai_risk_label: string;
  start_date: string | null;
  target_date: string | null;
  delivered_at: string | null;
  budget: string | null;
  members_count: number;
  is_archived: boolean;
  updated_at: string;
}

export interface ProjectSummary {
  tasks_total: number;
  tasks_overdue: number;
  estimate_hours: number;
  spent_hours: number;
  tasks_by_status: { status: string; label: string; count: number }[];
  members: { id: number; user_id: number; name: string; role: string; team: string; allocation_percent: number }[];
}

export interface ProjectFilters {
  search: string;
  status: string;
  priority: string;
  health_status: string;
  team: string;
  ordering: string;
  page: number;
}

const KEY = ["projects"] as const;

export const useProjects = (f: ProjectFilters) =>
  useQuery({
    queryKey: [...KEY, "list", f],
    queryFn: ({ signal }) => api<Paginated<Project>>("projects/", { signal, params: { ...f } }),
    placeholderData: keepPreviousData,
  });

export const useProject = (id: number) =>
  useQuery({ queryKey: [...KEY, id], queryFn: ({ signal }) => api<Project>(`projects/${id}/`, { signal }) });

export const useProjectSummary = (id: number) =>
  useQuery({ queryKey: [...KEY, id, "summary"], queryFn: ({ signal }) => api<ProjectSummary>(`projects/${id}/summary/`, { signal }) });

export function useProjectAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: "archive" | "delete" }) =>
      action === "archive" ? api(`projects/${id}/archive/`, { method: "POST" }) : api(`projects/${id}/`, { method: "DELETE" }),
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: KEY }), qc.invalidateQueries({ queryKey: ["dashboard"] })]),
  });
}
