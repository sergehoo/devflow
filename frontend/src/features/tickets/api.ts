import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMe } from "@/features/auth/api";
import { can } from "@/lib/permissions";
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
  source: "API" | "MANUAL" | "EMAIL"; source_label: string;
}

export interface TicketEmail {
  id: number; direction: "IN" | "OUT"; kind: string; kind_label: string; status: string; status_label: string;
  from: string; to: string; subject: string; reason: string; comment_id: number | null; attempt: number; created_at: string;
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
  rights: { manage: boolean; assign: boolean; work: boolean; reply: boolean };
  created_by: { id: number; name: string } | null;
  mailbox: { id: number; name: string; address: string } | null;
  email_reply: boolean;
  emails: TicketEmail[];
}

export interface CreateOptions {
  workspace: number;
  applications: { id: number; name: string; project: number | null; default_team: number | null }[];
  projects: { id: number; name: string }[];
  teams: { id: number; name: string }[];
  can_assign: boolean; can_set_priority: boolean; max_files: number; max_attachment_mb: number;
}

export interface Mailbox {
  id: number; workspace: number; application: number; project: number | null; name: string; address: string; from_name: string;
  is_active: boolean; inbound: "IMAP" | "WEBHOOK"; imap_host: string; imap_port: number; imap_security: "SSL" | "STARTTLS";
  imap_username: string; imap_folder: string; has_imap_password: boolean; smtp_host: string; smtp_port: number;
  smtp_security: "SSL" | "STARTTLS"; smtp_username: string; has_smtp_password: boolean; auto_acknowledge: boolean;
  default_category: string; allowed_domains: string[]; blocked_senders: string[]; max_attachment_mb: number; inbound_key: string;
  webhook_url: string; last_sync_at: string | null; last_success_at: string | null; last_error: string; last_error_at: string | null;
  consecutive_failures: number; stats: Record<string, number>; created_at: string;
  imap_password?: string; smtp_password?: string; webhook_secret?: string;
}

export interface MailMessage {
  id: number; direction: "IN" | "OUT"; kind: string; kind_label: string; status: string; status_label: string; from: string;
  from_name: string; to: string; subject: string; reason: string; size: number; attempt: number; created_at: string;
  processed_at: string | null; ticket: { id: number; reference: string } | null; can_reprocess: boolean;
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

export function useConfigList<T>(resource: "ticket-applications" | "ticket-routing-rules" | "ticket-sla-policies" | "ticket-mailboxes", workspace?: number) {
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

// ─── Création manuelle ───────────────────────────────────────────────────────

export const useCreateOptions = (workspace: number | undefined, enabled: boolean) =>
  useQuery({
    queryKey: [...TICKETS_KEY, "create-options", workspace], enabled: enabled && Boolean(workspace), staleTime: 60_000,
    queryFn: ({ signal }) => api<CreateOptions>("tickets/create-options/", { signal, params: { workspace } }),
  });

export const useTeamAgents = (team: number | null, enabled: boolean) =>
  useQuery({
    queryKey: [...TICKETS_KEY, "agents", team], enabled: enabled && team != null, staleTime: 60_000,
    queryFn: ({ signal }) => api<{ id: number; name: string }[]>("tickets/agents/", { signal, params: { team: team ?? undefined } }),
  });

export function useCreateTicket() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: FormData) => api<TicketDetail>("tickets/", { method: "POST", body }),
    onSuccess: (data) => {
      qc.setQueryData([...TICKETS_KEY, data.id], data);
      void qc.invalidateQueries({ queryKey: [...TICKETS_KEY, "list"] });
      void qc.invalidateQueries({ queryKey: [...TICKETS_KEY, "dashboard"] });
    },
  });
}

// ─── Canal e-mail ────────────────────────────────────────────────────────────

export const useMailMessages = (mailbox: number | null, status: string, page = 1) =>
  useQuery({
    queryKey: [...TICKETS_KEY, "mail-messages", mailbox, status, page], enabled: mailbox != null, placeholderData: keepPreviousData,
    queryFn: ({ signal }) => api<Paginated<MailMessage>>(`ticket-mailboxes/${mailbox}/messages/`, {
      signal, params: { status: status || undefined, page, page_size: 50 },
    }),
  });

export function useCanCreateTicket() {
  const { data: me } = useMe();
  return can(me?.permissions, "ticket.create");
}

type Option = { id: number; name: string };

export function useWorkspaceOptions(workspace?: number) {
  const opts = (path: string) => ({
    queryKey: ["tickets", "options", path, workspace], enabled: Boolean(workspace), staleTime: 60_000,
    queryFn: ({ signal }: { signal: AbortSignal }) => api<Paginated<Option>>(path, { signal, params: { workspace, page_size: 200 } }),
  });
  const projects = useQuery(opts("projects/"));
  const teams = useQuery(opts("teams/"));
  return { projects: projects.data?.results ?? [], teams: teams.data?.results ?? [] };
}
