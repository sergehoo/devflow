import { CheckCheck, Search, Settings2, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { PageHeader, Pagination } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { useDebouncedValue } from "@/lib/hooks";
import { useDeleteNotification, useMarkAllRead, useNotifications } from "./api";
import { NotificationItem } from "./NotificationItem";
import { useOpenNotification } from "./useOpenNotification";

const TABS = [["", "Toutes"], ["unread", "Non lues"], ["read", "Lues"]] as const;

/** Centre de notifications : mêmes données et règles que /notifications/ (destinataire uniquement). */
export function NotificationsPage() {
  const [f, setF] = useState({ status: "", type: "", q: "", page: 1 });
  const q = useDebouncedValue(f.q);
  const { data, isPending, isError, error, refetch } = useNotifications({ ...f, q });
  const markAll = useMarkAllRead();
  const del = useDeleteNotification();
  const openNotification = useOpenNotification();
  const set = (patch: Partial<typeof f>) => setF((x) => ({ ...x, page: 1, ...patch }));
  const counts: Record<string, number | undefined> = { "": data?.total_count, unread: data?.unread_count, read: data?.read_count };

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Collaboration" title="Notifications"
        description={data ? `${data.unread_count} non lue(s) sur ${data.total_count}` : undefined}
        actions={<>
          <Button variant="outline" asChild><Link to="/notifications/preferences"><Settings2 />Préférences</Link></Button>
          <Button disabled={!data?.unread_count || markAll.isPending}
            onClick={() => markAll.mutate(undefined, { onSuccess: () => toast.success("Toutes les notifications ont été marquées comme lues."), onError: (e) => toast.error(e.message) })}>
            <CheckCheck />Tout marquer comme lu
          </Button>
        </>} />

      <div className="flex flex-wrap items-center gap-3">
        <div role="tablist" aria-label="Filtrer par état" className="flex rounded-xl border bg-card p-1">
          {TABS.map(([v, l]) => (
            <Button key={v} role="tab" aria-selected={f.status === v} size="sm" variant={f.status === v ? "default" : "ghost"} onClick={() => set({ status: v })}>
              {l}{counts[v] !== undefined && <span className="ml-1 tabular-nums opacity-70">{counts[v]}</span>}
            </Button>
          ))}
        </div>
        <Select aria-label="Type" className="w-48" value={f.type} onChange={(e) => set({ type: e.target.value })}>
          <option value="">Type : tous</option>
          {data?.types.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </Select>
        <div className="relative min-w-56 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden="true" />
          <Input type="search" className="pl-9" placeholder="Rechercher…" aria-label="Rechercher une notification" value={f.q} onChange={(e) => set({ q: e.target.value })} />
        </div>
      </div>

      {isPending ? <Skeleton className="h-96" /> : isError ? <ErrorState message={error.message} onRetry={() => void refetch()} /> : data.results.length === 0 ? (
        <EmptyState title="Aucune notification" description="Rien ne correspond à ces critères." />
      ) : (
        <>
          <ul className="divide-y rounded-2xl border bg-card p-1">
            {data.results.map((n) => (
              <li key={n.id} className="group flex items-center gap-1">
                <div className="min-w-0 flex-1"><NotificationItem n={n} onOpen={openNotification} /></div>
                <Button size="icon" variant="ghost" className="mr-1 opacity-60 group-hover:opacity-100" aria-label={`Supprimer « ${n.title} »`}
                  disabled={del.isPending} onClick={() => del.mutate(n.id, { onError: (e) => toast.error(e.message) })}>
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
          <Pagination page={f.page} count={data.count} onPage={(page) => setF((x) => ({ ...x, page }))} />
        </>
      )}
    </div>
  );
}
