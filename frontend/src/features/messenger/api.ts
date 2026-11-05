import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData, type QueryClient } from "@tanstack/react-query";
import { useMe } from "@/features/auth/api";
import { useRealtimeStatus } from "@/lib/realtime";
import { api } from "@/services/api";

export interface Conversation {
  id: number;
  kind: "DM" | "TEAM" | "PROJECT" | "GROUP" | string;
  section: "direct" | "teams" | "projects" | "groups";
  title: string;
  other_user_id: number | null;
  member_count: number;
  last_message_preview: string;
  last_message_at: string | null;
  last_author_is_me: boolean;
  unread_count: number;
  is_muted: boolean;
}
export interface Attachment {
  id: number;
  name: string;
  url: string;
  size: number;
  mime_type: string;
  is_image: boolean;
}
export interface Reaction {
  emoji: string;
  count: number;
  mine: boolean;
}
export interface ChatMessage {
  id?: number;
  client_id?: string | null;
  channel_id?: number;
  author_id: number;
  author_name?: string;
  body: string;
  created_at?: string;
  is_edited?: boolean;
  attachments: Attachment[];
  reactions: Reaction[];
  pending?: boolean;
}
interface MessagesPage {
  channel: { id: number; display_name: string; member_count: number };
  messages: ChatMessage[];
  others_last_read_at: string | null;
}
export interface Contact {
  id: number;
  display_name: string;
  username?: string;
  email?: string;
  job_title?: string;
}
export interface Member {
  user_id: number;
  display_name: string;
  email: string;
  is_self: boolean;
  presence: { status: "online" | "idle" | "offline" | string; inactive_minutes: number | null };
}

export const CHAT_KEY = ["chat"] as const;
export const CONVERSATIONS_KEY = [...CHAT_KEY, "conversations"] as const;
export const messagesKey = (id: number) => [...CHAT_KEY, "messages", id] as const;
export const PAGE_SIZE = 50;
export const REACTIONS = ["👍", "❤️", "😂", "😮", "😢", "🎉"] as const;
export const MAX_FILES = 5;
export const MAX_FILE_BYTES = 20 * 1024 * 1024;

/** Liste Messenger du workspace courant ; temps réel via /ws/me/, polling de secours. */
export function useConversations(q = "") {
  const { data: me } = useMe();
  const live = useRealtimeStatus("/ws/me/") === "open";
  return useQuery({
    queryKey: [...CONVERSATIONS_KEY, me?.workspace?.id ?? null, q],
    queryFn: () => api<{ conversations: Conversation[] }>("me/chat/conversations/", { params: { q, workspace_id: me?.workspace?.id } }),
    select: (d) => d.conversations,
    enabled: Boolean(me),
    refetchInterval: live ? false : 20_000,
    placeholderData: (prev) => prev,
  });
}

export const totalUnread = (list: Conversation[] | undefined) =>
  (list ?? []).reduce((sum, c) => sum + (c.is_muted ? 0 : c.unread_count), 0);

export function useContacts(q: string, enabled = true) {
  const { data: me } = useMe();
  return useQuery({
    queryKey: [...CHAT_KEY, "contacts", me?.workspace?.id ?? null, q],
    queryFn: () => api<{ contacts: Contact[] }>("me/chat/contacts/", { params: { q, limit: 50, workspace_id: me?.workspace?.id } }),
    select: (d) => d.contacts,
    enabled: enabled && Boolean(me),
  });
}

export function useMessages(channelId: number) {
  return useInfiniteQuery({
    queryKey: messagesKey(channelId),
    queryFn: ({ pageParam }) =>
      api<MessagesPage>(`me/chat/channels/${channelId}/messages/`, { params: { limit: PAGE_SIZE, before: pageParam } }),
    initialPageParam: undefined as number | undefined,
    // Pages : [récents, plus anciens, …] ; la suivante charge l'historique avant le plus ancien message.
    getNextPageParam: (last) => (last.messages.length < PAGE_SIZE ? undefined : last.messages[0]?.id),
    staleTime: Infinity,
  });
}

export const flattenMessages = (data: InfiniteData<MessagesPage> | undefined) =>
  data ? [...data.pages].reverse().flatMap((p) => p.messages) : [];

const sameMessage = (a: ChatMessage, b: ChatMessage) =>
  (a.id !== undefined && a.id === b.id) || (Boolean(a.client_id) && a.client_id === b.client_id);

