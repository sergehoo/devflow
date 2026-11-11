/**
 * Pilotage › Suivi Pôle Développement.
 * Vue consolidée (lecture seule) des projets et activités : remplace le classeur Excel
 * de suivi. Les lignes, indicateurs et filtres sont calculés par Django sur le périmètre
 * RBAC de l'utilisateur ; l'écran ne stocke aucune donnée propre.
 */
import { ChevronDown, ChevronRight, FileDown, FileUp, Search, Sparkles } from "lucide-react";
import { Fragment, useMemo, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import { toast } from "sonner";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader, Pagination } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { useMe } from "@/features/auth/api";
import { DownloadButton } from "@/features/meetings/DownloadButton";
import { ActionBar, Pill } from "@/features/projet/ui";
import { formatDate, formatDateTime } from "@/lib/format";
import { useDebouncedValue } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import {
  filtersFrom, trackingExportUrl, useAiBrief, useTrackingBoard, useTrackingBrief,
  type ExportVariant, type FilterKey, type TrackingBoard, type TrackingFilters, type TrackingRow,
} from "./api";
import { ExportTrackingButton } from "./ExportTrackingButton";
import { alertTone, STATUS_TONE } from "./format";
import { Progress, RowDetail } from "./ui";

const PAGE_SIZE = 25;

const STATUS_BAR: Record<string, string> = { en_cours: "bg-info", suspendu: "bg-warning", realise: "bg-success", annule: "bg-muted-foreground/40" };
const SEVERITY_BAR: Record<string, string> = {
  CRITICAL: "bg-destructive", HIGH: "bg-warning", MEDIUM: "bg-info", LOW: "bg-subtle-foreground", DECISION: "bg-primary",
};

/** Tranches d'avancement proposées (valeur « min-max »). */
const PROGRESS_RANGES = [["0-0", "Non démarré (0 %)"], ["1-49", "1 à 49 %"], ["50-99", "50 à 99 %"], ["100-100", "Terminé (100 %)"]] as const;

const REPORTS: [ExportVariant, string][] = [["direction", "Rapport Direction"], ["weekly", "Rapport hebdomadaire"], ["monthly", "Rapport mensuel"]];

function Kpi({ label, value, hint, tone, active, onClick }: {
  label: string; value: ReactNode; hint?: string; tone?: "danger" | "warning" | "success"; active?: boolean; onClick?: () => void;
}) {
  const body = (
    <>
      <p className="truncate text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={cn("mt-1 font-serif text-2xl font-semibold leading-tight tabular-nums",
        tone === "danger" && "text-destructive", tone === "warning" && "text-warning", tone === "success" && "text-success")}>{value}</p>
      {hint && <p className="mt-0.5 truncate text-xs text-muted-foreground">{hint}</p>}
    </>
  );
  const frame = cn("min-w-0 rounded-[22px] border bg-card p-4 text-left shadow-card", active ? "border-primary" : "border-transparent dark:border-border");
  return onClick ? (
    <button type="button" aria-pressed={!!active} onClick={onClick} className={cn(frame, "transition-colors hover:bg-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary")}>{body}</button>
  ) : <div className={frame}>{body}</div>;
}

