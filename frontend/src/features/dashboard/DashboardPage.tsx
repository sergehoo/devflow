import { AlertTriangle, CheckCircle2, Clock3, FolderKanban, Plus, TrendingUp, Users } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Avatar } from "@/components/ui/misc";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { useMe } from "@/features/auth/api";
import { formatHours, formatMoney, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useDashboard, useDashboardInsights, type DashboardSummary } from "./api";
import {
  ActivityHeatmap, DayCard, ProjectHealth, ProjectsCard, RecentActivity, StatCard, TaskFocusList, UpcomingEvents, WidgetHeader,
} from "./widgets";

const SEVERITY: Record<string, string> = {
  critical: "border-destructive/40 bg-destructive/5",
  high: "border-warning/40 bg-warning/5",
  medium: "border-info/40 bg-info/5",
  positive: "border-success/40 bg-success/5",
};

const DISTRIBUTION = [
  { key: "todo", label: "À faire", color: "bg-subtle-foreground" },
  { key: "in_progress", label: "En cours", color: "bg-info" },
  { key: "review", label: "En revue", color: "bg-warning" },
  { key: "done", label: "Terminées", color: "bg-success" },
  { key: "blocked", label: "Bloquées", color: "bg-destructive" },
  { key: "cancelled", label: "Annulées", color: "bg-muted-foreground/40" },
];

function Progress({ value, className }: { value: number; className?: string }) {
  const v = Math.max(0, Math.min(100, value || 0));
  return (
    <div className={cn("h-1.5 overflow-hidden rounded-full bg-muted", className)} role="progressbar" aria-valuenow={v} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full bg-primary" style={{ width: `${v}%` }} />
    </div>
  );
}

function TaskDistribution({ data }: { data: DashboardSummary["task_distribution"] }) {
  const total = DISTRIBUTION.reduce((s, d) => s + (data[d.key] ?? 0), 0);
  if (!total) return <p className="text-sm text-muted-foreground">Aucune tâche dans ce workspace.</p>;
  return (
    <div className="space-y-3">
      <div className="flex h-3 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        {DISTRIBUTION.map((d) => {
          const n = data[d.key] ?? 0;
          return n ? <div key={d.key} className={d.color} style={{ width: `${(n / total) * 100}%` }} /> : null;
        })}
      </div>
      <ul className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-3">
        {DISTRIBUTION.map((d) => (
          <li key={d.key} className="flex items-center gap-2">
            <span className={cn("size-2.5 rounded-full", d.color)} aria-hidden="true" />
            <span className="text-muted-foreground">{d.label}</span>
            <span className="ml-auto font-semibold tabular-nums">{data[d.key] ?? 0}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Finance({ f }: { f: DashboardSummary["finance"] }) {
  const currency = String(f.currency || "XOF");
  const margin = Number(f.actual_margin ?? 0);
  const rows: [string, ReactNode][] = [
    ["Budget approuvé", formatMoney(f.approved_budget_total as number, currency)],
    ["Dépenses réelles", formatMoney(f.actual_expenses_total as number, currency)],
    ["Revenus attendus", formatMoney(f.expected_revenue_total as number, currency)],
    ["Revenus encaissés", formatMoney(f.received_revenue_total as number, currency)],
    ["Heures saisies", formatHours(f.logged_hours_total as number)],
  ];
  return (
    <div className="space-y-4">
      <div>
        <div className="mb-1 flex justify-between text-sm">
          <span className="text-muted-foreground">Consommation du budget</span>
          <span className="font-semibold tabular-nums">{formatNumber(f.budget_usage_percent as number)} %</span>
        </div>
        <Progress value={Number(f.budget_usage_percent ?? 0)} />
      </div>
      <dl className="space-y-2 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="font-medium tabular-nums">{v}</dd>
          </div>
        ))}
        <div className="flex justify-between gap-3 border-t pt-2">
          <dt className="font-semibold">Marge réelle</dt>
          <dd className={cn("font-semibold tabular-nums", margin < 0 ? "text-destructive" : "text-success")}>{formatMoney(margin, currency)}</dd>
        </div>
      </dl>
    </div>
  );
}

