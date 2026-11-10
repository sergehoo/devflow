import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/services/api";
import type { Paginated } from "@/types/api";

export const TICKETS_KEY = ["tickets"] as const;

type Ref = { id: number; name: string } | null;

export interface TicketRow {
  id: number; reference: string; title: string; status: string; status_label: string;
  priority: string; priority_label: string; severity: string; severity_label: string; category: string; category_label: string;
  application: Ref; team: Ref; assignee: Ref; project: Ref; task_id: number | null; reporter_name: string; workspace: number;
  created_at: string; updated_at: string; first_response_due: string | null; resolution_due: string | null;
  first_response_breached: boolean; resolution_breached: boolean; escalation_level: number; sla_paused: boolean;
}

export interface TicketDetail extends TicketRow {
  description: string; environment: string; app_version: string; url: string; metadata: Record<string, unknown>;
  external_id: string; reporter_email: string; reporter_external_id: string; task: { id: number; name: string } | null;
  qualified_at: string | null; assigned_at: string | null; first_response_at: string | null; resolved_at: string | null;
  closed_at: string | null; reopened_count: number;
  sla: {
    policy: string; first_response_due: string | null; resolution_due: string | null;
    first_response_remaining_seconds: number | null; resolution_remaining_seconds: number | null; paused: boolean;
    first_response_breached: boolean; resolution_breached: boolean; escalation_level: number;
  };
  comments: { id: number; body: string; visibility: "PUBLIC" | "INTERNAL"; created_at: string; author: string; external: boolean }[];
  attachments: { id: number; name: string; mime_type: string; size: number; visibility: string; created_at: string; uploaded_by: string; download_url: string }[];
  events: { id: number; action: string; actor: string; origin: string; old: Record<string, unknown> | null; new: Record<string, unknown> | null; public: boolean; created_at: string }[];
  allowed_transitions: { value: string; label: string }[];
  rights: { manage: boolean; assign: boolean; work: boolean };
}

export interface TicketDashboard {
  open: number; unassigned: number; mine: number; breached: number; due_24h: number; created_7d: number; resolved_7d: number;
  sla_compliance: number | null; avg_first_response_minutes: number | null;
  by_status: Record<string, number>; by_priority: Record<string, number>;
  by_application: { id: number; name: string; open: number }[]; at_risk: TicketRow[];
}

export interface ExternalApp {
  id: number; workspace: number; name: string; code: string; description: string; project: number | null; environment: string;
  status: string; teams: number[]; default_team: number | null; sla_policy: number | null; key_id: string; secret_last4: string;
  secret_rotated_at: string | null; webhook_url: string; webhook_events: string[]; rate_limit_per_minute: number;
  daily_ticket_quota: number; max_attachment_mb: number; retention_days: number | null; config: Record<string, unknown>;
  created_at: string; open_tickets: number; secret?: string;
}

export interface RoutingRule {
  id: number; workspace: number; name: string; application: number | null; category: string; severity: string; team: number;
  auto_assign: boolean; priority_override: string; position: number; is_active: boolean;
}

export interface SlaPolicy {
  id: number; workspace: number; name: string; is_default: boolean; targets: Record<string, { first_response: number; resolution: number }>;
  business_hours_only: boolean; business_start: string; business_end: string; business_days: number[]; timezone: string;
  warn_before_percent: number; escalation_team: number | null; auto_escalate: boolean;
}

export interface Delivery {
  id: number; event: string; event_id: string; status: string; status_label: string; attempt: number; response_status: number | null;
  error: string; ticket: string; next_attempt_at: string | null; delivered_at: string | null; created_at: string;
}

export type TicketFilters = Record<string, string | number | undefined>;

export function useTickets(filters: TicketFilters, enabled = true) {
  return useQuery({
    queryKey: [...TICKETS_KEY, "list", filters], enabled, placeholderData: keepPreviousData,
    queryFn: ({ signal }) => api<Paginated<TicketRow>>("tickets/", { signal, params: filters }),
  });
}

export const useTicket = (id: number) =>
  useQuery({ queryKey: [...TICKETS_KEY, id], queryFn: ({ signal }) => api<TicketDetail>(`tickets/${id}/`, { signal }) });

export const useTicketDashboard = (workspace?: number) =>
  useQuery({
    queryKey: [...TICKETS_KEY, "dashboard", workspace], enabled: Boolean(workspace),
    queryFn: ({ signal }) => api<TicketDashboard>("tickets/dashboard/", { signal, params: { workspace } }),
  });

export const useAssignable = (id: number, team: number | null | undefined, enabled: boolean) =>
  useQuery({
    queryKey: [...TICKETS_KEY, id, "assignable", team], enabled,
    queryFn: ({ signal }) => api<{ teams: { id: number; name: string }[]; team: number | null; agents: { id: number; name: string }[] }>(
      `tickets/${id}/assignable/`, { signal, params: { team: team ?? undefined } }),
  });

/** Action sur un ticket (transition, assign, qualify, escalate, comment, create-task) : renvoie la fiche à jour. */
export function useTicketAction(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ action, body }: { action: string; body: Record<string, unknown> | FormData }) =>
      api<TicketDetail>(`tickets/${id}/${action}/`, { method: "POST", body }),
    onSuccess: (data) => {
      qc.setQueryData([...TICKETS_KEY, id], data);
      void qc.invalidateQueries({ queryKey: [...TICKETS_KEY, "list"] });
      void qc.invalidateQueries({ queryKey: [...TICKETS_KEY, "dashboard"] });
    },
  });
}

// ─── Configuration (applications, routage, SLA) ──────────────────────────────

export function useConfigList<T>(resource: "ticket-applications" | "ticket-routing-rules" | "ticket-sla-policies", workspace?: number) {
  return useQuery({
    queryKey: [...TICKETS_KEY, resource, workspace], enabled: Boolean(workspace),
    queryFn: ({ signal }) => api<Paginated<T>>(`${resource}/`, { signal, params: { workspace, page_size: 100 } }),
  });
}

export function useConfigSave<T extends { id?: number }>(resource: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (item: Partial<T>) =>
      api<T>(item.id ? `${resource}/${item.id}/` : `${resource}/`, { method: item.id ? "PATCH" : "POST", body: item as Record<string, unknown> }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: [...TICKETS_KEY, resource] }),
  });
}

export function useConfigDelete(resource: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api(`${resource}/${id}/`, { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: [...TICKETS_KEY, resource] }),
  });
}

export const useDeliveries = (appId: number | null) =>
  useQuery({
    queryKey: [...TICKETS_KEY, "deliveries", appId], enabled: appId != null,
    queryFn: ({ signal }) => api<Delivery[]>(`ticket-applications/${appId}/deliveries/`, { signal }),
  });
