import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { CHAT_KEY, CONVERSATIONS_KEY } from "@/features/messenger/api";
import { NOTIF_KEY, SUMMARY_KEY, type AppNotification, type NotificationSummary } from "@/features/notifications/api";
import { resolveLegacyLink } from "@/lib/links";
import { realtime, type RealtimeMessage } from "@/lib/realtime";
import { api } from "@/services/api";

const PRESENCE_HEARTBEAT_MS = 30_000; // même cadence que l'ancien runtime chat

/**
 * Pont temps réel unique monté dans la coque : flux personnel /ws/me/ → caches TanStack Query.
 * Les événements ne font qu'invalider / ajuster les données ; Django reste la source de vérité.
 */
export function RealtimeBridge() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const seen = useRef(new Set<number>());

  useEffect(() => {
    return realtime.subscribe("/ws/me/", (msg: RealtimeMessage) => {
      switch (msg.type) {
        case "socket.open":
          if (msg.reconnected) {
            void qc.invalidateQueries({ queryKey: NOTIF_KEY });
            void qc.invalidateQueries({ queryKey: CHAT_KEY });
          }
          break;
        case "notification": {
          const n = msg.notification as AppNotification;
          if (seen.current.has(n.id)) break; // anti-doublon (reconnexion, onglets)
          seen.current.add(n.id);
          qc.setQueryData<NotificationSummary>(SUMMARY_KEY, (d) =>
            d && { unread_count: d.unread_count + 1, recent: [n, ...d.recent.filter((x) => x.id !== n.id)].slice(0, 6) });
          void qc.invalidateQueries({ queryKey: [...NOTIF_KEY, "list"] });
          if (n.type !== "MESSAGE") {
            const link = resolveLegacyLink(n.url);
            toast(n.title, {
              description: n.body || undefined,
              action: link ? {
                label: "Ouvrir",
                onClick: () => (link.kind === "app" ? void navigate(link.to) : window.location.assign(link.href)),
              } : undefined,
            });
          }
          break;
        }
        case "notification.read":
          qc.setQueryData<NotificationSummary>(SUMMARY_KEY, (d) => d && { ...d, unread_count: Number(msg.unread_count ?? 0) });
          void qc.invalidateQueries({ queryKey: NOTIF_KEY });
          break;
        case "chat.activity":
          void qc.invalidateQueries({ queryKey: CONVERSATIONS_KEY });
          void qc.invalidateQueries({ queryKey: SUMMARY_KEY });
          break;
        case "chat.read":
          void qc.invalidateQueries({ queryKey: CONVERSATIONS_KEY });
          break;
      }
    }, { heartbeat: true });
  }, [qc, navigate]);

  // Présence en ligne (même endpoint et cadence que l'ancien frontend).
  useEffect(() => {
    const beat = () => document.visibilityState === "visible" && void api("me/presence/heartbeat/", { method: "POST" }).catch(() => undefined);
    beat();
    const timer = setInterval(beat, PRESENCE_HEARTBEAT_MS);
    return () => clearInterval(timer);
  }, []);

  return null;
}
