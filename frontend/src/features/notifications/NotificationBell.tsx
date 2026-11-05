import * as Popover from "@radix-ui/react-popover";
import { Bell, CheckCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";
import { useMarkAllRead, useNotificationSummary } from "./api";
import { NotificationItem } from "./NotificationItem";
import { useOpenNotification } from "./useOpenNotification";

export function UnreadBadge({ count, label }: { count: number; label: string }) {
  if (!count) return null;
  return (
    <span aria-label={label} className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-primary px-1 text-[10px] font-bold leading-none text-primary-foreground">
      {count > 99 ? "99+" : count}
    </span>
  );
}

/** Cloche de l'en-tête : compteur non lu temps réel + 6 dernières notifications. */
export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const { data, isPending } = useNotificationSummary();
  const markAll = useMarkAllRead();
  const openNotification = useOpenNotification();
  const unread = data?.unread_count ?? 0;

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <Button variant="ghost" size="icon" className="relative" aria-label={unread ? `Notifications (${unread} non lues)` : "Notifications"}>
          <Bell />
          <UnreadBadge count={unread} label={`${unread} notifications non lues`} />
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="end" sideOffset={8} className="z-50 w-[min(24rem,calc(100vw-1rem))] rounded-2xl border bg-card p-2 shadow-xl">
          <div className="flex items-center justify-between gap-2 px-2 py-1.5">
            <p className="text-sm font-semibold">Notifications</p>
            <Button size="sm" variant="ghost" disabled={!unread || markAll.isPending}
              onClick={() => markAll.mutate(undefined, { onError: (e) => toast.error(e.message) })}>
              <CheckCheck />Tout marquer comme lu
            </Button>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {isPending ? <Skeleton className="m-2 h-40" /> : !data?.recent.length ? (
              <p className="px-3 py-8 text-center text-sm text-muted-foreground">Aucune notification.</p>
            ) : data.recent.map((n) => (
              <NotificationItem key={n.id} n={n} compact onOpen={(x) => { setOpen(false); openNotification(x); }} />
            ))}
          </div>
          <div className="border-t px-2 pt-2">
            <Button variant="outline" size="sm" className="w-full" asChild>
              <Link to="/notifications" onClick={() => setOpen(false)}>Voir toutes les notifications</Link>
            </Button>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
