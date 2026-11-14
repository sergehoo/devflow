import { Eye, FileSpreadsheet } from "lucide-react";
import { Link, useSearchParams } from "react-router";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { PageHeader, Pagination } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Badge, Skeleton } from "@/components/ui/misc";
import { DownloadButton } from "@/features/meetings/DownloadButton";
import { formatDate, formatHours } from "@/lib/format";
import { timesheetExportUrl, useWeeks, weekExportUrl, weekPath } from "./api";
import { APPROVAL_STATUSES, STATUS_TONE, statusLabel } from "./constants";
import { TimesheetTabs } from "./TimesheetNav";

const FILTERS = ["user", "status", "date_from", "date_to"] as const;
type Filter = (typeof FILTERS)[number];

/**
 * Feuilles de temps hebdomadaires de ses collaborateurs (N-1, N-2…) et des siennes, tous statuts
 * confondus : une semaine validée reste consultable et exportable. Le périmètre est appliqué par Django.
 */
export function SheetsPage() {
  const [params, setParams] = useSearchParams();
  const f = Object.fromEntries(FILTERS.map((k) => [k, params.get(k) ?? ""])) as Record<Filter, string>;
  const page = Number(params.get("page") ?? 1) || 1;
  const { data, isPending, isError, error, refetch } = useWeeks({ ...f, page });
  const set = (patch: Partial<Record<Filter | "page", string>>) => setParams((p) => {
    if (!("page" in patch)) p.delete("page");
    Object.entries(patch).forEach(([k, v]) => (v ? p.set(k, v) : p.delete(k)));
    return p;
  }, { replace: true });
  const exportUrl = timesheetExportUrl({ user: f.user, approval_status: f.status, date_from: f.date_from, date_to: f.date_to });

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Timesheets" title="Feuilles de temps"
        description="Les semaines de vos collaborateurs (N-1, N-2…) et les vôtres, y compris celles déjà validées. Ouvrez-les ou exportez-les en Excel."
        actions={<DownloadButton href={exportUrl} filename="Timesheets.xlsx"><FileSpreadsheet aria-hidden="true" />Exporter en Excel</DownloadButton>} />
      <TimesheetTabs />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Select aria-label="Collaborateur" value={f.user} onChange={(e) => set({ user: e.target.value })}>
          <option value="">Collaborateur : tous</option>{data?.collaborators?.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
        </Select>
        <Select aria-label="Statut" value={f.status} onChange={(e) => set({ status: e.target.value })}>
          <option value="">Statut : tous</option>{APPROVAL_STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </Select>
        <Input type="date" aria-label="Semaines à partir du" value={f.date_from} onChange={(e) => set({ date_from: e.target.value })} />
        <Input type="date" aria-label="Semaines jusqu'au" value={f.date_to} onChange={(e) => set({ date_to: e.target.value })} />
      </div>

      {isPending ? <Skeleton className="h-72" /> : isError ? <ErrorState message={error.message} onRetry={() => void refetch()} /> : data.results.length === 0 ? (
        <EmptyState title="Aucune feuille de temps" description="Aucune semaine ne correspond à ces critères." />
      ) : (
        <>
          <div className="overflow-x-auto rounded-[22px] border border-transparent bg-card shadow-card dark:border-border">
            <table className="w-full min-w-[820px] text-sm">
              <caption className="sr-only">Feuilles de temps hebdomadaires</caption>
              <thead className="border-b bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>{["Collaborateur", "Semaine", "Heures", "Saisies", "Statut", ""].map((h) => <th key={h} scope="col" className="px-4 py-3 font-semibold">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y">
                {data.results.map((g) => (
                  <tr key={`${g.user.id}-${g.monday}`} className="hover:bg-muted/40">
                    <td className="px-4 py-2.5 font-medium">
                      <Link to={weekPath(g.monday, g.user.id)} className="hover:text-brand">{g.user.name}</Link>
                      {g.is_mine && <Badge className="ml-2">Moi</Badge>}
                    </td>
                    <td className="px-4 py-2.5 whitespace-nowrap">S{g.iso_week} · {formatDate(g.monday)} → {formatDate(g.sunday)}</td>
                    <td className="px-4 py-2.5 font-semibold tabular-nums">{formatHours(g.total_hours)}</td>
                    <td className="px-4 py-2.5 tabular-nums">{g.entry_count}</td>
                    <td className="px-4 py-2.5"><Badge className={STATUS_TONE[g.status]}>{statusLabel(g.status, g.status_label)}</Badge></td>
                    <td className="px-4 py-2.5">
                      <span className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" asChild>
                          <Link to={weekPath(g.monday, g.user.id)} aria-label={`Voir la semaine ${g.iso_week} de ${g.user.name}`}><Eye />Voir</Link>
                        </Button>
                        <DownloadButton href={weekExportUrl(g.monday, g.user.id)} filename={`Timesheet_S${g.iso_week}.xlsx`} variant="ghost" size="sm">
                          <FileSpreadsheet aria-hidden="true" /><span className="sr-only">Exporter la semaine {g.iso_week} de {g.user.name} en</span> Excel
                        </DownloadButton>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} count={data.count} onPage={(p) => set({ page: String(p) })} />
        </>
      )}
    </div>
  );
}
