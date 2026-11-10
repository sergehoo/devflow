/**
 * Fiche projet complète (port de templates/project/detail.html et de ses partials).
 * Données : `/api/v1/projects/<id>/detail-tabs/?tab=` — contexte de ProjectDetailView exécuté par Django
 * (mêmes sélections, calculs et droits) ; onglet actif dans l'URL (`?tab=`), chargé à la demande.
 */
import { Bot, ChartGantt, ChevronDown, ChevronUp, Columns3, LayoutDashboard, RefreshCcw } from "lucide-react";
import { lazy, Suspense, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useProjectDetail, type ProjectDetail, type TabKey } from "./api";
import { money } from "./format";
import { ProjectHero } from "./Hero";
import { ModePanel } from "./ModePanel";
import { MethodologyWorkspace } from "./MethodologyWorkspace";
import { SPACE_KIND_LABEL, spaceKind, type SpaceView } from "./space";
import { useFormDialog, type FormSpec } from "./formDialog";
import { ProgressBar } from "./ui";

// Onglets chargés à la demande (un fichier par famille d'onglets).
import { ProjectTickets } from "@/features/tickets/TicketsPages";

const PlanningTab = lazy(() => import("./tabs/PlanningTab").then((m) => ({ default: m.PlanningTab })));
const EstimateTab = lazy(() => import("./tabs/FinanceTabs").then((m) => ({ default: m.EstimateTab })));
const ForecastTab = lazy(() => import("./tabs/FinanceTabs").then((m) => ({ default: m.ForecastTab })));
const ExpensesTab = lazy(() => import("./tabs/FinanceTabs").then((m) => ({ default: m.ExpensesTab })));
const BillingTab = lazy(() => import("./tabs/FinanceTabs").then((m) => ({ default: m.BillingTab })));
const TeamTab = lazy(() => import("./tabs/TeamTab").then((m) => ({ default: m.TeamTab })));
const EvolutionTab = lazy(() => import("./tabs/EvolutionTab").then((m) => ({ default: m.EvolutionTab })));
const TasksTab = lazy(() => import("./tabs/TasksTab").then((m) => ({ default: m.TasksTab })));
const KpiTab = lazy(() => import("./tabs/KpiTab").then((m) => ({ default: m.KpiTab })));
const DocumentsTab = lazy(() => import("./tabs/DocumentsTab").then((m) => ({ default: m.DocumentsTab })));
const MeetingsTab = lazy(() => import("./tabs/MeetingsTab").then((m) => ({ default: m.MeetingsTab })));

const TabSkeleton = () => <div className="space-y-4" aria-label="Chargement de l'onglet"><Skeleton className="h-20" /><Skeleton className="h-72" /></div>;

function KpiCard({ label, value, hint, children }: { label: string; value: ReactNode; hint?: string; children?: ReactNode }) {
  return (
    <Card className="min-w-0"><CardContent className="p-4">
      <p className="truncate text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1.5 break-words font-serif text-xl font-semibold leading-tight tabular-nums sm:text-2xl">{value}</p>
      {hint && <p className="mt-1 truncate text-xs text-muted-foreground">{hint}</p>}
      {children}
    </CardContent></Card>
  );
}

/** Bandeau KPI (port de _kpi_strip.html). */
function KpiStrip({ d }: { d: ProjectDetail }) {
  const k = d.kpis;
  return (
    <section aria-label="Indicateurs clés" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <KpiCard label="Avancement" value={`${k.progress_percent} %`}><ProgressBar value={k.progress_percent} label="Avancement du projet" className="mt-3" /></KpiCard>
      <KpiCard label="Risque" value={k.risk_score} hint={d.project.ai_risk_label || "Indice global projet"} />
      <KpiCard label="Tâches" value={k.tasks_total} hint="Backlog opérationnel" />
      <KpiCard label="Membres" value={k.members_count} hint="Équipe projet" />
      {d.can_view_financials ? (
        <>
          <KpiCard label="Coût réel" value={money(k.actual_cost, k.currency)} hint={k.currency} />
          <KpiCard label="CA encaissé" value={money(k.received_revenue, k.currency)} hint={k.currency} />
        </>
      ) : (
        <>
          <KpiCard label="Finance" value="••••" hint="Accès restreint" />
          <KpiCard label="Rentabilité" value="••••" hint="Accès restreint" />
        </>
      )}
    </section>
  );
}