export function DashboardPage() {
  const { data: me } = useMe();
  const summary = useDashboard();
  const [weeks, setWeeks] = useState(15);
  const insights = useDashboardInsights(weeks);

  if (summary.isPending || insights.isPending) return <PageSkeleton />;
  if (summary.isError) return <ErrorState message={summary.error.message} onRetry={() => void summary.refetch()} />;
  if (insights.isError) return <ErrorState message={insights.error.message} onRetry={() => void insights.refetch()} />;
  const data = summary.data;
  const ins = insights.data;
  if (!data.workspace || !ins.workspace) {
    return <EmptyState title="Aucun workspace" description="Rejoignez ou créez un workspace pour voir votre tableau de bord." />;
  }
  const s = data.stats;
  const sprint = data.active_sprint;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tableau de bord"
        description={<>Bonjour {me?.first_name || me?.full_name}, voici l'activité de <span className="font-medium text-foreground">{data.workspace.name}</span>{data.workspace.quarter_label ? ` · ${data.workspace.quarter_label}` : ""}.</>}
        actions={<Button asChild><Link to="/tasks/new"><Plus />Nouvelle tâche</Link></Button>}
      />

      {/* Grille de référence : 23 % / 52 % / 25 % (≥ xl) ; 2 colonnes (≥ md) ; empilée sur mobile. */}
      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-[minmax(0,23fr)_minmax(0,52fr)_minmax(0,25fr)]">
        <div className="flex min-w-0 flex-col gap-5 md:order-1">
          <DayCard data={ins} />
          <section aria-label="Indicateurs clés" className="grid grid-cols-2 gap-4">
            <StatCard icon={FolderKanban} value={Number(s.active_projects_count ?? 0)} unit="projets" label="Actifs"
              hint={`${formatNumber(s.projects_total)} au total`} to="/projects" />
            <StatCard icon={CheckCircle2} value={Number(s.completed_projects_count ?? 0)} unit="projets" label="Terminés"
              hint={`${formatNumber(s.project_completion_percent)} %`} />
            <StatCard icon={AlertTriangle} value={ins.health.at_risk} unit="projets" label="À risque"
              hint={`${ins.health.delayed} en retard`} to="/projects" />
            <StatCard icon={Clock3} value={ins.overdue_tasks} unit="tâches" label="En retard" hint="Voir" to="/my-day" />
          </section>
          <RecentActivity items={data.activities} className="flex-1" />
        </div>
        <div className="flex min-w-0 flex-col gap-5 md:order-3 md:col-span-2 xl:order-2 xl:col-span-1">
          <TaskFocusList data={ins} />
          <ActivityHeatmap data={ins} weeks={weeks} onWeeks={setWeeks} className="flex-1" />
        </div>
        <div className="flex min-w-0 flex-col gap-5 md:order-2 xl:order-3">
          <ProjectHealth data={ins} />
          <UpcomingEvents data={ins} />
          <ProjectsCard data={ins} className="flex-1" />
        </div>
      </div>

      <section aria-labelledby="pilotage" className="space-y-5 pt-2">
        <WidgetHeader title={<span id="pilotage">Pilotage du workspace</span>} />
        {data.analysis_cards.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {data.analysis_cards.map((c) => (
              <div key={c.title} className={cn("rounded-[22px] border p-5", SEVERITY[c.severity] ?? "bg-card")}>
                <p className="font-semibold">{c.title}</p>
                <p className="mt-1 text-sm text-muted-foreground">{c.text}</p>
                <p className="mt-2 flex items-center gap-1 text-xs font-semibold text-foreground"><TrendingUp className="size-3.5" aria-hidden="true" />{c.action}</p>
              </div>
            ))}
          </div>
        )}
        <div className="grid gap-5 lg:grid-cols-3">
          <Card>
            <CardHeader><CardTitle>Finances</CardTitle></CardHeader>
            <CardContent><Finance f={data.finance} /></CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Répartition des tâches</CardTitle></CardHeader>
            <CardContent>
              <TaskDistribution data={data.task_distribution} />
              <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
                <Users className="size-3.5" aria-hidden="true" />{formatNumber(s.active_members_count)} membres actifs · {formatNumber(s.blocked_tasks_count)} tâches bloquées · {formatNumber(s.open_risks_count)} risques ouverts
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Charge de l'équipe</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {data.team_load.length === 0 ? <p className="text-sm text-muted-foreground">Aucun membre.</p> : data.team_load.map((m) => (
                <div key={m.user} className="flex items-center gap-3">
                  <Avatar name={m.user} className="size-8 text-[10px]" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{m.user}</p>
                    <Progress value={Number(m.current_load_percent ?? 0)} className="mt-1" />
                  </div>
                  <span className="text-xs font-semibold tabular-nums">{formatNumber(m.current_load_percent)} %</span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        {sprint && (
          <Card>
            <CardHeader>
              <CardTitle>{sprint.name}</CardTitle>
              <p className="text-sm text-muted-foreground">
                {[sprint.project, sprint.team, sprint.status_label].filter(Boolean).join(" · ")}
                {sprint.remaining_days != null && ` · ${sprint.remaining_days} j restants`}
                {sprint.total_story_points ? ` · ${sprint.completed_story_points ?? 0}/${sprint.total_story_points} pts` : ""}
              </p>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {sprint.columns.map((col) => (
                <div key={col.id} className="rounded-2xl bg-muted p-3">
                  <p className="mb-2 flex items-center gap-2 text-sm font-semibold">
                    <span className="size-2.5 rounded-full" style={{ backgroundColor: col.color }} aria-hidden="true" />
                    {col.name}<span className="ml-auto text-xs text-muted-foreground">{col.count}</span>
                  </p>
                  <ul className="space-y-1.5">
                    {col.tasks.map((t) => (
                      <li key={t.id}>
                        <Link to={`/tasks/${t.id}`} className="block rounded-xl bg-card px-2.5 py-1.5 text-sm hover:text-brand">{t.title}</Link>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {data.top_cost_members.length > 0 && (
          <Card>
            <CardHeader><CardTitle>Coûts journaliers (TJM)</CardTitle></CardHeader>
            <CardContent className="grid gap-x-8 gap-y-2.5 sm:grid-cols-2 lg:grid-cols-3">
              {data.top_cost_members.map((p) => (
                <div key={p.user} className="flex items-center justify-between gap-3 text-sm">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{p.user}</p>
                    <p className="truncate text-xs text-muted-foreground">{p.job_title || "—"}</p>
                  </div>
                  <span className="font-semibold tabular-nums">{formatMoney(p.cost_per_day, p.currency || "XOF")}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  );
}
