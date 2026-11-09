import { useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";

export interface DashboardTask {
  id: number;
  title: string;
  status: string;
  priority: string;
  priority_label: string;
  due_date: string | null;
  estimate_hours: number | null;
  project: string;
  assignee: string;
}

export interface DashboardSummary {
  workspace: { id: number; name: string; quarter_label: string } | null;
  stats: Record<string, number>;
  finance: Record<string, number | string | null>;
  task_distribution: Record<string, number>;
  analysis_cards: { severity: string; title: string; text: string; action: string }[];
  projects: {
    id: number;
    name: string;
    status: string;
    status_label: string;
    progress_percent: number;
    risk_score: number | null;
    target_date: string | null;
    team: string;
    tech_stack: string;
  }[];
  due_soon_tasks: DashboardTask[];
  active_sprint: {
    id: number;
    name: string;
    status_label: string;
    project: string;
    team: string;
    remaining_days: number | null;
    total_story_points: number | null;
    completed_story_points: number | null;
    columns: { id: string; name: string; color: string; count: number; is_done: boolean; tasks: DashboardTask[] }[];
  } | null;
  team_load: { user: string; status_label: string; current_load_percent: number | null }[];
  top_cost_members: { user: string; job_title: string; cost_per_day: number | null; currency: string }[];
  activities: { id: number; title: string; actor: string; created_at: string | null }[];
}

export const useDashboard = () =>
  useQuery({
    queryKey: ["dashboard", "summary"],
    queryFn: ({ signal }) => api<DashboardSummary>("dashboard/summary/", { signal }),
    staleTime: 60_000,
  });

// ─── Indicateurs du tableau de bord (GET dashboard/insights/) ──────────────

export interface FocusTask extends DashboardTask {
  status_label: string;
  overdue: boolean;
}

export type ProjectHealthState = "on_track" | "at_risk" | "delayed";

export interface DashboardInsights {
  workspace: { id: number; name: string } | null;
  today: string;
  day: { planned: number; done: number; completed_today: number };
  health: { active: number; on_track: number; at_risk: number; delayed: number; healthy_percent: number | null };
  overdue_tasks: number;
  weeks: number;
  heatmap: { date: string; count: number }[];
  completed_in_period: number;
  focus: FocusTask[];
  focus_total: number;
  upcoming: { kind: "task" | "meeting" | "milestone"; id: number; title: string; subtitle: string; date: string; time: string | null; url: string }[];
  projects: {
    id: number; name: string; status_label: string; progress_percent: number; health: ProjectHealthState;
    target_date: string | null; members: string[]; members_count: number;
  }[];
}

export const INSIGHTS_KEY = ["dashboard", "insights"] as const;

export function useDashboardInsights(weeks: number) {
  return useQuery({
    queryKey: [...INSIGHTS_KEY, weeks],
    queryFn: ({ signal }) => api<DashboardInsights>("dashboard/insights/", { signal, params: { weeks } }),
    placeholderData: (prev) => prev,
  });
}
