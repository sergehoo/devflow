import { AlertTriangle, CheckCircle2, FolderKanban, ListTodo, TrendingUp, Users } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Avatar, Badge } from "@/components/ui/misc";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { useMe } from "@/features/auth/api";
import { formatDate, formatDateTime, formatHours, formatMoney, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useDashboard, type DashboardSummary } from "./api";

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

function Kpi({ icon, label, value, hint }: { icon: ReactNode; label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <Card>
      <CardContent className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">{icon}</span>
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
          <p className="mt-1 font-serif text-2xl font-semibold tabular-nums">{value}</p>
          {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

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
  const { data, isPending, isError, error, refetch } = useDashboard();

  if (isPending) return <PageSkeleton />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;
  if (!data.workspace) {
    return <EmptyState title="Aucun workspace" description="Rejoignez ou créez un workspace pour voir votre tableau de bord." />;
  }
  const s = data.stats;
  const sprint = data.active_sprint;

  return (
    <div className="space-y-6">
      <header>
        <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-primary">
          {data.workspace.name}{data.workspace.quarter_label ? ` · ${data.workspace.quarter_label}` : ""}
        </p>
        <h1 className="mt-1 font-serif text-3xl font-semibold">Bonjour {me?.first_name || me?.full_name}</h1>
      </header>

      <section aria-label="Indicateurs clés" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={<FolderKanban className="size-5" />} label="Projets actifs" value={formatNumber(s.active_projects_count)}
          hint={`${formatNumber(s.projects_total)} au total · ${formatNumber(s.delayed_projects_count)} en retard`} />
        <Kpi icon={<CheckCircle2 className="size-5" />} label="Tâches terminées" value={`${formatNumber(s.done_ratio_percent)} %`}
          hint={`${formatNumber(s.done_tasks_count)} terminées · ${formatNumber(s.pending_tasks_count)} en attente`} />
        <Kpi icon={<AlertTriangle className="size-5" />} label="Tâches bloquées" value={formatNumber(s.blocked_tasks_count)}
          hint={`${formatNumber(s.open_risks_count)} risques ouverts · ${formatNumber(s.critical_risks_count)} critiques`} />
        <Kpi icon={<Users className="size-5" />} label="Membres actifs" value={formatNumber(s.active_members_count)}
          hint={`${formatNumber(s.remote_members_count)} en télétravail`} />
      </section>

      {data.analysis_cards.length > 0 && (
        <section aria-label="Analyse" className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.analysis_cards.map((c) => (
            <div key={c.title} className={cn("rounded-2xl border p-4", SEVERITY[c.severity] ?? "bg-card")}>
              <p className="font-semibold">{c.title}</p>
              <p className="mt-1 text-sm text-muted-foreground">{c.text}</p>
              <p className="mt-2 flex items-center gap-1 text-xs font-semibold text-foreground"><TrendingUp className="size-3.5" aria-hidden="true" />{c.action}</p>
            </div>
          ))}
        </section>
      )}

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader><CardTitle>Projets</CardTitle></CardHeader>
          <CardContent>
            {data.projects.length === 0 ? (
              <EmptyState title="Aucun projet" />
            ) : (
              <ul className="divide-y">
                {data.projects.map((p) => (
                  <li key={p.id} className="py-3 first:pt-0 last:pb-0">
                    <Link to={`/projects/${p.id}`} className="group block">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium group-hover:text-primary">{p.name}</span>
                        <Badge>{p.status_label}</Badge>
                        {p.risk_score ? <Badge className={p.risk_score >= 70 ? "bg-destructive/10 text-destructive" : ""}>Risque {p.risk_score}</Badge> : null}
                        <span className="ml-auto text-xs text-muted-foreground">{p.team || "—"} · échéance {formatDate(p.target_date)}</span>
                      </div>
                      <div className="mt-2 flex items-center gap-3">
                        <Progress value={p.progress_percent} className="flex-1" />
                        <span className="w-10 text-right text-xs font-semibold tabular-nums">{p.progress_percent} %</span>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Finances</CardTitle></CardHeader>
          <CardContent><Finance f={data.finance} /></CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Répartition des tâches</CardTitle></CardHeader>
          <CardContent><TaskDistribution data={data.task_distribution} /></CardContent>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader><CardTitle>Échéances des 7 prochains jours</CardTitle></CardHeader>
          <CardContent>
            {data.due_soon_tasks.length === 0 ? (
              <p className="text-sm text-muted-foreground">Aucune échéance proche.</p>
            ) : (
              <ul className="divide-y">
                {data.due_soon_tasks.map((t) => (
                  <li key={t.id} className="flex flex-wrap items-center gap-2 py-2.5 first:pt-0 last:pb-0">
                    <ListTodo className="size-4 text-subtle-foreground" aria-hidden="true" />
                    <Link to={`/tasks/${t.id}`} className="font-medium hover:text-primary">{t.title}</Link>
                    <span className="text-xs text-muted-foreground">{t.project}</span>
                    <span className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
                      <Badge>{t.priority_label}</Badge>
                      {t.assignee || "Non assignée"} · {formatDate(t.due_date)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
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
              <div key={col.id} className="rounded-xl bg-muted/60 p-3">
                <p className="mb-2 flex items-center gap-2 text-sm font-semibold">
                  <span className="size-2.5 rounded-full" style={{ backgroundColor: col.color }} aria-hidden="true" />
                  {col.name}<span className="ml-auto text-xs text-muted-foreground">{col.count}</span>
                </p>
                <ul className="space-y-1.5">
                  {col.tasks.map((t) => (
                    <li key={t.id}>
                      <Link to={`/tasks/${t.id}`} className="block rounded-lg bg-card px-2.5 py-1.5 text-sm hover:text-primary">{t.title}</Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 xl:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Charge de l'équipe</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {data.team_load.length === 0 ? <p className="text-sm text-muted-foreground">Aucun membre.</p> : data.team_load.map((m) => (
              <div key={m.user} className="flex items-center gap-3">
                <Avatar name={m.user} className="size-8" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{m.user}</p>
                  <Progress value={Number(m.current_load_percent ?? 0)} className="mt-1" />
                </div>
                <span className="text-xs font-semibold tabular-nums">{formatNumber(m.current_load_percent)} %</span>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Coûts journaliers (TJM)</CardTitle></CardHeader>
          <CardContent className="space-y-2.5">
            {data.top_cost_members.length === 0 ? <p className="text-sm text-muted-foreground">Aucun TJM renseigné.</p> : data.top_cost_members.map((p) => (
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

        <Card>
          <CardHeader><CardTitle>Activité récente</CardTitle></CardHeader>
          <CardContent>
            {data.activities.length === 0 ? <p className="text-sm text-muted-foreground">Aucune activité.</p> : (
              <ol className="space-y-3">
                {data.activities.map((a) => (
                  <li key={a.id} className="text-sm">
                    <p className="font-medium">{a.title}</p>
                    <p className="text-xs text-muted-foreground">{a.actor || "Système"} · {formatDateTime(a.created_at)}</p>
                  </li>
                ))}
              </ol>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
