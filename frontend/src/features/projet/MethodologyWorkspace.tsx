/**
 * Tableau de bord méthodologie et espaces Scrum / Kanban / Waterfall intégrés à la fiche projet
 * (port de project/methodology/{dashboard,scrum_workspace,kanban_workspace,waterfall_workspace}.html).
 * Données : `/api/v1/projects/<id>/space/` (services.methodology_space : mêmes sélections et mêmes
 * indicateurs `compute_kpi` que les vues Django) — aucun calcul côté React.
 */
import { Flag, ListPlus, ShieldCheck } from "lucide-react";
import { Link } from "react-router";
import { ErrorState } from "@/components/feedback/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { FormSpec } from "./formDialog";
import { useMethodologySpace, type Kpi, type MethodologySpaceData, type SpaceTask, type SpaceView } from "./space";
import { EmptyLine, Pill, ProgressBar, Section, Table, Td } from "./ui";

const UNITS: Record<string, string> = { story_points: "SP", days: "j", "%": "%", tickets: "tickets", tâches: "tâches" };
const KPI_FALLBACK: Record<string, string> = {
  velocity: "Vélocité", burndown_sprint: "Burndown", sprint_success_rate: "Taux de succès des sprints",
  wip_count: "Travail en cours", cycle_time: "Cycle time", lead_time: "Lead time", throughput_weekly: "Throughput / semaine",
  cumulative_flow: "Flux cumulé", advancement_global: "Avancement global", schedule_adherence: "Respect du planning",
  budget_consumption: "Consommation budget", critical_path_length: "Chemin critique", gantt_data: "Gantt",
};
// Indicateurs rendus en graphique plutôt qu'en carte.
const CHART_KPIS = new Set(["cumulative_flow", "gantt_data"]);
const CFD_TONE: Record<string, string> = {
  TODO: "bg-muted-foreground/40", IN_PROGRESS: "bg-info", REVIEW: "bg-warning", DONE: "bg-success", BLOCKED: "bg-destructive",
};
const SPRINT_LANES: [string, string][] = [["TODO", "À faire"], ["IN_PROGRESS", "En cours"], ["REVIEW", "En revue"], ["DONE", "Terminé"]];

const nf = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
const isScalar = (k: Kpi) => k.value == null || typeof k.value !== "object";
const kpiLabel = (code: string, k: Kpi) => (k.label && k.label !== "—" ? k.label : KPI_FALLBACK[code] ?? code.replace(/_/g, " "));
function kpiValue(k: Kpi) {
  if (!isScalar(k) || k.value == null || k.value === "") return "—";
  return typeof k.value === "number" ? nf.format(k.value) : String(k.value);
}
const num = (v: unknown) => (typeof v === "number" ? v : Number(v) || 0);

function KpiCard({ label, k, pinned }: { label: string; k: Kpi; pinned?: boolean }) {
  const unit = k.unit ? UNITS[k.unit] ?? k.unit : "";
  const total = num(k.extra?.total);
  return (
    <div className={cn("min-w-0 rounded-xl border bg-card p-3", pinned && "border-primary/40 bg-primary/5")}>
      <p className="truncate text-[11px] font-semibold uppercase tracking-wide text-muted-foreground" title={label}>{label}</p>
      <p className="mt-1 flex items-baseline gap-1.5"><span className="font-serif text-2xl font-semibold tabular-nums">{kpiValue(k)}</span>
        {unit && kpiValue(k) !== "—" && <span className="text-xs text-muted-foreground">{unit}</span>}</p>
      {total > 0 && "remaining" in (k.extra ?? {}) && (
        <ProgressBar value={(num(k.extra?.remaining) / total) * 100} label={`${label} : reste à faire`} className="mt-2" />
      )}
      {k.unit === "%" && typeof k.value === "number" && <ProgressBar value={k.value} label={label} className="mt-2" />}
    </div>
  );
}

