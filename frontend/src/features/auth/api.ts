import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/services/api";
import type { Me } from "@/types/auth";

export const meQueryKey = ["auth", "me"] as const;

export function useMe() {
  return useQuery({
    queryKey: meQueryKey,
    queryFn: async () => {
      try {
        return await api<Me>("auth/me/");
      } catch (error) {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) return null;
        throw error;
      }
    },
    staleTime: 5 * 60_000,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { login: string; password: string }) => {
      await api("auth/csrf/");
      return api<Me>("auth/login/", { method: "POST", body: input });
    },
    onSuccess: (me) => queryClient.setQueryData(meQueryKey, me),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api("auth/logout/", { method: "POST" }),
    onSettled: () => {
      queryClient.clear();
      queryClient.setQueryData(meQueryKey, null);
    },
  });
}

export function useSwitchWorkspace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (workspaceId: number) => api<Me>("auth/workspace/", { method: "POST", body: { workspace_id: workspaceId } }),
    onSuccess: (me) => {
      // Toutes les données dépendent du workspace : on repart d'un cache propre.
      queryClient.clear();
      queryClient.setQueryData(meQueryKey, me);
    },
  });
}
