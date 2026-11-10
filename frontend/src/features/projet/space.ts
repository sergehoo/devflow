/**
 * Espace méthodologie du projet : `/api/v1/projects/<id>/space/` (services.methodology_space —
 * mêmes sélections et indicateurs `compute_kpi` que les vues Django dédiées).
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";

export type SpaceKind = "scrum" | "kanban" | "waterfall";
export type SpaceView = "dashboard" | "workspace";

export interface Kpi {
  value: unknown; label: string; unit?: string;
  series?: { x: string; y: number }[];
  extra?: Record<string, unknown>;
}
export interface SpaceTask { id: number; title: string; status: string; status_label: string; priority_label: string; assignee: string }
export interface MethodologySpaceData {
  kind: SpaceKind | "";
  methodology: { name: string; code: string } | null;
  kpis: Record<string, Kpi>;
  dashboard: { name: string; pinned: boolean; result: Kpi }[];
  active_sprint?: { id: number; name: string; status_label: string; start_date: string | null; end_date: string | null; goal: string; tasks: SpaceTask[] } | null;
  backlog?: { id: number; title: string; status_label: string; story_points?: number; rank?: number }[];
  sprints?: { id: number; name: string; status_label: string; total_story_points?: number; completed_story_points?: number; velocity_completed?: number }[];
  columns?: { code: string; name: string; wip_limit: number | null; count: number; over_wip: boolean; tasks: SpaceTask[] }[];
  phases?: { id: number; name: string; status?: string; status_label: string; start_date: string | null; end_date: string | null; progress: number | null; owner: string; gate_required?: boolean }[];
  milestones?: { id: number; name: string; due_date: string | null }[];
}

export const SPACE_KIND_LABEL: Record<SpaceKind, string> = { scrum: "Scrum", kanban: "Kanban", waterfall: "Waterfall" };

/** Même correspondance que `methodology_space._kind` (code de méthodologie → espace). */
export function spaceKind(methodology: string): SpaceKind | "" {
  const code = methodology.toLowerCase();
  return (["scrum", "kanban", "waterfall"] as const).find((k) => code.includes(k)) ?? "";
}

/** Même clé que `MethodologySpace` (features/projects) : cache partagé, invalidé avec la fiche. */
export const useMethodologySpace = (projectId: number) =>
  useQuery({
    queryKey: ["projects", projectId, "space"],
    queryFn: ({ signal }) => api<MethodologySpaceData>(`projects/${projectId}/space/`, { signal }),
  });