/** Histogramme simple (série `{x, y}` d'un indicateur) : barres en tokens du thème. */
function MiniBars({ title, series }: { title: string; series: { x: string; y: number }[] }) {
  const max = Math.max(1, ...series.map((p) => num(p.y)));
  return (
    <figure className="min-w-0 rounded-xl border bg-card p-3">
      <figcaption className="text-xs font-semibold text-muted-foreground">{title}</figcaption>
      <div role="img" aria-label={`${title} : ${series.map((p) => `${p.x} ${nf.format(num(p.y))}`).join(", ")}`}
        className="mt-3 flex h-24 items-end gap-1">
        {series.map((p) => (
          <div key={p.x} className="flex min-w-0 flex-1 flex-col items-center gap-1">
            <div className="w-full rounded-t bg-primary/70" style={{ height: `${Math.max(4, (num(p.y) / max) * 100)}%` }} title={`${p.x} : ${nf.format(num(p.y))}`} />
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-1 text-[10px] text-muted-foreground" aria-hidden="true">
        {series.map((p) => <span key={p.x} className="min-w-0 flex-1 truncate text-center">{p.x}</span>)}
      </div>
    </figure>
  );
}

function TaskCard({ t }: { t: SpaceTask }) {
  return (
    <li className="rounded-lg border bg-card p-2 text-xs">
      <Link to={`/tasks/${t.id}`} className="line-clamp-2 font-medium hover:text-brand">{t.title}</Link>
      <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{[t.assignee, t.priority_label].filter(Boolean).join(" · ") || t.status_label}</p>
    </li>
  );
}

function Dashboard({ s }: { s: MethodologySpaceData }) {
  const items = s.dashboard.length
    ? s.dashboard.map((d) => ({ key: d.name, label: d.name, k: d.result, pinned: d.pinned }))
    : Object.entries(s.kpis).map(([code, k]) => ({ key: code, label: kpiLabel(code, k), k, pinned: false }));
  const cards = items.filter((i) => isScalar(i.k));
  const charts = items.filter((i) => (i.k.series?.length ?? 0) > 1);
  if (!cards.length && !charts.length) {
    return <EmptyLine>Aucun indicateur méthodologique : la méthodologie du projet n'a pas de tableau de bord configuré.</EmptyLine>;
  }
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
        {cards.map((i) => <KpiCard key={i.key} label={i.label} k={i.k} pinned={i.pinned} />)}
      </div>
      {charts.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2">
          {charts.slice(0, 4).map((i) => <MiniBars key={i.key} title={i.label} series={i.k.series ?? []} />)}
        </div>
      )}
    </div>
  );
}

function ScrumSpace({ s, openForm, projectId }: { s: MethodologySpaceData; openForm: (f: FormSpec) => void; projectId: number }) {
  const sprint = s.active_sprint;
  const q = { project: String(projectId) };
  const newSprint = () => openForm({ name: "sprint", title: "Nouveau sprint", query: q, hidden: ["project"], submitLabel: "Créer" });
  const velocity = s.kpis.velocity?.series ?? [];
  return (
    <div className="space-y-4">
      {sprint ? (
        <Section title={`Sprint actif · ${sprint.name}`} description={`${formatDate(sprint.start_date)} → ${formatDate(sprint.end_date)}${sprint.goal ? ` · « ${sprint.goal} »` : ""}`}
          actions={<><Pill tone="success">{sprint.status_label}</Pill><Button size="sm" variant="outline" asChild><Link to={`/m/sprint/${sprint.id}`}>Ouvrir le sprint</Link></Button></>}>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {SPRINT_LANES.map(([code, label]) => {
              const tasks = sprint.tasks.filter((t) => t.status === code);
              return (
                <div key={code} className="min-w-0 rounded-xl border bg-muted/30 p-2.5">
                  <p className="flex justify-between text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"><span>{label}</span><span>{tasks.length}</span></p>
                  {tasks.length ? <ul className="mt-2 space-y-1.5">{tasks.map((t) => <TaskCard key={t.id} t={t} />)}</ul>
                    : <p className="mt-2 text-xs text-muted-foreground">—</p>}
                </div>
              );
            })}
          </div>
        </Section>
      ) : (
        <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed p-6 text-center">
          <p className="text-sm font-semibold">Aucun sprint actif</p>
          <p className="text-xs text-muted-foreground">Planifiez un sprint pour suivre le burndown et la vélocité.</p>
          <Button size="sm" onClick={newSprint}><Flag />Créer un sprint</Button>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <Section title="Product backlog" count={s.backlog?.length ?? 0} description="Éléments ouverts, par rang"
          actions={<Button size="sm" variant="outline" onClick={() => openForm({ name: "backlog-item", title: "Élément de backlog", query: q, hidden: ["project"], submitLabel: "Créer" })}><ListPlus />Élément de backlog</Button>}>
          {s.backlog?.length ? (
            <ul className="space-y-1.5">
              {s.backlog.map((b) => (
                <li key={b.id} className="flex items-center gap-2 rounded-xl border bg-muted/20 p-2.5 text-sm">
                  <Pill tone="info" className="shrink-0">{b.status_label}</Pill>
                  <Link to={`/m/backlog-item/${b.id}`} className="min-w-0 flex-1 truncate font-medium hover:text-brand">{b.title}</Link>
                  <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{b.story_points ? `${b.story_points} SP · ` : ""}#{b.rank ?? "—"}</span>
                </li>
              ))}
            </ul>
          ) : <EmptyLine>Backlog vide : ajoutez des user stories.</EmptyLine>}
        </Section>
        <div className="space-y-4">
          {velocity.length > 0 && <MiniBars title="Vélocité des derniers sprints (SP)" series={velocity} />}
          <Section title="Sprints récents" actions={<Button size="sm" variant="ghost" onClick={newSprint}><Flag />Nouveau sprint</Button>}>
            {s.sprints?.length ? (
              <Table caption="Sprints récents" minWidth="min-w-[420px]" head={["Sprint", "Statut", "SP planifiés", "SP complétés", "Vélocité"]}>
                {s.sprints.map((sp) => (
                  <tr key={sp.id} className="hover:bg-muted/40">
                    <Td><Link to={`/m/sprint/${sp.id}`} className="font-medium hover:text-brand">{sp.name}</Link></Td>
                    <Td><Pill>{sp.status_label}</Pill></Td>
                    <Td className="text-right tabular-nums">{sp.total_story_points ?? 0}</Td>
                    <Td className="text-right tabular-nums">{sp.completed_story_points ?? 0}</Td>
                    <Td className="text-right font-medium tabular-nums text-brand">{sp.velocity_completed ?? 0}</Td>
                  </tr>
                ))}
              </Table>
            ) : <EmptyLine>Aucun sprint.</EmptyLine>}
          </Section>
        </div>
      </div>
    </div>
  );
}

function KanbanSpace({ s }: { s: MethodologySpaceData }) {
  const throughput = s.kpis.throughput_weekly?.series ?? [];
  const cfd = (s.kpis.cumulative_flow?.series ?? []).filter((p) => num(p.y) > 0);
  const cfdTotal = cfd.reduce((acc, p) => acc + num(p.y), 0);
  return (
    <div className="space-y-4">
      <Section title="Board Kanban" description="Colonnes de la méthodologie et limites WIP">
        {s.columns?.length ? (
          <div className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-1">
            {s.columns.map((c) => (
              <div key={c.code} className={cn("w-60 shrink-0 rounded-xl border bg-muted/30 p-2.5", c.over_wip && "border-destructive/50")}>
                <p className="flex justify-between gap-2 text-[11px] font-semibold uppercase tracking-wide">
                  <span className="truncate">{c.name}</span>
                  <span className={c.over_wip ? "text-destructive" : "text-muted-foreground"} title={c.over_wip ? "Limite WIP dépassée" : undefined}>
                    {c.count}{c.wip_limit != null ? ` / ${c.wip_limit}` : ""}
                  </span>
                </p>
                {c.tasks.length ? <ul className="mt-2 space-y-1.5">{c.tasks.map((t) => <TaskCard key={t.id} t={t} />)}</ul>
                  : <p className="mt-2 text-xs text-muted-foreground">Aucune tâche.</p>}
              </div>
            ))}
          </div>
        ) : <EmptyLine>Aucune colonne : la méthodologie Kanban du projet n'a pas de statuts configurés.</EmptyLine>}
      </Section>
      <div className="grid gap-4 md:grid-cols-2">
        {throughput.length > 0 && <MiniBars title="Throughput (tâches terminées / semaine)" series={throughput} />}
        {cfdTotal > 0 && (
          <figure className="min-w-0 rounded-xl border bg-card p-3">
            <figcaption className="text-xs font-semibold text-muted-foreground">Flux cumulé — distribution actuelle</figcaption>
            <div role="img" aria-label={`Flux cumulé : ${cfd.map((p) => `${p.x} ${p.y}`).join(", ")}`} className="mt-3 flex h-4 overflow-hidden rounded-full bg-muted">
              {cfd.map((p) => <div key={p.x} className={CFD_TONE[p.x] ?? "bg-primary"} style={{ width: `${(num(p.y) / cfdTotal) * 100}%` }} />)}
            </div>
            <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              {cfd.map((p) => (
                <li key={p.x} className="flex items-center gap-1.5"><span aria-hidden="true" className={cn("size-2 rounded-full", CFD_TONE[p.x] ?? "bg-primary")} />{p.x.replace("_", " ").toLowerCase()} · {p.y}</li>
              ))}
            </ul>
          </figure>
        )}
      </div>
    </div>
  );
}

function WaterfallSpace({ s }: { s: MethodologySpaceData }) {
  const bars = (s.kpis.gantt_data?.extra?.bars as { name: string; start: string; end: string; progress: number }[] | undefined) ?? [];
  const times = bars.flatMap((b) => [Date.parse(b.start), Date.parse(b.end)]).filter((t) => !Number.isNaN(t));
  const min = Math.min(...times);
  const span = Math.max(1, Math.max(...times) - min);
  return (
    <div className="space-y-4">
      {bars.length > 0 && (
        <Section title="Diagramme de Gantt" description="Phases planifiées et avancement">
          <ul className="space-y-3">
            {bars.map((b) => {
              const left = ((Date.parse(b.start) - min) / span) * 100;
              const width = Math.max(2, ((Date.parse(b.end) - Date.parse(b.start)) / span) * 100);
              return (
                <li key={`${b.name}-${b.start}`} className="grid gap-1 text-xs sm:grid-cols-[10rem_1fr_9rem] sm:items-center sm:gap-3">
                  <span className="truncate font-medium" title={b.name}>{b.name}</span>
                  <div className="relative h-5 overflow-hidden rounded bg-muted" role="img"
                    aria-label={`${b.name} : du ${formatDate(b.start)} au ${formatDate(b.end)}, ${Math.round(num(b.progress))} %`}>
                    <div className="absolute inset-y-0 rounded bg-primary/25" style={{ left: `${left}%`, width: `${width}%` }}>
                      <div className="h-full rounded bg-primary" style={{ width: `${Math.max(0, Math.min(100, num(b.progress)))}%` }} />
                    </div>
                  </div>
                  <span className="text-[11px] text-muted-foreground sm:text-right">{formatDate(b.start)} → {formatDate(b.end)}</span>
                </li>
              );
            })}
          </ul>
        </Section>
      )}
      <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        <Section title="Phases" count={s.phases?.length ?? 0}>
          {s.phases?.length ? (
            <ol className="space-y-2">
              {s.phases.map((p, i) => (
                <li key={p.id} className="rounded-xl border bg-muted/20 p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <Pill tone="info">{i + 1}</Pill>
                    <span className="font-semibold">{p.name}</span>
                    <Pill tone={p.status === "DONE" ? "success" : p.status === "BLOCKED" ? "danger" : p.status === "IN_PROGRESS" ? "warning" : "muted"}>{p.status_label}</Pill>
                    {p.gate_required && <Pill tone="warning"><ShieldCheck className="size-3" aria-hidden="true" />Gate</Pill>}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{[p.owner, p.start_date ? `${formatDate(p.start_date)} → ${formatDate(p.end_date)}` : ""].filter(Boolean).join(" · ") || "Non planifiée"}</p>
                  <ProgressBar value={num(p.progress)} label={`Avancement de la phase ${p.name}`} className="mt-2" />
                </li>
              ))}
            </ol>
          ) : <EmptyLine>Aucune phase définie.</EmptyLine>}
        </Section>
        <Section title="Jalons" count={s.milestones?.length ?? 0}>
          {s.milestones?.length ? (
            <ul className="divide-y text-sm">
              {s.milestones.map((m) => (
                <li key={m.id} className="flex justify-between gap-3 py-2">
                  <Link to={`/m/milestone/${m.id}`} className="min-w-0 truncate font-medium hover:text-brand">{m.name}</Link>
                  <span className="shrink-0 text-xs text-muted-foreground">{formatDate(m.due_date)}</span>
                </li>
              ))}
            </ul>
          ) : <EmptyLine>Aucun jalon.</EmptyLine>}
        </Section>
      </div>
    </div>
  );
}

export function MethodologyWorkspace({ projectId, view, openForm }: { projectId: number; view: SpaceView; openForm: (f: FormSpec) => void }) {
  const space = useMethodologySpace(projectId);
  if (space.isPending) return <Skeleton className="h-48" />;
  if (space.isError) return <ErrorState message={space.error.message} onRetry={() => void space.refetch()} />;
  const s = space.data;
  if (view === "dashboard" || !s.kind) {
    return (
      <Section title={s.methodology ? `Tableau de bord · ${s.methodology.name}` : "Tableau de bord méthodologie"}
        description="Indicateurs calculés par le moteur méthodologique DevFlow">
        <Dashboard s={s} />
      </Section>
    );
  }
  const kpiCards = Object.entries(s.kpis).filter(([code, k]) => !CHART_KPIS.has(code) && isScalar(k));
  return (
    <div className="space-y-4">
      {kpiCards.length > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          {kpiCards.map(([code, k]) => <KpiCard key={code} label={kpiLabel(code, k)} k={k} />)}
        </div>
      )}
      {s.kind === "scrum" && <ScrumSpace s={s} openForm={openForm} projectId={projectId} />}
      {s.kind === "kanban" && <KanbanSpace s={s} />}
      {s.kind === "waterfall" && <WaterfallSpace s={s} />}
    </div>
  );
}
