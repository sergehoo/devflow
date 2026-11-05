import { MessageCircle, X } from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";
import { useLocation } from "react-router";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";
import { cn } from "@/lib/utils";
import { totalUnread, useConversations } from "./api";
import { useMessengerUi } from "./store";

// Chargés à l'ouverture seulement : la coque n'embarque que le badge.
const Conversation = lazy(async () => ({ default: (await import("./Conversation")).Conversation }));
const ConversationList = lazy(async () => ({ default: (await import("./ConversationList")).ConversationList }));
const Loading = () => <Skeleton className="m-3 h-40" />;

const MOBILE = "(max-width: 767px)";

function useIsMobile() {
  const [mobile, setMobile] = useState(() => window.matchMedia(MOBILE).matches);
  useEffect(() => {
    const media = window.matchMedia(MOBILE);
    const onChange = (e: MediaQueryListEvent) => setMobile(e.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return mobile;
}

/** Bulle Messenger flottante globale : badge non lus, liste, mini-fenêtres (3 sur desktop, plein écran sur mobile). */
export function MessengerBubble() {
  const { pathname } = useLocation();
  const { panelOpen, windows, setPanelOpen, openWindow, closeWindow } = useMessengerUi();
  const { data } = useConversations();
  const mobile = useIsMobile();
  const unread = totalUnread(data);
  if (pathname.startsWith("/messenger")) return null;
  const visible = mobile ? windows.slice(-1) : windows;

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-40 flex items-end gap-3">
      {visible.map((w) => (
        <div key={w.id} className={cn("pointer-events-auto flex flex-col overflow-hidden rounded-2xl border bg-card shadow-2xl",
          mobile ? "fixed inset-0 rounded-none" : "h-[30rem] w-80")}>
          <Suspense fallback={<Loading />}>
            <Conversation channelId={w.id} title={w.title} subtitle={w.subtitle} compact onClose={() => closeWindow(w.id)} />
          </Suspense>
        </div>
      ))}
      <div className="pointer-events-auto relative flex flex-col items-end gap-3">
        {panelOpen && (
          <div role="dialog" aria-label="Conversations" className={cn("flex flex-col overflow-hidden rounded-2xl border bg-card shadow-2xl",
            mobile ? "fixed inset-0 rounded-none" : "h-[30rem] w-80")}>
            <div className="flex items-center justify-between border-b px-3 py-2">
              <p className="text-sm font-semibold">Messagerie</p>
              <Button size="icon" variant="ghost" aria-label="Fermer la messagerie" onClick={() => setPanelOpen(false)}><X /></Button>
            </div>
            <div className="min-h-0 flex-1">
              <Suspense fallback={<Loading />}>
                <ConversationList onSelect={(c) => {
                  openWindow({ id: c.id, title: c.title, subtitle: c.kind === "DM" ? "Message direct" : `${c.member_count} participants` }, mobile ? 1 : 3);
                  if (mobile) setPanelOpen(false);
                }} />
              </Suspense>
            </div>
          </div>
        )}
        {/* Mobile : panneau / fenêtre en plein écran → le bouton flottant ne doit rien recouvrir. */}
        {!(mobile && (panelOpen || visible.length > 0)) && <button type="button" onClick={() => setPanelOpen(!panelOpen)}
          aria-label={unread ? `Messagerie (${unread} message(s) non lu(s))` : "Messagerie"} aria-expanded={panelOpen}
          className="relative grid size-14 place-items-center rounded-full bg-primary text-primary-foreground shadow-xl transition-transform hover:scale-105 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring/40">
          <MessageCircle className="size-6" />
          {unread > 0 && (
            <span className="absolute -right-1 -top-1 grid h-5 min-w-5 place-items-center rounded-full border-2 border-card bg-destructive px-1 text-[11px] font-bold text-white">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </button>}
      </div>
    </div>
  );
}