function BarList({ title, items }: { title: string; items: { label: string; value: number; color?: string }[] }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  const empty = items.every((i) => !i.value);
  return (
    <Card className="min-w-0">
      <CardHeader><CardTitle className="text-sm">{title}</CardTitle></CardHeader>
      <CardContent>
        {empty ? <p className="text-sm text-muted-foreground">Aucune donnée sur ce périmètre.</p> : (
          <ul className="space-y-2.5">
            {items.map((i) => (
              <li key={i.label} className="grid grid-cols-[minmax(0,8.5rem)_1fr_2.25rem] items-center gap-2 text-sm">
                <span className="truncate text-muted-foreground" title={i.label}>{i.label}</span>
                <span className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                  <span className={cn("block h-full rounded-full", i.color ?? "bg-primary")} style={{ width: `${(i.value / max) * 100}%` }} />
                </span>
                <span className="text-right font-semibold tabular-nums">{i.value}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function Workload({ items }: { items: TrackingBoard["charts"]["workload"] }) {
  const max = Math.max(1, ...items.map((i) => i.projects + i.tasks));
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="text-sm">Charge par responsable</CardTitle>
        <p className="flex gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-primary" aria-hidden="true" />Projets</span>
          <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-info" aria-hidden="true" />Activités</span>
        </p>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? <p className="text-sm text-muted-foreground">Aucun élément ouvert.</p> : (
          <ul className="space-y-2.5">
            {items.map((i) => (
              <li key={i.label} className="grid grid-cols-[minmax(0,8.5rem)_1fr_2.25rem] items-center gap-2 text-sm">
                <span className="truncate text-muted-foreground" title={i.label}>{i.label}</span>
                <span className="flex h-2 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                  <span className="h-full bg-primary" style={{ width: `${(i.projects / max) * 100}%` }} />
                  <span className="h-full bg-info" style={{ width: `${(i.tasks / max) * 100}%` }} />
                </span>
                <span className="text-right font-semibold tabular-nums" title={`${i.projects} projet(s), ${i.tasks} activité(s)`}>{i.projects + i.tasks}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function Brief({ filters }: { filters: TrackingFilters }) {
  const { data: me } = useMe();
  const brief = useTrackingBrief(filters);
  const ai = useAiBrief(filters);
  const shown = ai.data ?? brief.data;
  if (brief.isPending) return null;
  if (!shown) return null;
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>Points d'attention</CardTitle>
          <p className="text-xs text-muted-foreground">
            {shown.source === "ai" ? "Reformulé par l'IA DevFlow à partir des constats ci-dessous." : "Constats calculés sur les données DevFlow affichées."}
          </p>
        </div>
        {can(me?.permissions, "ai.summarize") && shown.facts.length > 0 && (
          <Button variant="outline" size="sm" disabled={ai.isPending} aria-busy={ai.isPending}
            onClick={() => ai.mutate(undefined, { onError: (e) => toast.error(e.message) })}>
            <Sparkles aria-hidden="true" />{ai.isPending ? "Synthèse en cours…" : "Synthèse IA"}
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {shown.source === "ai" && <p className="whitespace-pre-line rounded-2xl bg-primary/5 p-4 text-sm leading-relaxed">{shown.text}</p>}
        {shown.facts.length === 0 ? (
          <p className="text-sm text-muted-foreground">Aucun point d'attention sur ce périmètre.</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {shown.facts.map((f) => (
              <li key={f.kind} className="flex gap-2"><span className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />{f.text}</li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function Late({ row }: { row: TrackingRow }) {
  if (row.late) return <Pill tone="danger">{row.days_late} j</Pill>;
  if (row.due_soon) return <Pill tone="warning">Proche</Pill>;
  return <span className="text-muted-foreground">—</span>;
}

const first = (texts: string[]) => texts[0] ?? "";

function BoardTable({ rows }: { rows: TrackingRow[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="overflow-x-auto rounded-[22px] border border-transparent bg-card shadow-card dark:border-border">
      <table className="w-full min-w-[1180px] text-sm">
        <caption className="sr-only">Suivi consolidé des projets et activités</caption>
        <thead className="border-b bg-muted text-left text-[11px] uppercase tracking-wider text-muted-foreground">
          <tr>
            <th scope="col" className="w-9 px-2 py-3"><span className="sr-only">Détail</span></th>
            {["Entreprise", "Projet / activité", "Porteur", "Interlocuteurs", "Avancement", "Statut", "Début", "Échéance",
              "Actions réalisées", "Prochaines actions", "Alertes / décisions", "Retard"].map((h) => (
              <th key={h} scope="col" className="px-3 py-3 font-semibold">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((r) => {
            const expanded = open === r.id;
            return (
              <Fragment key={r.id}>
                <tr className={cn("align-top hover:bg-hover", expanded && "bg-hover")}>
                  <td className="px-2 py-3">
                    <Button variant="ghost" size="icon" className="size-7" aria-expanded={expanded}
                      aria-label={`${expanded ? "Masquer" : "Afficher"} le détail de ${r.title}`} onClick={() => setOpen(expanded ? null : r.id)}>
                      {expanded ? <ChevronDown /> : <ChevronRight />}
                    </Button>
                  </td>
                  <td className="px-3 py-3">{r.companies.length ? r.companies.join(", ") : <span className="text-muted-foreground">—</span>}</td>
                  <td className="max-w-[18rem] px-3 py-3">
                    <Link to={r.url} className="font-medium hover:text-brand">{r.title}</Link>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {r.kind === "project" ? "Projet" : `Activité · ${r.project.name}`}
                    </p>
                  </td>
                  <td className="px-3 py-3">{r.owners.length ? r.owners.map((o) => o.name).join(", ") : <span className="text-muted-foreground">Non attribué</span>}</td>
                  <td className="max-w-[12rem] px-3 py-3 text-muted-foreground">{r.contacts.join(", ") || "—"}</td>
                  <td className="w-32 px-3 py-3"><Progress value={r.progress} label={`Avancement de ${r.title}`} /></td>
                  <td className="px-3 py-3"><Pill tone={STATUS_TONE[r.status_key]}>{r.sheet_status}</Pill></td>
                  <td className="whitespace-nowrap px-3 py-3">{formatDate(r.start)}</td>
                  <td className={cn("whitespace-nowrap px-3 py-3", r.late && "font-semibold text-destructive")}>{formatDate(r.end)}</td>
                  <td className="max-w-[14rem] px-3 py-3">
                    <span className="font-semibold tabular-nums">{r.done_count}</span>
                    {r.done_count > 0 && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{r.done[r.done.length - 1]?.text}</p>}
                  </td>
                  <td className="max-w-[14rem] px-3 py-3">
                    <span className="font-semibold tabular-nums">{r.next_count}</span>
                    {r.next_count > 0 && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{first(r.next.map((n) => n.text))}</p>}
                  </td>
                  <td className="max-w-[14rem] px-3 py-3">
                    {r.alerts.length === 0 ? <span className="text-muted-foreground">—</span> : (
                      <div className="flex flex-wrap gap-1">
                        {r.alerts.slice(0, 2).map((a) => <Pill key={`${a.type}-${a.id}`} tone={alertTone(a)}>{a.kind_label}</Pill>)}
                        {r.alerts.length > 2 && <Pill>+{r.alerts.length - 2}</Pill>}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-3"><Late row={r} /></td>
                </tr>
                {expanded && (
                  <tr className="bg-muted/40">
                    <td colSpan={13} className="px-5 py-4">
                      <RowDetail row={r} />
                      <p className="mt-4 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                        <Button variant="outline" size="sm" asChild><Link to={r.url}>Ouvrir la fiche</Link></Button>
                        {r.stale && <span>Aucune mise à jour récente.</span>}
                        {r.updated_at && <span>Mis à jour le {formatDateTime(r.updated_at)}</span>}
                      </p>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function PilotagePage() {
  const [search, setSearch] = useSearchParams();
  const [q, setQ] = useState(() => search.get("q") ?? "");
  const [page, setPage] = useState(1);
  const debounced = useDebouncedValue(q);
  // Les filtres vivent dans l'URL (lien partageable) ; la recherche est saisie localement.
  const filters = useMemo<TrackingFilters>(() => {
    const f = filtersFrom(search);
    delete f.q;
    return debounced.trim() ? { ...f, q: debounced.trim() } : f;
  }, [search, debounced]);
  const board = useTrackingBoard(filters);

  const set = (patch: Partial<Record<FilterKey, string>>) => {
    setPage(1);
    setSearch((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("q");
      Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
      return next;
    }, { replace: true });
  };
  const toggle = (patch: Partial<Record<FilterKey, string>>) => {
    const on = Object.entries(patch).every(([k, v]) => filters[k as FilterKey] === v);
    set(on ? Object.fromEntries(Object.keys(patch).map((k) => [k, ""])) : patch);
  };
  const reset = () => { setQ(""); setPage(1); setSearch(new URLSearchParams(), { replace: true }); };
  const active = Object.keys(filters).length > 0;

  if (board.isPending) return <PageSkeleton />;
  if (board.isError) return <ErrorState message={board.error.message} onRetry={() => void board.refetch()} />;
  const data = board.data;
  const { kpis: k, charts, options } = data;
  const pages = Math.max(1, Math.ceil(data.rows.length / PAGE_SIZE));
  const current = Math.min(page, pages);
  const visible = data.rows.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);
  const progressValue = filters.progress_min || filters.progress_max ? `${filters.progress_min ?? 0}-${filters.progress_max ?? 100}` : "";
  const is = (patch: Partial<Record<FilterKey, string>>) => Object.entries(patch).every(([key, v]) => filters[key as FilterKey] === v);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Pilotage"
        title="Suivi Pôle Développement"
        description={`Périmètre : ${data.scope.label} · ${data.count} ligne(s) sur ${data.total}`}
        actions={<>
          {data.can_import && <Button variant="outline" asChild><Link to="/imports/tracking"><FileUp />Importer le suivi</Link></Button>}
          <ExportTrackingButton filters={filters} variant="default" />
        </>}
      />

      <section aria-label="Indicateurs clés" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <Kpi label="Projets actifs" value={k.projects_active} hint={`${k.projects_total} projet(s) au total`}
          active={is({ section: "projects", status: "en_cours" })} onClick={() => toggle({ section: "projects", status: "en_cours" })} />
        <Kpi label="Réalisés" value={k.projects_done} tone="success"
          active={is({ section: "projects", status: "realise" })} onClick={() => toggle({ section: "projects", status: "realise" })} />
        <Kpi label="Suspendus" value={k.projects_suspended} tone={k.projects_suspended ? "warning" : undefined}
          active={is({ section: "projects", status: "suspendu" })} onClick={() => toggle({ section: "projects", status: "suspendu" })} />
        <Kpi label="En retard" value={k.projects_late} tone={k.projects_late ? "danger" : undefined}
          active={is({ section: "projects", late: "1" })} onClick={() => toggle({ section: "projects", late: "1" })} />
        <Kpi label="Échéances proches" value={k.due_soon} hint="Sous 7 jours" tone={k.due_soon ? "warning" : undefined} />
        <Kpi label="Avancement moyen" value={`${k.progress_avg} %`} hint="Projets non annulés" />
        <Kpi label="Projets bloqués" value={k.projects_blocked} tone={k.projects_blocked ? "danger" : undefined}
          active={is({ section: "projects", alert: "BLOCKER" })} onClick={() => toggle({ section: "projects", alert: "BLOCKER" })} />
        <Kpi label="Décisions en attente" value={k.pending_decisions} tone={k.pending_decisions ? "warning" : undefined}
          active={is({ alert: "DECISION" })} onClick={() => toggle({ alert: "DECISION" })} />
        <Kpi label="Tâches ouvertes" value={k.tasks_open} hint={`${k.activities_total} activité(s) suivie(s)`} />
        <Kpi label="Tâches en retard" value={k.tasks_late} tone={k.tasks_late ? "danger" : undefined} />
      </section>

      <Brief filters={filters} />

      <section aria-label="Répartitions" className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <BarList title="Projets par entreprise" items={charts.by_company} />
        <BarList title="Projets par statut" items={charts.by_status.map((s) => ({ ...s, color: STATUS_BAR[s.key ?? ""] }))} />
        <BarList title="Avancement des projets" items={charts.progress} />
        <BarList title="Échéances à venir" items={charts.deadlines.map((d) => ({ ...d, color: d.label === "En retard" ? "bg-destructive" : undefined }))} />
        <Workload items={charts.workload} />
        <BarList title="Alertes par criticité" items={charts.alerts.map((a) => ({ ...a, color: SEVERITY_BAR[a.key ?? ""] }))} />
      </section>

      <ActionBar title="Rapports" description="Générés depuis DevFlow sur votre périmètre, avec les filtres actifs.">
        {REPORTS.map(([variant, label]) => (
          <DownloadButton key={variant} size="sm" href={trackingExportUrl(filters, "pdf", variant)} filename={`Suivi_Pole_Developpement_${variant}.pdf`}>
            <FileDown aria-hidden="true" />{label}
          </DownloadButton>
        ))}
      </ActionBar>

      <section aria-label="Filtres" className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
          <div className="relative sm:col-span-2">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden="true" />
            <Input type="search" className="pl-9" placeholder="Projet, porteur, action, alerte…" aria-label="Rechercher dans le suivi"
              value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          </div>
          <Select aria-label="Bloc" value={filters.section ?? ""} onChange={(e) => set({ section: e.target.value })}>
            <option value="">Projets et activités</option>
            <option value="projects">Projets</option>
            <option value="tasks">Activités</option>
          </Select>
          <Select aria-label="Entreprise" value={filters.company ?? ""} onChange={(e) => set({ company: e.target.value })}>
            <option value="">Entreprise : toutes</option>
            {options.companies.map((c) => <option key={c} value={c}>{c}</option>)}
            <option value="aucune">Sans entreprise</option>
          </Select>
          <Select aria-label="Projet" value={filters.project ?? ""} onChange={(e) => set({ project: e.target.value })}>
            <option value="">Projet : tous</option>
            {options.projects.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </Select>
          <Select aria-label="Porteur" value={filters.owner ?? ""} onChange={(e) => set({ owner: e.target.value })}>
            <option value="">Porteur : tous</option>
            {options.owners.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </Select>
          <Select aria-label="Statut" value={filters.status ?? ""} onChange={(e) => set({ status: e.target.value })}>
            <option value="">Statut : tous</option>
            {options.statuses.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </Select>
          <Select aria-label="Retard" value={filters.late ?? ""} onChange={(e) => set({ late: e.target.value })}>
            <option value="">Retard : indifférent</option>
            <option value="1">En retard</option>
            <option value="0">Sans retard</option>
          </Select>
          <Select aria-label="Alerte" value={filters.alert ?? ""} onChange={(e) => set({ alert: e.target.value })}>
            <option value="">Alerte : indifférent</option>
            <option value="1">Avec alerte ou décision</option>
            <option value="0">Sans alerte</option>
            {options.alerts.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
          </Select>
          <Select aria-label="Avancement" value={PROGRESS_RANGES.some(([v]) => v === progressValue) ? progressValue : ""}
            onChange={(e) => { const [min, max] = e.target.value ? e.target.value.split("-") : ["", ""]; set({ progress_min: min, progress_max: max }); }}>
            <option value="">Avancement : tous</option>
            {PROGRESS_RANGES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </Select>
          <Input type="date" aria-label="Échéance à partir du" title="Période : à partir du" value={filters.from ?? ""} onChange={(e) => set({ from: e.target.value })} />
          <Input type="date" aria-label="Échéance jusqu'au" title="Période : jusqu'au" value={filters.to ?? ""} onChange={(e) => set({ to: e.target.value })} />
          {options.workspaces.length > 1 && (
            <Select aria-label="Espace de travail" value={filters.workspace ?? ""} onChange={(e) => set({ workspace: e.target.value })}>
              <option value="">Espace : tous</option>
              {options.workspaces.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}
            </Select>
          )}
        </div>
        {active && (
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>{data.filters.join(" · ")}</span>
            <Button variant="link" className="h-auto p-0 text-xs" onClick={reset}>Réinitialiser les filtres</Button>
          </p>
        )}
      </section>

      {data.rows.length === 0 ? (
        <EmptyState
          title={active ? "Aucune ligne ne correspond aux filtres" : "Aucun projet suivi pour l'instant"}
          description={active ? "Élargissez la recherche ou réinitialisez les filtres." : "Créez un projet ou importez le classeur de suivi existant."}
          action={!active && data.can_import ? <Button asChild><Link to="/imports/tracking"><FileUp />Importer le suivi</Link></Button> : undefined}
        />
      ) : (
        <>
          <BoardTable rows={visible} />
          <Pagination page={current} count={data.rows.length} pageSize={PAGE_SIZE} onPage={setPage} />
        </>
      )}
    </div>
  );
}
