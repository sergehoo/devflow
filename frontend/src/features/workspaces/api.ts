import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { meQueryKey } from "@/features/auth/api";
import { api } from "@/services/api";
import type { Paginated } from "@/types/api";

export interface Workspace {
  id: number;
  name: string;
  slug: string;
  is_archived: boolean;
  created_at: string;
  description: string;
  logo: string | null;
  owner: number;
  owner_name: string;
  is_active: boolean;
  timezone: string;
  quarter_label: string;
  legal_name: string;
  tagline: string;
  legal_rccm: string;
  legal_cc: string;
  legal_tax_id: string;
  address_line1: string;
  address_line2: string;
  postal_code: string;
  city: string;
  country: string;
  phone: string;
  website: string;
  email: string;
  bank_details: string;
  invoice_footer_text: string;
  accent_color: string;
  teams_count: number | null;
  projects_count: number | null;
  memberships_count: number | null;
  can_manage: boolean;
  can_delete: boolean;
}

export interface WorkspaceOverview {
  teams: { id: number; name: string; team_type: string }[];
  projects: { id: number; name: string; status_label: string; progress_percent: number; team: string }[];
  members: { id: number; name: string; email: string; job_title: string }[];
}

const KEY = ["workspaces"] as const;

export const useWorkspaces = (params: { search: string; includeArchived: boolean; page: number }) =>
  useQuery({
    queryKey: [...KEY, "list", params],
    queryFn: ({ signal }) =>
      api<Paginated<Workspace>>("workspaces/", {
        signal,
        params: { search: params.search, include_archived: params.includeArchived ? 1 : undefined, page: params.page },
      }),
    placeholderData: keepPreviousData,
  });

export const useWorkspace = (id: number) =>
  useQuery({ queryKey: [...KEY, id], queryFn: ({ signal }) => api<Workspace>(`workspaces/${id}/`, { signal }), enabled: id > 0 });

export const useWorkspaceOverview = (id: number) =>
  useQuery({ queryKey: [...KEY, id, "overview"], queryFn: ({ signal }) => api<WorkspaceOverview>(`workspaces/${id}/overview/`, { signal }) });

function useInvalidate() {
  const qc = useQueryClient();
  return () => Promise.all([qc.invalidateQueries({ queryKey: KEY }), qc.invalidateQueries({ queryKey: meQueryKey })]);
}

export function useSaveWorkspace(id?: number) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: FormData | Partial<Workspace>) =>
      api<Workspace>(id ? `workspaces/${id}/` : "workspaces/", { method: id ? "PATCH" : "POST", body }),
    onSuccess: invalidate,
  });
}

export function useWorkspaceAction() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: "archive" | "delete" }) =>
      action === "archive"
        ? api(`workspaces/${id}/archive/`, { method: "POST" })
        : api(`workspaces/${id}/`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}
