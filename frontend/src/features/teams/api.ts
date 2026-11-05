import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, actionBody } from "@/services/api";
import type { Paginated } from "@/types/api";

export interface Team {
  id: number; name: string; team_type: string; team_type_label: string; description: string; color: string;
  is_active: boolean; is_archived: boolean; velocity_target: number; velocity_current: number;
  lead_name: string; members_count: number | null; projects_count: number | null;
}
export interface TeamOverview {
  members: { id: number; user_id: number; name: string; role_label: string; status_label: string; job_title: string; current_load_percent: number }[];
  projects: { id: number; name: string; status_label: string; progress_percent: number }[];
}
export interface Member {
  id: number;
  user: { id: number; name: string; email: string; is_active: boolean };
  team: { id: number; name: string } | null;
  role: string; role_label: string; status: string; status_label: string; job_title: string;
  current_load_percent: number; joined_at: string | null; manager: string; capacity_hours_per_week: number | null; is_owner: boolean;
}
type Option = { value: string; label: string };
export interface MembersPage extends Paginated<Member> {
  permissions: { can_manage_passwords: boolean; can_onboard: boolean };
  filters: { teams: Option[]; roles: Option[]; statuses: Option[] };
}

const KEY = ["teams"] as const;

export const useTeams = (search: string) =>
  useQuery({
    queryKey: [...KEY, "list", search],
    queryFn: ({ signal }) => api<Paginated<Team>>("teams/", { signal, params: { search, is_archived: "false", page_size: 200 } }),
    placeholderData: keepPreviousData,
  });
export const useTeam = (id: number) => useQuery({ queryKey: [...KEY, id], queryFn: ({ signal }) => api<Team>(`teams/${id}/`, { signal }) });
export const useTeamOverview = (id: number) =>
  useQuery({ queryKey: [...KEY, id, "overview"], queryFn: ({ signal }) => api<TeamOverview>(`teams/${id}/overview/`, { signal }) });
export const useMembers = (params: Record<string, string | number>) =>
  useQuery({
    queryKey: [...KEY, "members", params],
    queryFn: ({ signal }) => api<MembersPage>("team-members/", { signal, params }),
    placeholderData: keepPreviousData,
  });

/** Actions servies par les vues Django (archivage, suppression, réinitialisation de mot de passe). */
export function useTeamAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ action, id, data }: { action: string; id: number; data?: Record<string, string> }) => {
      const fd = actionBody(data ?? {});
      return api<{ messages?: string[] }>(`actions/${action}/${id}/`, { method: "POST", body: fd });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
