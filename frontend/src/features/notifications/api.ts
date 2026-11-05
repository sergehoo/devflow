import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRealtimeStatus } from "@/lib/realtime";
import { api } from "@/services/api";
import type { Paginated } from "@/types/api";

export interface AppNotification {
  id: number;
  type: string;
  type_label: string;
  title: string;
  body: string;
  url: string;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
  workspace: { id: number; name: string } | null;
}
export interface Choice {
  value: string;
  label: string;
}
export interface NotificationList extends Paginated<AppNotification> {
  unread_count: number;
  read_count: number;
  total_count: number;
  types: Choice[];
}
export interface NotificationSummary {
  unread_count: number;
  recent: AppNotification[];
}
export interface NotificationPreferences {
  channel_in_app: boolean;
  channel_email: boolean;
  channel_digest: boolean;
  notify_frequency: string;
  quiet_hours_start: number;
  quiet_hours_end: number;
  priority_types: string[];
  choices: { notify_frequency: Choice[]; priority_types: Choice[] };
}

export const NOTIF_KEY = ["notifications"] as const;
export const SUMMARY_KEY = [...NOTIF_KEY, "summary"] as const;
const BASE = "me/notifications/";

/** Badge + aperçu : temps réel via /ws/me/, polling de secours si le socket est coupé. */
export function useNotificationSummary() {
  const live = useRealtimeStatus("/ws/me/") === "open";
  return useQuery({
    queryKey: SUMMARY_KEY,
    queryFn: () => api<NotificationSummary>(`${BASE}summary/`),
    refetchInterval: live ? false : 60_000,
  });
}

export function useNotifications(params: { status?: string; type?: string; q?: string; page?: number }) {
  return useQuery({
    queryKey: [...NOTIF_KEY, "list", params],
    queryFn: () => api<NotificationList>(BASE, { params }),
    placeholderData: (prev) => prev,
  });
}

function useNotifMutation<V>(fn: (v: V) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: NOTIF_KEY }) });
}

export const useMarkRead = () => useNotifMutation((id: number) => api(`${BASE}${id}/read/`, { method: "POST" }));
export const useMarkAllRead = () => useNotifMutation(() => api(`${BASE}read-all/`, { method: "POST" }));
export const useDeleteNotification = () => useNotifMutation((id: number) => api(`${BASE}${id}/`, { method: "DELETE" }));

export function usePreferences() {
  return useQuery({ queryKey: [...NOTIF_KEY, "preferences"], queryFn: () => api<NotificationPreferences>("me/notification-preferences/") });
}

export function useUpdatePreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<Omit<NotificationPreferences, "choices">>) =>
      api<NotificationPreferences>("me/notification-preferences/", { method: "PATCH", body }),
    onSuccess: (data) => qc.setQueryData([...NOTIF_KEY, "preferences"], data),
  });
}