function BandCard({ title, subtitle, badge, rows }: { title: string; subtitle: string; badge: ReactNode; rows: [string, ReactNode, string?][] }) {
  return (
    <Card className="min-w-0"><CardContent className="p-5">
      <div className="flex items-start justify-between gap-2">
        <div><h2 className="text-sm font-semibold">{title}</h2><p className="text-xs text-muted-foreground">{subtitle}</p></div>
        {badge}
      </div>
      <dl className="mt-4 space-y-2.5 text-sm">
        {rows.map(([k, v, cls]) => (
          <div key={k} className="flex items-start justify-between gap-4"><dt className="text-muted-foreground">{k}</dt><dd className={cn("min-w-0 truncate text-right font-medium", cls)}>{v}</dd></div>
        ))}
      </dl>
    </CardContent></Card>
  );
}

/** Bandeau d'informations intelligentes (port de _smart_info_band.html). */
function SmartBand({ d }: { d: ProjectDetail }) {
  const p = d.project;
  const b = d.band;
  const c = d.kpis.currency;
  const tag = (label: string, cls: string) => <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide", cls)}>{label}</span>;
  return (
    <section aria-label="Synthèse" className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <BandCard title="Pilotage" subtitle="Synthèse de cadrage" badge={tag("Projet", "bg-muted text-muted-foreground")}
        rows={[["Responsable", p.owner || "—"], ["Product manager", p.product_manager || "—"], ["Workspace", p.workspace || "—"],
          ["Catégorie", p.category || "—"], ["Échéance cible", formatDate(p.target_date)]]} />
      <BandCard title="Charge" subtitle="Suivi de l'exécution" badge={tag("Live", "bg-warning/15 text-warning")}
        rows={[["À faire", b.todo], ["En cours", b.in_progress], ["Bloquées", b.blocked], ["En retard", b.overdue, b.overdue ? "text-destructive" : undefined]]} />
      <BandCard title="IA & Documents" subtitle="Imports et pièces projet" badge={tag("IA", "bg-info/15 text-info")}
        rows={[["Imports", b.imports], ["Terminés", b.imports_completed], ["Insights IA", b.insights_total], ["Critiques", b.insights_critical, "text-destructive"]]} />
      <BandCard title="Finance" subtitle="Lecture rapide" badge={tag("Budget", "bg-success/15 text-success")}
        rows={[["Budget approuvé", money(b.approved_budget, c)], ["Coût réel", money(b.actual_cost, c)], ["Marge prévisionnelle", money(b.forecast_margin, c)]]} />
    </section>
  );
}

const KIND_ICON = { scrum: RefreshCcw, kanban: Columns3, waterfall: ChartGantt } as const;

/**
 * Barre méthodologie (port de _methodology_toolbar.html) : tableau de bord méthodologie et espace
 * Scrum / Kanban / Waterfall intégrés (ports des pages Django dédiées), ouverts via `?space=`.
 */
function MethodologyBar({ d, view, onView, openForm }: {
  d: ProjectDetail; view: SpaceView | null; onView: (v: SpaceView | null) => void; openForm: (s: FormSpec) => void;
}) {
  const id = d.project.id;
  const kind = spaceKind(d.project.methodology);
  const KindIcon = kind ? KIND_ICON[kind] : LayoutDashboard;
  const toggle = (v: SpaceView) => onView(view === v ? null : v);
  return (
    <section aria-label="Méthodologie" className="space-y-4">
      <Card className="border-primary/30 bg-primary/5">
        <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="flex items-center gap-3">
            <span aria-hidden="true" className="flex size-10 items-center justify-center rounded-xl bg-primary/15 text-brand"><KindIcon className="size-5" /></span>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-brand">Méthodologie : {d.project.methodology_label || "—"}</p>
              <p className="text-xs text-muted-foreground">Outils dédiés à cette méthodologie · IA spécialisée disponible</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant={view === "dashboard" ? "default" : "outline"} aria-expanded={view === "dashboard"} aria-controls="projet-methodology-panel"
              onClick={() => toggle("dashboard")}>
              {view === "dashboard" ? <ChevronUp /> : <ChevronDown />}Tableau de bord
            </Button>
            {kind && (
              <Button size="sm" variant={view === "workspace" ? "default" : "outline"} aria-expanded={view === "workspace"} aria-controls="projet-methodology-panel"
                onClick={() => toggle("workspace")}>
                <KindIcon />Espace {SPACE_KIND_LABEL[kind]}
              </Button>
            )}
            <Button size="sm" variant="outline" asChild><Link to={`/projects/${id}/copilot`}><Bot />Copilote IA</Link></Button>
          </div>
        </CardContent>
      </Card>
      {view && (
        <div id="projet-methodology-panel">
          <MethodologyWorkspace projectId={id} view={kind ? view : "dashboard"} openForm={openForm} />
        </div>
      )}
    </section>
  );
}

