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
