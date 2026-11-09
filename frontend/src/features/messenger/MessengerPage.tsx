import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";
import { EmptyState } from "@/components/feedback/states";
import { useConversations, useOpenDirect, type Conversation as Conv } from "./api";
import { Conversation } from "./Conversation";
import { ConversationList } from "./ConversationList";

const subtitleOf = (c: Conv) => (c.kind === "DM" ? "Message direct" : `${c.member_count} participants`);

/** Page Messenger : liste | conversation (une colonne sur mobile). `?channel=` et `?user=` comme /chat/. */
export function MessengerPage() {
  const [params, setParams] = useSearchParams();
  const selectedId = Number(params.get("channel")) || null;
  const { data: conversations } = useConversations();
  const openDirect = useOpenDirect();
  const handledUser = useRef<string | null>(null);
  const selected = conversations?.find((c) => c.id === selectedId);

  // Compatibilité des liens /chat/?user=<id> : ouvre (ou crée) le message direct.
  useEffect(() => {
    const userId = params.get("user");
    if (!userId || handledUser.current === userId) return;
    handledUser.current = userId;
    openDirect.mutate(Number(userId), {
      onSuccess: (r) => setParams({ channel: String(r.id) }, { replace: true }),
      onError: (e) => toast.error(e.message),
    });
  }, [params, openDirect, setParams]);

  const select = (c: Conv) => setParams({ channel: String(c.id) });

  return (
    <div className="flex h-[calc(100dvh-9.5rem)] min-h-[460px] overflow-hidden rounded-[22px] bg-card shadow-card dark:border dark:border-border">
      <div className={selectedId ? "hidden w-full md:block md:w-80 md:shrink-0 md:border-r" : "w-full md:w-80 md:shrink-0 md:border-r"}>
        <ConversationList selectedId={selectedId} onSelect={select} />
      </div>
      <div className={selectedId ? "flex min-w-0 flex-1 flex-col" : "hidden min-w-0 flex-1 md:flex md:flex-col"}>
        {selectedId ? (
          <Conversation key={selectedId} channelId={selectedId} title={selected?.title ?? "Conversation"}
            subtitle={selected ? subtitleOf(selected) : undefined} onBack={() => setParams({})} />
        ) : (
          <div className="grid flex-1 place-items-center p-6">
            <EmptyState title="Sélectionnez une conversation" description="Messages directs, équipes et projets : tout est synchronisé automatiquement." />
          </div>
        )}
      </div>
    </div>
  );
}
