import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, actionBody } from "@/services/api";
import type { Paginated } from "@/types/api";

export interface Task {
  id: number;
  project: number | null;
  project_name: string;
  sprint: number | null;
  sprint_name: string;
  title: string;
  description: string;
  status: string;
  status_label: string;
  priority: string;
  priority_label: string;
  assignee: number | null;
  assignee_name: string;
  estimate_hours: string | null;
  spent_hours: string | null;
  due_date: string | null;
  start_date: string | null;
  progress_percent: number;
  is_flagged: boolean;
  is_archived: boolean;
}

export interface TaskState {
  id: number;
  title: string;
  status: string;
  status_label: string;
  progress_percent: number;
  spent_hours: string;
  estimate_hours: string | null;
  assignee_id: number | null;
  assignee_name: string;
  can_update: boolean;
  statuses: { value: string; label: string }[];
}

export interface TaskOverview {
  state: TaskState;
  description: string;
  reporter: string;
  can_arbitrate: boolean;
  can_edit: boolean;
  can_delete: boolean;
  comments: { id: number; author: string; body: string; is_internal: boolean; created_at: string }[];
  attachments: { id: number; name: string; url: string | null; size: number | null; uploaded_by: string; created_at: string }[];
  assignments: { id: number; user: string; allocation_percent: number; is_active: boolean }[];
  checklists: { id: number; title: string; items: { id: number; text: string; is_checked: boolean }[] }[];
  subtasks: { id: number; title: string; status_label: string; assignee: string }[];
  dependencies: { id: number; direction: "in" | "out"; type: string; task_id: number; title: string }[];
  labels: { id: number; name: string; color: string }[];
}

export interface TaskFilters {
  search: string;
  status: string;
  priority: string;
  project: string;
  assignee: string;
  is_flagged: string;
  ordering: string;
  page: number;
}

export const TASKS_KEY = ["tasks"] as const;

export const useTasks = (f: TaskFilters, pageSize?: number) =>
  useQuery({
    queryKey: [...TASKS_KEY, "list", f, pageSize ?? 25],
    queryFn: ({ signal }) =>
      api<Paginated<Task>>("tasks/", { signal, params: { ...f, is_archived: "false", page_size: pageSize } }),
    placeholderData: keepPreviousData,
  });

export const useTask = (id: number) =>
  useQuery({ queryKey: [...TASKS_KEY, id], queryFn: ({ signal }) => api<Task>(`tasks/${id}/`, { signal }) });

export const useTaskOverview = (id: number) =>
  useQuery({ queryKey: [...TASKS_KEY, id, "overview"], queryFn: ({ signal }) => api<TaskOverview>(`tasks/${id}/overview/`, { signal }) });

export function useInvalidateTasks() {
  const qc = useQueryClient();
  return () => Promise.all([
    qc.invalidateQueries({ queryKey: TASKS_KEY }),
    qc.invalidateQueries({ queryKey: ["dashboard"] }),
    qc.invalidateQueries({ queryKey: ["projects"] }),
    qc.invalidateQueries({ queryKey: ["timesheet"] }),
  ]);
}

/** Mise à jour rapide (assigné uniquement) : statut, avancement, temps du jour, commentaire. */
export function useQuickUpdate(id: number) {
  const invalidate = useInvalidateTasks();
  return useMutation({
    mutationFn: (body: { status?: string; progress_percent?: number; spent_hours?: number | string; comment?: string }) =>
      api<TaskState>(`tasks/${id}/quick-update/`, { method: "POST", body }),
    onSuccess: invalidate,
  });
}

/** Actions servies par les vues Django existantes (`/api/v1/actions/<nom>/<id>/`). */
export function useTaskAction(id: number) {
  const invalidate = useInvalidateTasks();
  return useMutation({
    mutationFn: ({ action, data }: { action: string; data?: Record<string, string | Blob> }) => {
      const fd = actionBody(data ?? {});
      return api<{ messages?: string[] }>(`actions/${action}/${id}/`, { method: "POST", body: fd });
    },
    onSuccess: invalidate,
  });
}

export const useAssignees = (id: number, q: string, enabled: boolean) =>
  useQuery({
    queryKey: [...TASKS_KEY, id, "assignees", q],
    queryFn: ({ signal }) =>
      api<{ can_reassign: boolean; users: { id: number; name: string; email: string; job_title: string; is_project_member: boolean }[] }>(
        `tasks/${id}/assignees/`, { signal, params: { q } }),
    enabled,
  });

export function useReassign(id: number) {
  const invalidate = useInvalidateTasks();
  return useMutation({
    mutationFn: (body: { user_id: number | null; note?: string }) => api(`tasks/${id}/quick-assign/`, { method: "POST", body }),
    onSuccess: invalidate,
  });
}

export function useMoveTask() {
  const invalidate = useInvalidateTasks();
  return useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => api(`tasks/${id}/move-kanban/`, { method: "POST", body: { status } }),
    onSettled: invalidate,
  });
}
