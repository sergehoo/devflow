import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileText, Loader2, Paperclip, SendHorizontal, SmilePlus, Users, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { toast } from "sonner";
import { ErrorState } from "@/components/feedback/states";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Avatar, Skeleton } from "@/components/ui/misc";
import { useMe } from "@/features/auth/api";
import { formatDate } from "@/lib/format";
import { realtime, useRealtimeStatus, type RealtimeMessage } from "@/lib/realtime";
import { cn } from "@/lib/utils";
import {
  MAX_FILE_BYTES, MAX_FILES, REACTIONS, flattenMessages, newClientId, patchMessage, setOthersRead,
  upsertMessage, useMarkRead, useMembers, useMessages, useSendMessage, useToggleReaction, type ChatMessage, type Reaction,
} from "./api";

const timeFmt = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });
const dayKey = (iso?: string) => (iso ? iso.slice(0, 10) : "");
const dayLabel = (iso?: string) => {
  const key = dayKey(iso);
  const today = new Date().toISOString().slice(0, 10);
  return key === today ? "Aujourd'hui" : formatDate(key);
};
const sizeLabel = (bytes: number) => (bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} Mo` : `${Math.max(1, Math.round(bytes / 1024))} Ko`);

/** Abonnement au WebSocket de la conversation : messages, réactions, accusés de lecture, saisie. */
function useChannelSocket(channelId: number, meId: number | undefined, onIncoming: () => void) {
  const qc = useQueryClient();
  const [typing, setTyping] = useState("");
  const path = `/ws/channels/${channelId}/`;
  const status = useRealtimeStatus(path);
  // Refs : changer d'utilisateur courant ou de callback ne doit pas rouvrir le socket.
  const incoming = useRef(onIncoming);
  const me = useRef(meId);
  useEffect(() => { incoming.current = onIncoming; me.current = meId; }, [onIncoming, meId]);

  useEffect(() => {
    let clearTyping: ReturnType<typeof setTimeout> | undefined;
    const unsubscribe = realtime.subscribe(path, (msg: RealtimeMessage) => {
      if (msg.type === "socket.open" && msg.reconnected) {
        void qc.invalidateQueries({ queryKey: ["chat", "messages", channelId] });
      } else if (msg.type === "chat_message") {
        const m = msg.message as ChatMessage;
        upsertMessage(qc, channelId, m);
        if (m.author_id !== me.current) incoming.current();
      } else if (msg.type === "reaction") {
        // Diffusion sans contexte utilisateur : on conserve nos propres « mine ».
        const reactions = msg.reactions as Reaction[];
        patchMessage(qc, channelId, msg.message_id as number, (m) => {
          const mine = new Set(m.reactions.filter((r) => r.mine).map((r) => r.emoji));
          return { reactions: reactions.map((r) => ({ ...r, mine: r.mine || mine.has(r.emoji) })) };
        });
      } else if (msg.type === "read" && msg.user_id !== me.current) {
        setOthersRead(qc, channelId, msg.last_read_at as string);
      } else if (msg.type === "typing") {
        clearTimeout(clearTyping);
        setTyping(msg.is_typing ? String(msg.display_name ?? "") : "");
        if (msg.is_typing) clearTyping = setTimeout(() => setTyping(""), 4000);
      }
    });
    return () => { clearTimeout(clearTyping); unsubscribe(); };
  }, [path, channelId, qc]);

  return { typing, live: status === "open", send: (data: unknown) => realtime.send(path, data) };
}

function MessageBubble({ m, mine, onReact }: { m: ChatMessage; mine: boolean; onReact: (emoji: string) => void }) {
  const [picker, setPicker] = useState(false);
  return (
    <div className={cn("group flex gap-2", mine ? "flex-row-reverse" : "flex-row")}>
      {!mine && <Avatar name={m.author_name ?? "?"} className="mt-5 size-7 text-[10px]" />}
      <div className={cn("flex max-w-[78%] flex-col", mine ? "items-end" : "items-start")}>
        {!mine && <span className="mb-0.5 px-1 text-[11px] font-medium text-muted-foreground">{m.author_name}</span>}
        <div className="relative">
          <div className={cn("whitespace-pre-wrap break-words rounded-2xl px-3 py-2 text-sm",
            mine ? "rounded-br-md bg-primary text-primary-foreground" : "rounded-bl-md bg-muted", m.pending && "opacity-60")}>
            {m.body !== "📎" || !m.attachments.length ? m.body : null}
            {m.attachments.length > 0 && (
              <div className="mt-1 space-y-1">
                {m.attachments.map((a) => a.is_image ? (
                  <a key={a.id} href={a.url} target="_blank" rel="noopener noreferrer" className="block">
                    <img src={a.url} alt={a.name} loading="lazy" className="max-h-48 rounded-lg object-cover" />
                  </a>
                ) : (
                  <a key={a.id} href={a.url} target="_blank" rel="noopener noreferrer"
                    className={cn("flex items-center gap-2 rounded-lg px-2 py-1 text-xs underline-offset-2 hover:underline", mine ? "bg-white/15" : "bg-card")}>
                    <FileText className="size-4 shrink-0" aria-hidden="true" /><span className="truncate">{a.name}</span><span className="shrink-0 opacity-70">{sizeLabel(a.size)}</span>
                  </a>
                ))}
              </div>
            )}
          </div>
          {m.id !== undefined && (
            <button type="button" aria-label="Réagir" onClick={() => setPicker((p) => !p)}
              className={cn("absolute top-1/2 hidden -translate-y-1/2 rounded-full border bg-card p-1 text-muted-foreground shadow-sm hover:text-foreground group-hover:block focus-visible:block",
                mine ? "-left-8" : "-right-8")}>
              <SmilePlus className="size-3.5" />
            </button>
          )}
          {picker && (
            <div role="menu" className={cn("absolute bottom-full z-10 mb-1 flex gap-0.5 rounded-full border bg-card p-1 shadow-lg", mine ? "right-0" : "left-0")}>
              {REACTIONS.map((e) => (
                <button key={e} type="button" role="menuitem" className="rounded-full px-1.5 py-0.5 text-base hover:bg-muted" aria-label={`Réagir ${e}`}
                  onClick={() => { setPicker(false); onReact(e); }}>{e}</button>
              ))}
            </div>
          )}
        </div>
        {m.reactions.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {m.reactions.map((r) => (
              <button key={r.emoji} type="button" onClick={() => onReact(r.emoji)} aria-pressed={r.mine}
                aria-label={`${r.emoji} ${r.count}${r.mine ? " (vous)" : ""}`}
                className={cn("rounded-full border px-1.5 text-xs tabular-nums", r.mine ? "border-primary bg-primary/10" : "bg-card")}>
                {r.emoji} {r.count}
              </button>
            ))}
          </div>
        )}
        <span className="mt-0.5 px-1 text-[10px] text-subtle-foreground">
          {m.pending ? "Envoi…" : m.created_at ? timeFmt.format(new Date(m.created_at)) : ""}{m.is_edited ? " · modifié" : ""}
        </span>
      </div>
    </div>
  );
}

function MembersPanel({ channelId, onClose }: { channelId: number; onClose: () => void }) {
  const { data, isPending } = useMembers(channelId, true);
  const dot: Record<string, string> = { online: "bg-emerald-500", idle: "bg-amber-400" };
  return (
    <aside aria-label="Participants" className="flex w-64 shrink-0 flex-col border-l bg-card">
      <div className="flex items-center justify-between border-b px-3 py-2.5">
        <p className="text-sm font-semibold">Participants{data ? ` (${data.member_count})` : ""}</p>
        <Button size="icon" variant="ghost" aria-label="Fermer les participants" onClick={onClose}><X /></Button>
      </div>
      <ul className="flex-1 space-y-1 overflow-y-auto p-2">
        {isPending ? <Skeleton className="h-32" /> : data?.members.map((m) => (
          <li key={m.user_id} className="flex items-center gap-2 rounded-lg px-2 py-1.5">
            <span className="relative"><Avatar name={m.display_name} className="size-7 text-[10px]" />
              <span className={cn("absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full border-2 border-card", dot[m.presence.status] ?? "bg-muted-foreground/40")}
                aria-label={m.presence.status === "online" ? "En ligne" : m.presence.status === "idle" ? "Inactif" : "Hors ligne"} />
            </span>
            <span className="min-w-0"><span className="block truncate text-sm">{m.display_name}{m.is_self && " (vous)"}</span>
              <span className="block truncate text-[11px] text-muted-foreground">{m.email}</span></span>
          </li>
        ))}
      </ul>
    </aside>
  );
}

export interface ConversationProps {
  channelId: number;
  title: string;
  subtitle?: string;
  compact?: boolean;
  onBack?: () => void;
  onClose?: () => void;
}

/** Fil de discussion : historique paginé, temps réel, pièces jointes, réactions, accusés de lecture. */
export function Conversation({ channelId, title, subtitle, compact, onBack, onClose }: ConversationProps) {
  const { data: me } = useMe();
  const messages = useMessages(channelId);
  const send = useSendMessage(channelId);
  const react = useToggleReaction(channelId);
  const markRead = useMarkRead();
  const [draft, setDraft] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [showMembers, setShowMembers] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const lastTyping = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);

  const read = useCallback(() => {
    if (document.visibilityState === "visible") markRead.mutate(channelId);
  }, [channelId, markRead]);
  const socket = useChannelSocket(channelId, me?.id, read);
  useEffect(() => { markRead.mutate(channelId); }, [channelId]); // eslint-disable-line react-hooks/exhaustive-deps

  const list = flattenMessages(messages.data);
  const othersRead = messages.data?.pages[0]?.others_last_read_at ?? null;
  const lastMine = [...list].reverse().find((m) => m.author_id === me?.id && !m.pending);
  const seen = Boolean(lastMine?.created_at && othersRead && othersRead >= lastMine.created_at && list[list.length - 1] === lastMine);

  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [list.length, socket.typing]);

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  const loadOlder = async () => {
    const el = scroller.current;
    const before = el?.scrollHeight ?? 0;
    stickToBottom.current = false;
    await messages.fetchNextPage();
    requestAnimationFrame(() => { if (el) el.scrollTop += el.scrollHeight - before; });
  };

  const addFiles = (picked: FileList | null) => {
    if (!picked) return;
    const next = [...files, ...Array.from(picked)];
    const tooBig = next.find((f) => f.size > MAX_FILE_BYTES);
    if (tooBig) return toast.error(`« ${tooBig.name} » dépasse ${MAX_FILE_BYTES / 1024 / 1024} Mo.`);
    if (next.length > MAX_FILES) return toast.error(`${MAX_FILES} pièces jointes maximum par message.`);
    setFiles(next);
  };

  const submit = () => {
    const body = draft.trim();
    if ((!body && !files.length) || send.isPending) return;
    const pendingFiles = files;
    stickToBottom.current = true;
    socket.send({ type: "typing.stop" });
    setDraft("");
    setFiles([]);
    send.mutate({ body, files: pendingFiles, clientId: newClientId() }, {
      onError: (e) => { toast.error(e.message); setDraft(body); setFiles(pendingFiles); },
    });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    } else if (Date.now() - lastTyping.current > 2500) {
      lastTyping.current = Date.now();
      socket.send({ type: "typing.start" });
    }
  };

  return (
    <div className="flex h-full min-h-0">
      <section aria-label={`Conversation ${title}`} className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b px-3 py-2.5">
          {onBack && <Button size="icon" variant="ghost" className="md:hidden" aria-label="Retour aux conversations" onClick={onBack}><ArrowLeft /></Button>}
          <Avatar name={title} className="size-8 text-xs" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold">{title}</p>
            <p className="truncate text-[11px] text-muted-foreground">
              {socket.typing ? <span className="text-primary">{socket.typing} écrit…</span> : subtitle}
              {!socket.live && <span className="ml-1">· reconnexion…</span>}
            </p>
          </div>
          {!compact && <Button size="icon" variant={showMembers ? "outline" : "ghost"} aria-pressed={showMembers} aria-label="Participants" onClick={() => setShowMembers((s) => !s)}><Users /></Button>}
          {onClose && <Button size="icon" variant="ghost" aria-label={`Fermer ${title}`} onClick={onClose}><X /></Button>}
        </header>

        <div ref={scroller} onScroll={onScroll} className="flex-1 space-y-3 overflow-y-auto px-3 py-3" aria-live="polite">
          {messages.isPending ? <Skeleton className="h-40" /> : messages.isError ? (
            <ErrorState message={messages.error.message} onRetry={() => void messages.refetch()} />
          ) : (
            <>
              {messages.hasNextPage && (
                <div className="text-center">
                  <Button size="sm" variant="ghost" disabled={messages.isFetchingNextPage} onClick={() => void loadOlder()}>
                    {messages.isFetchingNextPage && <Loader2 className="animate-spin" />}Messages précédents
                  </Button>
                </div>
              )}
              {list.length === 0 && <p className="py-10 text-center text-sm text-muted-foreground">Aucun message. Lancez la conversation !</p>}
              {list.map((m, i) => (
                <div key={m.id ?? m.client_id}>
                  {dayKey(m.created_at) !== dayKey(list[i - 1]?.created_at) && (
                    <p className="my-2 text-center text-[11px] font-medium uppercase tracking-wide text-subtle-foreground">{dayLabel(m.created_at)}</p>
                  )}
                  <MessageBubble m={m} mine={m.author_id === me?.id}
                    onReact={(emoji) => m.id !== undefined && react.mutate({ id: m.id, emoji }, { onError: (e) => toast.error(e.message) })} />
                </div>
              ))}
              {seen && <p className="text-right text-[11px] text-muted-foreground">Vu</p>}
            </>
          )}
        </div>

        <form className="border-t p-2" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          {files.length > 0 && (
            <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="Pièces jointes">
              {files.map((f, i) => (
                <li key={`${f.name}-${i}`} className="flex items-center gap-1 rounded-full border bg-muted/50 py-0.5 pl-2.5 pr-1 text-xs">
                  <span className="max-w-40 truncate">{f.name}</span>
                  <button type="button" className="rounded-full p-0.5 hover:bg-muted" aria-label={`Retirer ${f.name}`}
                    onClick={() => setFiles(files.filter((_, j) => j !== i))}><X className="size-3" /></button>
                </li>
              ))}
            </ul>
          )}
          <div className="flex items-end gap-1.5">
            <input ref={fileInput} type="file" multiple hidden onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
            <Button type="button" size="icon" variant="ghost" aria-label="Joindre des fichiers" onClick={() => fileInput.current?.click()}><Paperclip /></Button>
            <Textarea rows={1} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown}
              onBlur={() => socket.send({ type: "typing.stop" })} maxLength={5000}
              placeholder="Écrire un message…" aria-label="Message" className="max-h-32 min-h-10 flex-1 resize-none" />
            <Button type="submit" size="icon" aria-label="Envoyer" disabled={(!draft.trim() && !files.length) || send.isPending}><SendHorizontal /></Button>
          </div>
        </form>
      </section>
      {showMembers && !compact && <MembersPanel channelId={channelId} onClose={() => setShowMembers(false)} />}
    </div>
  );
}
