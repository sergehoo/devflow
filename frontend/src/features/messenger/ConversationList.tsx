import { BellOff, MessageSquarePlus, Search } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ErrorState } from "@/components/feedback/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Avatar, Skeleton } from "@/components/ui/misc";
import { useDebouncedValue } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { useContacts, useConversations, useOpenDirect, usePresence, type Conversation } from "./api";

const SECTIONS = [["direct", "Messages directs"], ["teams", "Équipes"], ["projects", "Projets"], ["groups", "Groupes"]] as const;
const timeFmt = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });
const dateFmt = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "short" });
const when = (iso: string | null) => {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toDateString() === new Date().toDateString() ? timeFmt.format(d) : dateFmt.format(d);
};
const PRESENCE_DOT: Record<string, string> = { online: "bg-emerald-500", idle: "bg-amber-400" };

export function PresenceDot({ status }: { status?: string }) {
  if (!status || !PRESENCE_DOT[status]) return null;
  return <span className={cn("absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full border-2 border-card", PRESENCE_DOT[status])}
    aria-label={status === "online" ? "En ligne" : "Inactif"} />;
}

/** Liste Messenger (DM, équipes, projets, groupes) + démarrage d'un message direct. */
export function ConversationList({ selectedId, onSelect }: { selectedId?: number | null; onSelect: (c: Conversation) => void }) {
  const [q, setQ] = useState("");
  const [composing, setComposing] = useState(false);
  const query = useDebouncedValue(q);
  const conversations = useConversations(query);
  const contacts = useContacts(query, composing);
  const openDirect = useOpenDirect();
  const presence = usePresence((conversations.data ?? []).map((c) => c.other_user_id).filter((x): x is number => x !== null));

  const startDirect = (userId: number, name: string) =>
    openDirect.mutate(userId, {
      onSuccess: (r) => {
        setComposing(false);
        setQ("");
        onSelect(r.conversation ?? { id: r.id, kind: "DM", section: "direct", title: name, other_user_id: userId, member_count: 2,
          last_message_preview: "", last_message_at: null, last_author_is_me: false, unread_count: 0, is_muted: false });
      },
      onError: (e) => toast.error(e.message),
    });

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b p-2.5">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden="true" />
          <Input type="search" className="pl-9" value={q} onChange={(e) => setQ(e.target.value)}
            placeholder={composing ? "Rechercher un collègue…" : "Rechercher une conversation…"} aria-label={composing ? "Rechercher un collègue" : "Rechercher une conversation"} />
        </div>
        <Button size="icon" variant={composing ? "outline" : "ghost"} aria-pressed={composing} aria-label="Nouveau message direct" onClick={() => setComposing((c) => !c)}>
          <MessageSquarePlus />
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-1.5">
        {composing ? (
          contacts.isPending ? <Skeleton className="h-40" /> : !contacts.data?.length ? (
            <p className="p-6 text-center text-sm text-muted-foreground">Aucun collègue trouvé.</p>
          ) : (
            <ul aria-label="Collègues">
              {contacts.data.map((u) => (
                <li key={u.id}>
                  <button type="button" disabled={openDirect.isPending} onClick={() => startDirect(u.id, u.display_name)}
                    className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left hover:bg-muted/60">
                    <Avatar name={u.display_name} className="size-8 text-xs" />
                    <span className="min-w-0"><span className="block truncate text-sm font-medium">{u.display_name}</span>
                      <span className="block truncate text-xs text-muted-foreground">{u.email}</span></span>
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : conversations.isPending ? <Skeleton className="h-60" /> : conversations.isError ? (
          <ErrorState message={conversations.error.message} onRetry={() => void conversations.refetch()} />
        ) : !conversations.data.length ? (
          <p className="p-6 text-center text-sm text-muted-foreground">Aucune conversation{q ? " pour cette recherche" : ""}.</p>
        ) : SECTIONS.map(([key, label]) => {
          const items = conversations.data.filter((c) => c.section === key);
          if (!items.length) return null;
          return (
            <section key={key} aria-label={label} className="mb-2">
              <h3 className="px-2.5 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-subtle-foreground">{label}</h3>
              <ul>
                {items.map((c) => (
                  <li key={c.id}>
                    <button type="button" onClick={() => onSelect(c)} aria-current={selectedId === c.id ? "true" : undefined}
                      className={cn("flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors hover:bg-muted/60",
                        selectedId === c.id && "bg-primary/10")}>
                      <span className="relative shrink-0"><Avatar name={c.title} className="size-9 text-xs" />
                        {c.other_user_id && <PresenceDot status={presence.data?.[c.other_user_id]} />}</span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-baseline justify-between gap-2">
                          <span className={cn("truncate text-sm", c.unread_count > 0 && !c.is_muted ? "font-semibold" : "font-medium")}>{c.title}</span>
                          <span className="shrink-0 text-[10px] text-subtle-foreground">{when(c.last_message_at)}</span>
                        </span>
                        <span className="flex items-center gap-1.5">
                          <span className="truncate text-xs text-muted-foreground">
                            {c.last_message_preview ? `${c.last_author_is_me ? "Vous : " : ""}${c.last_message_preview}` : `${c.member_count} participant(s)`}
                          </span>
                          {c.is_muted && <BellOff className="size-3 shrink-0 text-subtle-foreground" aria-label="En sourdine" />}
                          {c.unread_count > 0 && (
                            <span className={cn("ml-auto grid h-4 min-w-4 shrink-0 place-items-center rounded-full px-1 text-[10px] font-bold",
                              c.is_muted ? "bg-muted text-muted-foreground" : "bg-primary text-primary-foreground")}
                              aria-label={`${c.unread_count} non lu(s)`}>{c.unread_count}</span>
                          )}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
  );
}
