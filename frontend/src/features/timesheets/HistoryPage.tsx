import { useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, Pencil, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { LegacyForm } from "@/components/forms/LegacyForm";
import { PageHeader, Pagination } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/input";
import { Badge, Skeleton } from "@/components/ui/misc";
import { DownloadButton } from "@/features/meetings/DownloadButton";
import { formatDate, formatHours } from "@/lib/format";
import { useDebouncedValue } from "@/lib/hooks";
import { TS_KEY, timesheetExportUrl, useDeleteEntry, useEntries, weekPath, type Breakdown } from "./api";
import { APPROVAL_STATUSES, STATUS_TONE, statusLabel } from "./constants";
import { TimesheetTabs } from "./TimesheetNav";

const EMPTY = { search: "", date_from: "", date_to: "", user: "", project: "", approval_status: "", is_billable: "", page: 1 };

function Bars({ title, items }: { title: string; items: Breakdown[] }) {
  const max = Math.max(1, ...items.map((i) => i.hours));
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent>
        {items.length === 0 ? <p className="text-sm text-muted-foreground">Aucune donnée.</p> : (
          <ul className="space-y-2.5 text-sm">
            {items.map((i) => (
              <li key={`${i.id}`}>
                <div className="flex justify-between gap-3"><span className="truncate">{i.name}</span><span className="shrink-0 font-semibold tabular-nums">{formatHours(i.hours)}</span></div>
                <div className="mt-1 flex h-1.5 overflow-hidden rounded-full bg-muted" title={`${formatHours(i.billable_hours)} facturables`}>
                  <div className="bg-primary" style={{ width: `${(i.billable_hours / max) * 100}%` }} />
                  <div className="bg-primary/30" style={{ width: `${((i.hours - i.billable_hours) / max) * 100}%` }} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/** Historique des saisies visibles (soi + subordonnés), filtres, totaux facturable / non facturable. */
export function HistoryPage() {
  const qc = useQueryClient();
  const [f, setF] = useState(EMPTY);
  const search = useDebouncedValue(f.search);
  const { data, isPending, isError, error, refetch } = useEntries({ ...f, search });
  const del = useDeleteEntry();
  const [editing, setEditing] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const set = (patch: Partial<typeof EMPTY>) => setF((x) => ({ ...x, page: 1, ...patch }));

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Timesheets" title="Historique des saisies" description="Vos saisies et celles de vos collaborateurs (N-1, N-2…)."
        actions={<DownloadButton href={timesheetExportUrl({ ...f, search })} filename="Timesheets.xlsx"><FileSpreadsheet aria-hidden="true" />Exporter en Excel</DownloadButton>} />
      <TimesheetTabs />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="relative sm:col-span-2">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden="true" />
          <Input type="search" className="pl-9" placeholder="Description, projet, tâche, collaborateur…" aria-label="Rechercher" value={f.search} onChange={(e) => set({ search: e.target.value })} />
        </div>
        <Input type="date" aria-label="Du" value={f.date_from} onChange={(e) => set({ date_from: e.target.value })} />
        <Input type="date" aria-label="Au" value={f.date_to} onChange={(e) => set({ date_to: e.target.value })} />
        <Select aria-label="Collaborateur" value={f.user} onChange={(e) => set({ user: e.target.value })}>
          <option value="">Collaborateur : tous</option>{data?.collaborators.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
        </Select>
        <Select aria-label="Projet" value={f.project} onChange={(e) => set({ project: e.target.value })}>
          <option value="">Projet : tous</option>{data?.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </Select>
        <Select aria-label="Statut" value={f.approval_status} onChange={(e) => set({ approval_status: e.target.value })}>
          <option value="">Statut : tous</option>{APPROVAL_STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </Select>
        <Select aria-label="Facturable" value={f.is_billable} onChange={(e) => set({ is_billable: e.target.value })}>
          <option value="">Facturable : tous</option><option value="true">Facturable</option><option value="false">Non facturable</option>
        </Select>
      </div>

      {isPending ? <Skeleton className="h-96" /> : isError ? <ErrorState message={error.message} onRetry={() => void refetch()} /> : (
        <>
          <section aria-label="Totaux" className="grid gap-3 sm:grid-cols-3">
            {([["Total", data.totals.hours], ["Facturable", data.totals.billable_hours], ["Non facturable", data.totals.non_billable_hours]] as const).map(([k, v]) => (
              <Card key={k}><CardContent className="py-4"><p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{k}</p><p className="mt-1 font-serif text-xl font-semibold tabular-nums">{formatHours(v)}</p></CardContent></Card>
            ))}
          </section>
          <div className="grid gap-4 lg:grid-cols-2">
            <Bars title="Par collaborateur" items={data.totals.by_user} />
            <Bars title="Par projet" items={data.totals.by_project} />
          </div>

          {data.results.length === 0 ? <EmptyState title="Aucune saisie" description="Aucune saisie ne correspond à ces critères." /> : (
            <div className="overflow-x-auto rounded-[22px] border border-transparent bg-card shadow-card dark:border-border">
              <table className="w-full min-w-[860px] text-sm">
                <caption className="sr-only">Saisies de temps</caption>
                <thead className="border-b bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>{["Date", "Collaborateur", "Projet", "Tâche / description", "Heures", "Facturable", "Statut", ""].map((h) => <th key={h} scope="col" className="px-4 py-3 font-semibold">{h}</th>)}</tr>
                </thead>
                <tbody className="divide-y">
                  {data.results.map((e) => (
                    <tr key={e.id} className="hover:bg-muted/40">
                      <td className="px-4 py-2.5 whitespace-nowrap">{formatDate(e.entry_date)}</td>
                      <td className="px-4 py-2.5">
                        <Link to={weekPath(e.entry_date, e.user.id)} className="hover:text-brand" title="Ouvrir la feuille de temps de la semaine">{e.user.name}</Link>
                      </td>
                      <td className="px-4 py-2.5">{e.project?.name ?? "—"}</td>
                      <td className="max-w-72 px-4 py-2.5">{e.task ? <Link to={`/tasks/${e.task.id}`} className="hover:text-brand">{e.task.title}</Link> : <span className="line-clamp-2">{e.description || "—"}</span>}</td>
                      <td className="px-4 py-2.5 font-semibold tabular-nums">{e.hours}</td>
                      <td className="px-4 py-2.5">{e.is_billable ? "Oui" : "Non"}</td>
                      <td className="px-4 py-2.5"><Badge className={STATUS_TONE[e.approval_status]}>{statusLabel(e.approval_status, e.approval_status_label)}</Badge></td>
                      <td className="px-4 py-2.5 text-right">
                        {e.can_edit && (
                          <span className="inline-flex gap-1">
                            <Button size="icon" variant="ghost" aria-label="Modifier la saisie" onClick={() => setEditing(e.id)}><Pencil /></Button>
                            <Button size="icon" variant="ghost" aria-label="Supprimer la saisie" onClick={() => setDeleting(e.id)}><Trash2 /></Button>
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pagination page={f.page} count={data.count} onPage={(page) => setF((x) => ({ ...x, page }))} />
        </>
      )}

      <Dialog open={editing !== null} onOpenChange={(o) => !o && setEditing(null)} title="Modifier la saisie" className="sm:max-w-2xl">
        {editing !== null && (
          <LegacyForm name="timesheet-entry" id={editing} onCancel={() => setEditing(null)}
            onSuccess={() => { toast.success("Saisie mise à jour."); setEditing(null); void qc.invalidateQueries({ queryKey: TS_KEY }); }} />
        )}
      </Dialog>
      <ConfirmDialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)} destructive pending={del.isPending}
        title="Supprimer cette saisie ?" description="Les heures seront retirées de votre semaine." confirmLabel="Supprimer"
        onConfirm={() => deleting !== null && del.mutate(deleting, {
          onSuccess: () => { toast.success("Saisie supprimée."); setDeleting(null); },
          onError: (e) => { toast.error(e.message); setDeleting(null); },
        })} />
    </div>
  );
}
