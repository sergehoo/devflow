import { AlarmClock, Inbox, LayoutGrid, List, ShieldCheck, Timer, UserCheck, UserX } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { toast } from "sonner";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader, Pagination } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { useMe } from "@/features/auth/api";
import { StatCard, WidgetHeader } from "@/features/dashboard/widgets";
import { formatDateTime, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import { useQueryClient } from "@tanstack/react-query";
import { TICKETS_KEY, useConfigList, useTicketDashboard, useTickets, type ExternalApp, type TicketRow } from "./api";
import { PriorityPill, SlaBadge, StatusPill, TicketCard } from "./components";
import { BOARD_STATUSES, CATEGORIES, PRIORITIES, STATUSES, statusMeta } from "./constants";

function SupportNav() {
  return (
    <nav aria-label="Support" className="flex flex-wrap gap-2">
      {([["/tickets", "Ticket Center"], ["/tickets/list", "Tickets"], ["/tickets/applications", "Applications"], ["/tickets/settings", "Routage & SLA"]] as const).map(([to, label]) => (
        <Button key={to} asChild variant="outline" size="sm"><Link to={to}>{label}</Link></Button>
      ))}
    </nav>
  );
}

// ─── Ticket Center (tableau de bord) ─────────────────────────────────────────

export function TicketCenterPage() {
  const { data: me } = useMe();
  const { data, isPending, isError, error, refetch } = useTicketDashboard(me?.workspace?.id);
  if (!me?.workspace) return <EmptyState title="Aucun workspace" />;
  if (isPending) return <PageSkeleton />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;
  const total = Object.values(data.by_status).reduce((a, b) => a + b, 0);
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Support" title="Ticket Center" description="Tickets remontés par les applications connectées : file, SLA et charge des équipes."
        actions={<SupportNav />} />
      <section aria-label="Indicateurs" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard icon={Inbox} value={data.open} unit="ouverts" label="Tickets ouverts" hint={`${data.created_7d} sur 7 j`} to="/tickets/list?open=1" />
        <StatCard icon={UserX} value={data.unassigned} unit="tickets" label="Non assignés" hint="File" to="/tickets/list?open=1&assignee=none" />
        <StatCard icon={AlarmClock} value={data.breached} unit="tickets" label="SLA dépassé" hint={`${data.due_24h} sous 24 h`} to="/tickets/list?breached=1" />
        <StatCard icon={UserCheck} value={data.mine} unit="tickets" label="Pour moi" hint="Voir" to="/tickets/list?open=1&assignee=me" />
      </section>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card className="p-5 sm:p-6">
          <WidgetHeader title="Échéances les plus proches" action={<Link to="/tickets/list?open=1&ordering=due" className="text-xs text-muted-foreground hover:text-foreground">Tout voir</Link>} />
          {data.at_risk.length ? (
            <ul className="mt-3 divide-y">
              {data.at_risk.map((t) => (
                <li key={t.id} className="flex flex-wrap items-center gap-3 py-3">
                  <PriorityPill priority={t.priority} />
                  <Link to={`/tickets/${t.id}`} className="min-w-0 flex-1 truncate text-sm font-medium hover:text-brand">{t.reference} · {t.title}</Link>
                  <span className="text-xs text-muted-foreground">{t.application?.name}</span>
                  <SlaBadge t={t} />
                </li>
              ))}
            </ul>
          ) : <p className="py-8 text-center text-sm text-muted-foreground">Aucun ticket ouvert avec échéance.</p>}
        </Card>
        <div className="space-y-5">
          <Card className="p-5 sm:p-6">
            <WidgetHeader title="Qualité de service" />
            <dl className="mt-3 grid grid-cols-2 gap-3">
              <div className="rounded-2xl bg-gradient-to-br from-primary-soft to-primary-faint p-3.5">
                <dt className="flex items-center gap-1.5 text-xs text-foreground/80"><ShieldCheck className="size-3.5" aria-hidden="true" />SLA respecté (30 j)</dt>
                <dd className="mt-1 text-2xl font-semibold tabular">{data.sla_compliance == null ? "—" : `${data.sla_compliance}%`}</dd>
              </div>
              <div className="rounded-2xl bg-gradient-to-br from-primary-soft to-primary-faint p-3.5">
                <dt className="flex items-center gap-1.5 text-xs text-foreground/80"><Timer className="size-3.5" aria-hidden="true" />1re réponse moy.</dt>
                <dd className="mt-1 text-2xl font-semibold tabular">{data.avg_first_response_minutes == null ? "—" : `${formatNumber(data.avg_first_response_minutes)} min`}</dd>
              </div>
            </dl>
            <p className="mt-3 text-xs text-muted-foreground">{data.resolved_7d} ticket(s) résolu(s) sur 7 jours.</p>
          </Card>
          <Card className="p-5 sm:p-6">
            <WidgetHeader title="Répartition par statut" />
            {total ? (
              <>
                <div className="mt-3 flex h-2.5 overflow-hidden rounded-full bg-hover" aria-hidden="true">
                  {STATUSES.map((s) => (data.by_status[s.value] ? <div key={s.value} className={s.dot} style={{ width: `${(data.by_status[s.value]! / total) * 100}%` }} /> : null))}
                </div>
                <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
                  {STATUSES.filter((s) => data.by_status[s.value]).map((s) => (
                    <li key={s.value} className="flex items-center gap-2">
                      <span className={cn("size-2 rounded-full", s.dot)} aria-hidden="true" /><span className="text-muted-foreground">{s.label}</span>
                      <span className="ml-auto font-semibold tabular">{data.by_status[s.value]}</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : <p className="py-4 text-sm text-muted-foreground">Aucun ticket pour l'instant.</p>}
          </Card>
          <Card className="p-5 sm:p-6">
            <WidgetHeader title="Applications (tickets ouverts)" />
            {data.by_application.length ? (
              <ul className="mt-3 space-y-2 text-sm">
                {data.by_application.map((a) => (
                  <li key={a.id} className="flex items-center justify-between gap-2">
                    <Link to={`/tickets/list?open=1&application=${a.id}`} className="truncate hover:text-brand">{a.name}</Link>
                    <span className="font-semibold tabular">{a.open}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="py-4 text-sm text-muted-foreground">Aucun ticket ouvert.</p>}
          </Card>
        </div>
      </div>
    </div>
  );
}

// ─── Liste + Kanban ──────────────────────────────────────────────────────────

const FILTER_KEYS = ["q", "status", "priority", "category", "application", "assignee", "open", "breached", "ordering", "team", "project"] as const;

export function TicketsPage() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const board = params.get("view") === "board";
  const page = Number(params.get("page") || 1);
  const filters: Record<string, string | number | undefined> = { workspace: me?.workspace?.id, page, page_size: board ? 200 : 25 };
  FILTER_KEYS.forEach((k) => { const v = params.get(k); if (v) filters[k] = v; });
  if (board && !filters.status) filters.status = BOARD_STATUSES.join(",");
  const { data, isPending, isError, error, refetch } = useTickets(filters, Boolean(me?.workspace));
  const apps = useConfigList<ExternalApp>("ticket-applications", me?.workspace?.id);
  const [dragging, setDragging] = useState<TicketRow | null>(null);

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: true });
  };

  const drop = async (status: string) => {
    const t = dragging;
    setDragging(null);
    if (!t || t.status === status) return;
    try {
      await api(`tickets/${t.id}/transition/`, { method: "POST", body: { status } });
      toast.success(`${t.reference} → ${statusMeta(status).label}`);
    } catch (e) {
      toast.error((e as Error).message);
    }
    void qc.invalidateQueries({ queryKey: TICKETS_KEY });
  };

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Support" title="Tickets" description={data ? `${formatNumber(data.count)} ticket(s)` : undefined}
        actions={(
          <div className="flex flex-wrap gap-2">
            <div className="flex rounded-full bg-card p-1 shadow-card dark:border dark:border-border" role="group" aria-label="Affichage">
              <Button size="sm" variant={board ? "ghost" : "default"} onClick={() => set("view", "")} aria-pressed={!board}><List />Liste</Button>
              <Button size="sm" variant={board ? "default" : "ghost"} onClick={() => set("view", "board")} aria-pressed={board}><LayoutGrid />Kanban</Button>
            </div>
            <SupportNav />
          </div>
        )} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <Input aria-label="Rechercher" placeholder="Référence, titre, déclarant…" defaultValue={params.get("q") ?? ""} className="lg:col-span-2"
          onKeyDown={(e) => { if (e.key === "Enter") set("q", (e.target as HTMLInputElement).value.trim()); }}
          onBlur={(e) => set("q", e.target.value.trim())} />
        {!board && (
          <Select aria-label="Statut" value={params.get("status") ?? ""} onChange={(e) => set("status", e.target.value)}>
            <option value="">Statut : tous</option>
            {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </Select>
        )}
        <Select aria-label="Priorité" value={params.get("priority") ?? ""} onChange={(e) => set("priority", e.target.value)}>
          <option value="">Priorité : toutes</option>
          {PRIORITIES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </Select>
        <Select aria-label="Catégorie" value={params.get("category") ?? ""} onChange={(e) => set("category", e.target.value)}>
          <option value="">Catégorie : toutes</option>
          {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </Select>
        <Select aria-label="Application" value={params.get("application") ?? ""} onChange={(e) => set("application", e.target.value)}>
          <option value="">Application : toutes</option>
          {(apps.data?.results ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </Select>
        <Select aria-label="Affectation" value={params.get("assignee") ?? ""} onChange={(e) => set("assignee", e.target.value)}>
          <option value="">Affectation : toutes</option>
          <option value="me">Mes tickets</option>
          <option value="none">Non assignés</option>
        </Select>
      </div>

      {isPending ? <PageSkeleton /> : isError ? <ErrorState message={error.message} onRetry={() => void refetch()} /> : !data.results.length ? (
        <EmptyState title="Aucun ticket" description="Aucun ticket ne correspond à ces filtres." />
      ) : board ? (
        <div className="flex gap-4 overflow-x-auto pb-2">
          {BOARD_STATUSES.map((status) => {
            const items = data.results.filter((t) => t.status === status);
            return (
              <section key={status} aria-label={statusMeta(status).label} onDragOver={(e) => e.preventDefault()} onDrop={() => void drop(status)}
                className="w-72 shrink-0 rounded-[22px] bg-muted/70 p-3 dark:bg-muted">
                <h2 className="mb-3 flex items-center gap-2 px-1 text-sm font-semibold">
                  <span className={cn("size-2 rounded-full", statusMeta(status).dot)} aria-hidden="true" />{statusMeta(status).label}
                  <span className="ml-auto text-xs text-muted-foreground">{items.length}</span>
                </h2>
                <div className="space-y-2.5">
                  {items.map((t) => <TicketCard key={t.id} t={t} draggable onDragStart={() => setDragging(t)} />)}
                </div>
              </section>
            );
          })}
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-[22px] bg-card shadow-card dark:border dark:border-border">
            <table className="w-full min-w-[860px] text-sm">
              <caption className="sr-only">Tickets</caption>
              <thead className="border-b bg-muted text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                <tr>{["Ticket", "Application", "Statut", "Priorité", "Équipe / agent", "SLA", "Créé"].map((h) => <th key={h} scope="col" className="px-4 py-3 font-semibold">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y">
                {data.results.map((t) => (
                  <tr key={t.id} className="hover:bg-hover">
                    <td className="max-w-[320px] px-4 py-3">
                      <Link to={`/tickets/${t.id}`} className="block truncate font-medium hover:text-brand">{t.title}</Link>
                      <span className="text-xs text-muted-foreground">{t.reference} · {t.category_label}{t.reporter_name ? ` · ${t.reporter_name}` : ""}</span>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{t.application?.name}</td>
                    <td className="px-4 py-3"><StatusPill status={t.status} label={t.status_label} /></td>
                    <td className="px-4 py-3"><PriorityPill priority={t.priority} /></td>
                    <td className="px-4 py-3 text-xs"><span className="block">{t.team?.name ?? "Non assigné"}</span><span className="text-muted-foreground">{t.assignee?.name ?? "—"}</span></td>
                    <td className="px-4 py-3"><SlaBadge t={t} /></td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">{formatDateTime(t.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} count={data.count} onPage={(p) => set("page", String(p))} />
        </>
      )}
    </div>
  );
}

/** Tickets d'un projet (fiche projet). */
export function ProjectTickets({ projectId }: { projectId: number }) {
  const { data, isPending } = useTickets({ project: projectId, page_size: 5, ordering: "updated" });
  if (isPending || !data?.count) return null;
  return (
    <Card className="p-5 sm:p-6">
      <WidgetHeader title="Tickets" meta={`${data.count} au total`} action={<Link to={`/tickets/list?project=${projectId}`} className="text-xs text-muted-foreground hover:text-foreground">Tout voir</Link>} />
      <ul className="mt-3 divide-y">
        {data.results.map((t) => (
          <li key={t.id} className="flex flex-wrap items-center gap-3 py-2.5">
            <PriorityPill priority={t.priority} />
            <Link to={`/tickets/${t.id}`} className="min-w-0 flex-1 truncate text-sm font-medium hover:text-brand">{t.reference} · {t.title}</Link>
            <StatusPill status={t.status} label={t.status_label} />
          </li>
        ))}
      </ul>
    </Card>
  );
}