/** Fusion idempotente (écho WebSocket + réponse HTTP + optimiste) : jamais de doublon. */
export function upsertMessage(qc: QueryClient, channelId: number, message: ChatMessage) {
  qc.setQueryData<InfiniteData<MessagesPage>>(messagesKey(channelId), (data) => {
    if (!data) return data;
    let found = false;
    const pages = data.pages.map((p) => ({
      ...p,
      messages: p.messages.map((m) => {
        if (!sameMessage(m, message)) return m;
        found = true;
        return { ...m, ...message, pending: false, client_id: m.client_id ?? message.client_id };
      }),
    }));
    if (!found && pages[0]) pages[0] = { ...pages[0], messages: [...pages[0].messages, message] };
    return { ...data, pages };
  });
}

export function patchMessage(qc: QueryClient, channelId: number, id: number, patch: (m: ChatMessage) => Partial<ChatMessage>) {
  qc.setQueryData<InfiniteData<MessagesPage>>(messagesKey(channelId), (data) =>
    data && { ...data, pages: data.pages.map((p) => ({ ...p, messages: p.messages.map((m) => (m.id === id ? { ...m, ...patch(m) } : m)) })) });
}

export function removeMessage(qc: QueryClient, channelId: number, clientId: string) {
  qc.setQueryData<InfiniteData<MessagesPage>>(messagesKey(channelId), (data) =>
    data && { ...data, pages: data.pages.map((p) => ({ ...p, messages: p.messages.filter((m) => m.client_id !== clientId) })) });
}

export function setOthersRead(qc: QueryClient, channelId: number, at: string) {
  qc.setQueryData<InfiniteData<MessagesPage>>(messagesKey(channelId), (data) =>
    data && { ...data, pages: data.pages.map((p, i) => (i === 0 ? { ...p, others_last_read_at: at } : p)) });
}

let seq = 0;
export const newClientId = () => `c${Date.now().toString(36)}${(seq++).toString(36)}`;

export function useSendMessage(channelId: number) {
  const qc = useQueryClient();
  const { data: me } = useMe();
  return useMutation({
    mutationFn: ({ body, files, clientId }: { body: string; files: File[]; clientId: string }) => {
      const fd = new FormData();
      fd.append("body", body);
      fd.append("client_id", clientId);
      files.forEach((f) => fd.append("files", f));
      return api<ChatMessage>(`me/chat/channels/${channelId}/messages/`, { method: "POST", body: fd });
    },
    onMutate: ({ body, clientId }) => {
      upsertMessage(qc, channelId, {
        client_id: clientId, author_id: me?.id ?? 0, body: body || "📎", attachments: [], reactions: [],
        created_at: new Date().toISOString(), pending: true,
      });
    },
    onSuccess: (message, { clientId }) => {
      upsertMessage(qc, channelId, { ...message, client_id: clientId });
      void qc.invalidateQueries({ queryKey: CONVERSATIONS_KEY });
    },
    onError: (_e, { clientId }) => removeMessage(qc, channelId, clientId),
  });
}

export function useToggleReaction(channelId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, emoji }: { id: number; emoji: string }) =>
      api<{ message_id: number; reactions: Reaction[] }>(`me/chat/messages/${id}/reactions/`, { method: "POST", body: { emoji } }),
    onSuccess: (r) => patchMessage(qc, channelId, r.message_id, () => ({ reactions: r.reactions })),
  });
}

export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (channelId: number) => api(`me/chat/channels/${channelId}/mark-read/`, { method: "POST" }),
    onSuccess: (_r, channelId) => {
      qc.setQueriesData<{ conversations: Conversation[] }>({ queryKey: CONVERSATIONS_KEY }, (d) =>
        d && { ...d, conversations: d.conversations.map((c) => (c.id === channelId ? { ...c, unread_count: 0 } : c)) });
    },
  });
}

export function useOpenDirect() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: number) =>
      api<{ id: number; conversation: Conversation | null }>("me/chat/direct/", { method: "POST", body: { user_id: userId } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: CONVERSATIONS_KEY }),
  });
}

export function useMembers(channelId: number, enabled: boolean) {
  return useQuery({
    queryKey: [...CHAT_KEY, "members", channelId],
    queryFn: () => api<{ members: Member[]; member_count: number }>(`me/chat/channels/${channelId}/members/`),
    enabled,
    refetchInterval: enabled ? 60_000 : false,
  });
}

export function usePresence(userIds: number[]) {
  const ids = [...new Set(userIds)].sort((a, b) => a - b).slice(0, 500);
  return useQuery({
    queryKey: [...CHAT_KEY, "presence", ids.join(",")],
    queryFn: () => api<{ statuses: { user_id: number; status: string }[] }>("me/presence/", { params: { user_ids: ids.join(",") } }),
    select: (d) => Object.fromEntries(d.statuses.map((s) => [s.user_id, s.status])) as Record<number, string>,
    enabled: ids.length > 0,
    refetchInterval: 60_000,
  });
}
