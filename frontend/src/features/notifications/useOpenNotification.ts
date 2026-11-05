import { useNavigate } from "react-router";
import { resolveLegacyLink } from "@/lib/links";
import { useMarkRead, type AppNotification } from "./api";

/** Ouvre la ressource liée (route React si migrée, sinon ancienne interface) après marquage « lu ». */
export function useOpenNotification() {
  const navigate = useNavigate();
  const markRead = useMarkRead();
  return (n: AppNotification) => {
    if (!n.is_read) markRead.mutate(n.id);
    const link = resolveLegacyLink(n.url);
    if (link?.kind === "app") void navigate(link.to);
    else if (link?.kind === "legacy") window.location.assign(link.href);
  };
}
