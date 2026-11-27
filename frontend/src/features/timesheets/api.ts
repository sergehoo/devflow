import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, actionBody } from "@/services/api";
import type { Paginated } from "@/types/api";
import { invalidateTaskViews } from "@/features/tasks/sync";

export interface WeekTask {
  id: number;
  title: string;
  status: string;
  status_label: string;
  progress_percent: number;
  start_date: string | null;
  due_date: string | null;
  is_late: boolean;
  /** Assigné(e) : mise à jour rapide possible (statut, avancement, temps, commentaire). */
  can_update: boolean;
}

export interface WeekRow {
  kind: "task" | "activity";
  row_id: string;
  label: string;
  /** La tâche du projet elle-même (lue en direct sur `dm.Task`, comme dans /tasks et le Suivi). */
  task: WeekTask | null;
  project: { id: number; name: string } | null;
  description: string;
  cells: { date: string; hours: number }[];
  total: number;
}

export interface WeekLog { action: string; action_label: string; actor: string; comment: string; created_at: string }

export interface Week {
  user: { id: number; name: string };
  is_self: boolean;
  monday: string;
  iso_week: number;
  year: number;
  days: { date: string; label: string }[];
  today: string;
  prev_week: string;
  next_week: string;
  rows: WeekRow[];
  day_totals: Record<string, number>;
  week_total: number;
  week_status: string;
  week_status_label: string;
  is_locked: boolean;
  can_submit: boolean;
  can_review: boolean;
  summary: {
    status: string; status_label: string; total_hours: number; planned_hours: number; capacity: number; expected: number;
    missing_hours: number; completion_percent: number; last_log: WeekLog | null;
  } | null;
  history: WeekLog[];
  projects: { id: number; name: string }[];
}

export interface Entry {
  id: number;
  entry_date: string;
  user: { id: number; name: string };
  project: { id: number; name: string } | null;
  task: { id: number; title: string } | null;
  hours: number;
  planned_hours: number | null;
  description: string;
  is_billable: boolean;
  approval_status: string;
  approval_status_label: string;
  can_edit: boolean;
}

export interface Breakdown { id: number | null; name: string; hours: number; billable_hours: number }
export interface EntriesPage extends Paginated<Entry> {
  collaborators: { id: number; name: string }[];
  projects: { id: number; name: string }[];
  totals: { hours: number; billable_hours: number; non_billable_hours: number; by_user: Breakdown[]; by_project: Breakdown[] };
}

export interface WeekGroup {
  user: { id: number; name: string };
  monday: string; sunday: string; iso_week: number; year: number;
  total_hours: number; entry_count: number; status: string; status_label: string; can_review: boolean; is_mine: boolean;
}

export interface WeeksPage extends Paginated<WeekGroup> { collaborators?: { id: number; name: string }[] }

export const TS_KEY = ["timesheet"] as const;

type Params = Record<string, string | number | undefined | null>;
const query = (params: Params) => {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") q.set(k, String(v)); });
  return q.toString();
};

/** Export Excel de l'historique : mêmes filtres et même périmètre que `timesheet/entries/` (contrôle Django). */
export const timesheetExportUrl = (params: Params) => {
  const q = query({ ...params, page: undefined, page_size: undefined });
  return `/api/v1/timesheet/export/${q ? `?${q}` : ""}`;
};

/** Feuille de temps d'une semaine en Excel (soi ou un collaborateur visible ; 404 sinon). */
export const weekExportUrl = (date: string, user?: number | string | null) => `/api/v1/timesheet/week/export/?${query({ date, user })}`;

/** Ouvre la semaine d'un collaborateur (ou la sienne : Django la rend modifiable si c'est l'utilisateur courant). */
export const weekPath = (date: string, user?: number | null) => `/timesheets?${query({ user, date })}`;

export const useWeek = (date: string, user?: string | null) =>
  useQuery({
    queryKey: [...TS_KEY, "week", date, user ?? "me"],
    queryFn: ({ signal }) => api<Week>("timesheet/week/", { signal, params: { date, user } }),
    placeholderData: keepPreviousData,
  });

export const useEntries = (params: Record<string, string | number | undefined>, enabled = true) =>
  useQuery({
    queryKey: [...TS_KEY, "entries", params],
    queryFn: ({ signal }) => api<EntriesPage>("timesheet/entries/", { signal, params }),
    placeholderData: keepPreviousData,
    enabled,
  });

export const useWeeks = (params: Record<string, string | number | undefined>) =>
  useQuery({
    queryKey: [...TS_KEY, "weeks", params],
    queryFn: ({ signal }) => api<WeeksPage>("timesheet/weeks/", { signal, params }),
    placeholderData: keepPreviousData,
  });

function postAction(name: string, data: Record<string, string | number>, id?: number) {
  const fd = actionBody(data);
  return api<{ messages?: string[]; day_total?: number; week_total?: number }>(id ? `actions/${name}/${id}/` : `actions/${name}/`, { method: "POST", body: fd });
}

/** Une saisie, une tâche créée ou une activité convertie change aussi /tasks, la fiche projet et le Suivi. */
function useTsMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSettled: () => invalidateTaskViews(qc) });
}

/** Saisie d'une cellule — vue Django TimesheetCalendarSaveView (0 h supprime la ligne du jour). */
export const useSaveCell = () =>
  useTsMutation((v: { task_id?: number; project_id?: number; description?: string; date: string; hours: string }) =>
    postAction("timesheet-cell", Object.fromEntries(Object.entries(v).filter(([, x]) => x !== undefined)) as Record<string, string | number>));

/** submit / approve / reject / reopen — vue Django TimesheetWeekValidateView (service timesheet_workflow). */
export const useWeekAction = () =>
  useTsMutation((v: { user: number; monday: string; action: "submit" | "approve" | "reject" | "reopen"; comment?: string }) =>
    postAction("timesheet-week", { user: v.user, monday: v.monday, action: v.action, comment: v.comment ?? "" }));

export const useDeleteEntry = () => useTsMutation((id: number) => postAction("timesheet-entry-delete", {}, id));

/** Nouvelle tâche du projet créée depuis le timesheet (assignée à soi), avec les heures éventuelles du jour. */
export const useCreateTimesheetTask = () =>
  useTsMutation((v: { project_id: number; title: string; date: string; hours?: string; due_date?: string; description?: string }) =>
    api<{ task: WeekTask; project: { id: number; name: string }; hours: number }>("timesheet/tasks/", { method: "POST", body: v }));

/** Activité libre (libellé sans tâche) → tâche du projet ; ses saisies modifiables y sont rattachées. */
export const useConvertActivity = () =>
  useTsMutation((v: { project_id: number; description: string }) =>
    api<{ task: WeekTask; linked_entries: number; created: boolean }>("timesheet/activities/convert/", { method: "POST", body: v }));