function TabNav({ tabs, active, onChange }: { tabs: ProjectDetail["tabs"]; active: string; onChange: (k: TabKey) => void }) {
  return (
    <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
      <div role="tablist" aria-label="Sections du projet" className="flex w-max min-w-full gap-1.5 rounded-2xl border bg-card p-1.5 sm:w-auto sm:flex-wrap">
        {tabs.map((t) => {
          const selected = t.key === active;
          return (
            <button key={t.key} type="button" role="tab" id={`tab-${t.key}`} aria-selected={selected} aria-controls="projet-tabpanel"
              onClick={() => onChange(t.key)}
              className={cn("inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-xl px-3.5 py-2 text-sm font-semibold transition-colors",
                selected ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:bg-hover hover:text-foreground")}>
              {t.label}
              <span className={cn("rounded-full px-1.5 py-0.5 text-[10px] tabular-nums", selected ? "bg-primary-foreground/20" : "bg-muted")}>{t.count}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function TabContent({ d, openForm }: { d: ProjectDetail; openForm: (s: FormSpec) => void }) {
  const id = d.project.id;
  const t = d.tab;
  switch (t.key) {
    case "planification": return <PlanningTab projectId={id} data={t} openForm={openForm} />;
    case "budget_estimatif": return <EstimateTab projectId={id} data={t} openForm={openForm} />;
    case "budget_previsionnel": return <ForecastTab projectId={id} workspaceId={d.project.workspace_id} data={t} openForm={openForm} />;
    case "depenses": return <ExpensesTab projectId={id} data={t} openForm={openForm} />;
    case "facturation_client": return <BillingTab projectId={id} data={t} openForm={openForm} />;
    case "equipes": return <TeamTab projectId={id} workspaceId={d.project.workspace_id} data={t} openForm={openForm} />;
    case "evolution": return <EvolutionTab projectId={id} data={t} openForm={openForm} canViewFinancials={d.can_view_financials} />;
    case "taches": return <TasksTab projectId={id} data={t} />;
    case "kpi_roi": return <KpiTab data={t} currency={d.kpis.currency} canViewFinancials={d.can_view_financials} />;
    case "documents": return <DocumentsTab projectId={id} data={t} openForm={openForm} />;
    case "meetings": return <MeetingsTab projectId={id} data={t} />;
    default: return null;
  }
}

export function ProjectDetailPage() {
  const id = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") || "planification";
  const detail = useProjectDetail(id, requested);
  const form = useFormDialog(id, detail.data?.project.workspace_id);

  if (detail.isPending) return <PageSkeleton />;
  if (detail.isError) return <ErrorState message={detail.error.message} onRetry={() => void detail.refetch()} />;

  const d = detail.data;
  const switching = detail.isPlaceholderData;
  const keys = new Set(d.tabs.map((t) => t.key));
  // Pendant le chargement : onglet demandé ; ensuite : onglet retenu par Django (droits, clé inconnue).
  const active = switching && keys.has(requested as TabKey) ? requested : d.active_tab;
  const onTab = (key: TabKey) => setParams((p) => { p.set("tab", key); return p; }, { replace: true, preventScrollReset: true });
  // Tableau de bord / espace méthodologie ouvert (`?space=`, liens historiques /projects/<id>/scrum/…).
  const spaceParam = params.get("space");
  const space: SpaceView | null = spaceParam === "dashboard" || spaceParam === "workspace" ? spaceParam : null;
  const onSpace = (v: SpaceView | null) =>
    setParams((p) => { if (v) p.set("space", v); else p.delete("space"); return p; }, { replace: true, preventScrollReset: true });

  return (
    <div className="space-y-6">
      <ProjectHero detail={d} onTab={onTab} openForm={form.open} />
      <KpiStrip d={d} />
      <SmartBand d={d} />
      {d.mode && <ModePanel mode={d.mode} />}
      <MethodologyBar d={d} view={space} onView={onSpace} openForm={form.open} />
      <TabNav tabs={d.tabs} active={active} onChange={onTab} />
      <section id="projet-tabpanel" role="tabpanel" aria-labelledby={`tab-${active}`} aria-busy={switching} className="min-w-0">
        {switching ? <TabSkeleton /> : <Suspense fallback={<TabSkeleton />}><TabContent d={d} openForm={form.open} /></Suspense>}
      </section>
      <ProjectTickets projectId={d.project.id} />
      {form.element}
    </div>
  );
}
