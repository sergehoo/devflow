import { CalendarDays, Clock, Folder, Gavel, History, List, Mic, MessagesSquare, Plus, Repeat, Tag, User } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/misc";
import { cn } from "@/lib/utils";
import { useMeetingDashboard, type MeetingDashboard } from "./api";
import { fmtDateTime, fmtTime } from "./constants";

const dayFmt = new Intl.DateTimeFormat("fr-FR", { weekday: "short" });
const numFmt = new Intl.DateTimeFormat("fr-FR", { day: "2-digit" });
const monFmt = new Intl.DateTimeFormat("fr-FR", { month: "short" });
const monthLabel = new Intl.DateTimeFormat("fr-FR", { month: "long", year: "numeric" });

function Panel({ title, icon, children, action, className }: { title: string; icon: ReactNode; children: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2">{icon}{title}</CardTitle>
        {action}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

const Empty = ({ children }: { children: ReactNode }) => <p className="text-sm italic text-muted-foreground">{children}</p>;

function MiniCalendar({ cells }: { cells: MeetingDashboard["calendar"] }) {
  const first = cells.find((c) => c.date)?.date;
  return (
    <Panel title={first ? monthLabel.format(new Date(`${first}T00:00:00`)).replace(/^./, (c) => c.toUpperCase()) : "Ce mois"}
      icon={<CalendarDays className="size-4" aria-hidden="true" />}>
      <div className="grid grid-cols-7 gap-1 text-center text-[10px]">
        {["L", "M", "M", "J", "V", "S", "D"].map((d, i) => <div key={i} className="font-semibold uppercase text-muted-foreground" aria-hidden="true">{d}</div>)}
        {cells.map((c, i) => c.day ? (
          <div key={i} title={c.count ? `${c.count} réunion(s)` : undefined}
            className={cn("relative flex aspect-square items-center justify-center rounded-lg text-[11px]",
              c.is_today ? "bg-primary font-semibold text-primary-foreground" : c.is_weekend ? "bg-muted/40 text-muted-foreground" : "bg-muted text-foreground/80",
              c.count > 0 && "ring-1 ring-primary/40")}>
            {c.day}
            {c.count > 0 && <span className="absolute bottom-0.5 size-1 rounded-full bg-primary" aria-label={`${c.count} réunion(s)`} />}
          </div>
        ) : <div key={i} />)}
      </div>
      <p className="mt-3 flex items-center gap-1 text-[10px] italic text-muted-foreground"><span className="inline-block size-2 rounded-full bg-primary" />Jour avec réunion(s) planifiée(s)</p>
    </Panel>
  );
}

/** Tableau de bord des réunions (`MeetingDashboardView`). */
export function MeetingDashboardPage() {
  const { data: d, isPending, isError, error, refetch } = useMeetingDashboard();
  if (isPending) return <PageSkeleton />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;
  const kpis: [string, number, string][] = [
    ["Réunions ce mois", d.month_stats.total ?? 0, ""], ["Tenues", d.month_stats.held ?? 0, "border-success/30 bg-success/10 text-success"],
    ["Planifiées", d.month_stats.planned ?? 0, "border-primary/30 bg-primary/10 text-primary"], ["Annulées", d.month_stats.cancelled ?? 0, "border-destructive/30 bg-destructive/10 text-destructive"],
  ];
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Collaboration" title="Réunions — vue d'ensemble"
        description="Toutes les réunions du workspace (projet ou libre), comités multi-projets et séries récurrentes."
        actions={<>
          <Button variant="outline" asChild><Link to="/meetings"><List />Liste complète</Link></Button>
          <Button variant="outline" asChild><Link to="/meetings/series"><Repeat />Séries</Link></Button>
          <Button asChild><Link to="/meetings/new"><Plus />Nouvelle réunion</Link></Button>
        </>} />

      <section aria-label="Indicateurs du mois" className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {kpis.map(([label, value, tone]) => (
          <div key={label} className={cn("rounded-2xl border bg-card p-4", tone)}>
            <p className="text-[10px] uppercase opacity-80">{label}</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
          </div>
        ))}
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Panel className="lg:col-span-2" title="Prochaines réunions (14 jours)" icon={<Clock className="size-4" aria-hidden="true" />}>
          {d.upcoming.length ? (
            <ul className="space-y-2">
              {d.upcoming.map((m) => (
                <li key={m.id} className="flex items-start gap-3 rounded-xl border bg-muted/30 p-3">
                  <div className="w-12 shrink-0 text-center" aria-hidden="true">
                    <div className="text-[10px] uppercase text-muted-foreground">{dayFmt.format(new Date(m.scheduled_at))}</div>
                    <div className="text-lg font-bold">{numFmt.format(new Date(m.scheduled_at))}</div>
                    <div className="text-[10px] uppercase text-muted-foreground">{monFmt.format(new Date(m.scheduled_at))}</div>
                  </div>
                  <div className="min-w-0 flex-1">
                    <Link to={`/meetings/${m.id}`} className="block truncate text-sm font-medium hover:text-primary">{m.title}</Link>
                    <p className="mt-0.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                      <span className="inline-flex items-center gap-1"><Clock className="size-3" aria-hidden="true" />{fmtTime(m.scheduled_at)} · {m.duration_minutes} min</span>
                      <span className="inline-flex items-center gap-1"><Tag className="size-3" aria-hidden="true" />{m.type_label}</span>
                      {m.project && <span className="inline-flex items-center gap-1"><Folder className="size-3" aria-hidden="true" />{m.project.name}</span>}
                      {!!m.projects_count && <span>{m.projects_count} projet{m.projects_count > 1 ? "s" : ""}</span>}
                      {m.series_id && <span className="inline-flex items-center gap-1"><Repeat className="size-3" aria-hidden="true" />Série</span>}
                      {m.organizer && <span className="inline-flex items-center gap-1"><User className="size-3" aria-hidden="true" />{m.organizer}</span>}
                    </p>
                  </div>
                  <Badge className="shrink-0">{m.status_label}</Badge>
                </li>
              ))}
            </ul>
          ) : (
            <div className="space-y-3">
              <Empty>Aucune réunion planifiée dans les 14 prochains jours.</Empty>
              <Button size="sm" asChild><Link to="/meetings/new"><Plus />Planifier une réunion</Link></Button>
            </div>
          )}
        </Panel>
        <MiniCalendar cells={d.calendar} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Panel title="Récentes (7 jours passés)" icon={<History className="size-4" aria-hidden="true" />}>
          {d.recent.length ? (
            <ul className="space-y-2">
              {d.recent.map((m) => (
                <li key={m.id} className="rounded-xl border bg-muted/30 p-3">
                  <Link to={`/meetings/${m.id}`} className="block text-sm font-medium hover:text-primary">{m.title}</Link>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">{fmtDateTime(m.scheduled_at)}{m.project ? ` · ${m.project.name}` : ""} · {m.status_label}</p>
                </li>
              ))}
            </ul>
          ) : <Empty>Aucune réunion récente.</Empty>}
        </Panel>
        <Panel title="Top projets par réunions (année)" icon={<Folder className="size-4" aria-hidden="true" />}>
          {d.top_projects.length ? (
            <ul className="space-y-2">
              {d.top_projects.map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-2 rounded-xl border bg-muted/30 p-3">
                  <Link to={`/projects/${p.id}`} className="truncate text-sm hover:text-primary">{p.name}</Link>
                  <Link to={`/meetings?project=${p.id}`} className="shrink-0" aria-label={`${p.count} réunion(s) du projet ${p.name}`}>
                    <Badge className="bg-primary/10 text-primary">{p.count} réunion{p.count > 1 ? "s" : ""}</Badge>
                  </Link>
                </li>
              ))}
            </ul>
          ) : <Empty>Aucune réunion liée à un projet cette année.</Empty>}
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Panel title="Temps de parole (année)" icon={<Mic className="size-4" aria-hidden="true" />}>
          {d.speaking.length ? (
            <ul className="space-y-2">
              {d.speaking.map((s) => (
                <li key={s.name} className="flex items-center justify-between gap-2 text-sm">
                  <span className="truncate">{s.name}</span><Badge className="shrink-0 bg-primary/10 text-primary">{s.minutes} min</Badge>
                </li>
              ))}
            </ul>
          ) : <Empty>Pas encore de transcription avec voix identifiées.</Empty>}
        </Panel>
        <Panel title="Décisions (année)" icon={<Gavel className="size-4" aria-hidden="true" />}>
          <div className="flex flex-col items-center text-center">
            <p className="text-5xl font-bold text-primary tabular-nums">{d.execution_rate}<span className="text-2xl">%</span></p>
            <p className="mt-1 text-xs text-muted-foreground">d'exécution</p>
            <p className="mt-3 text-[11px] text-muted-foreground">{d.executed_decisions_year} exécutées sur {d.total_decisions_year}</p>
            <Link to="/meetings/decisions" className="mt-2 text-xs text-primary hover:underline">Registre complet</Link>
          </div>
        </Panel>
        <Panel title="Top projets discutés (IA)" icon={<MessagesSquare className="size-4" aria-hidden="true" />}>
          {d.top_discussed_projects.length ? (
            <ul className="space-y-2">
              {d.top_discussed_projects.map((p) => (
                <li key={p.title} className="flex items-center justify-between gap-2 text-sm">
                  <span className="truncate">{p.title}</span><Badge className="shrink-0 bg-primary/10 text-primary">{p.count} ×</Badge>
                </li>
              ))}
            </ul>
          ) : <Empty>L'IA n'a pas encore détecté de projets mentionnés.</Empty>}
        </Panel>
      </div>

      {d.active_series.length > 0 && (
        <Panel title={`Séries récurrentes actives (${d.active_series.length})`} icon={<Repeat className="size-4" aria-hidden="true" />}
          action={<Link to="/meetings/series" className="text-xs text-primary hover:underline">Toutes les séries</Link>}>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {d.active_series.map((s) => (
              <Link key={s.id} to={`/meetings/series/${s.id}`} className="rounded-xl border bg-muted/30 p-3 hover:bg-muted">
                <p className="truncate text-sm font-medium">{s.name}</p>
                <p className="mt-0.5 text-[11px] text-muted-foreground">{s.recurrence_label}</p>
              </Link>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}
