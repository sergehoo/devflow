import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CalendarClock, CheckCircle2, ChevronRight, Circle, CircleDot, Flag, Milestone, MoreHorizontal, Users, type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar } from "@/components/ui/misc";
import { formatNumber, parseISODate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import { INSIGHTS_KEY, type DashboardInsights, type FocusTask, type ProjectHealthState } from "./api";

// ─── Utilitaires de date ─────────────────────────────────────────────────────

const DAY = 86_400_000;
const dayDiff = (iso: string, today: string) => Math.round((parseISODate(iso).getTime() - parseISODate(today).getTime()) / DAY);
const shortDate = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" });
const longDate = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long" });
const monthLabel = new Intl.DateTimeFormat("fr-FR", { month: "short" });
const rtf = new Intl.RelativeTimeFormat("fr-FR", { numeric: "auto", style: "short" });

function dueLabel(iso: string | null, today: string): string {
  if (!iso) return "Sans échéance";
  const d = dayDiff(iso, today);
  if (d === 0) return "Aujourd'hui";
  if (d === 1) return "Demain";
  if (d === -1) return "Hier";
  return shortDate.format(parseISODate(iso));
}

function timeAgo(iso: string): string {
  const s = (new Date(iso).getTime() - Date.now()) / 1000;
  const abs = Math.abs(s);
  if (abs < 60) return "à l'instant";
  if (abs < 3600) return rtf.format(Math.round(s / 60), "minute");
  if (abs < DAY / 1000) return rtf.format(Math.round(s / 3600), "hour");
  return rtf.format(Math.round(s / (DAY / 1000)), "day");
}

// ─── Briques visuelles ───────────────────────────────────────────────────────

/** En-tête de carte : titre, sous-titre discret, action à droite. */
export function WidgetHeader({ title, meta, action, className }: { title: ReactNode; meta?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-center justify-between gap-3", className)}>
      <h2 className="flex min-w-0 items-baseline gap-2 text-[17px] font-semibold tracking-tight">
        <span className="truncate">{title}</span>
        {meta && <span className="truncate text-xs font-normal text-muted-foreground">{meta}</span>}
      </h2>
      {action}
    </div>
  );
}

export function ViewAll({ to, children = "Tout voir" }: { to: string; children?: ReactNode }) {
  return (
    <Link to={to} className="inline-flex shrink-0 items-center gap-0.5 text-xs font-medium text-muted-foreground hover:text-foreground">
      {children}<ChevronRight className="size-3.5" aria-hidden="true" />
    </Link>
  );
}

/** Anneau de progression (carte « Ma journée »), avec curseur en bout d'arc. */
export function RingGauge({ value, children, label }: { value: number | null; children: ReactNode; label: string }) {
  const r = 70, c = 2 * Math.PI * r, span = 0.78; // arc de 280°
  const v = value == null ? 0 : Math.max(0, Math.min(100, value));
  const angle = (135 + span * 360 * (v / 100)) * (Math.PI / 180);
  return (
    <div className="relative mx-auto aspect-square w-full max-w-[200px]" role="img" aria-label={label}>
      <svg viewBox="0 0 180 180" className="size-full" aria-hidden="true">
        <defs>
          <linearGradient id="ring-grad" x1="0" y1="1" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--primary-soft)" />
            <stop offset="100%" stopColor="var(--primary-strong)" />
          </linearGradient>
        </defs>
        <circle cx="90" cy="90" r={r} fill="none" stroke="var(--border)" strokeWidth="9" strokeLinecap="round"
          strokeDasharray={`${c * span} ${c}`} transform="rotate(135 90 90)" />
        {v > 0 && (
          <circle cx="90" cy="90" r={r} fill="none" stroke="url(#ring-grad)" strokeWidth="9" strokeLinecap="round"
            strokeDasharray={`${c * span * (v / 100)} ${c}`} transform="rotate(135 90 90)" />
        )}
        {value != null && (
          <circle cx={90 + r * Math.cos(angle)} cy={90 + r * Math.sin(angle)} r="9" fill="var(--card)" stroke="var(--primary)" strokeWidth="5" />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">{children}</div>
    </div>
  );
}

/** Jauge semi-circulaire à graduations (« Santé des projets »). */
export function TickGauge({ value, label }: { value: number | null; label: string }) {
  const ticks = 34, v = value == null ? 0 : Math.max(0, Math.min(100, value));
  const lit = Math.round((v / 100) * ticks);
  return (
    <svg viewBox="0 0 240 132" className="w-full" role="img" aria-label={label}>
      {Array.from({ length: ticks + 1 }, (_, i) => {
        const a = Math.PI - (i / ticks) * Math.PI;
        const r1 = 92, r2 = i % 2 ? 108 : 112;
        return (
          <line key={i} x1={120 + r1 * Math.cos(a)} y1={122 - r1 * Math.sin(a)} x2={120 + r2 * Math.cos(a)} y2={122 - r2 * Math.sin(a)}
            stroke={i <= lit && value != null ? "var(--primary)" : "var(--border)"} strokeWidth="4" strokeLinecap="round" />
        );
      })}
      <text x="120" y="112" textAnchor="middle" className="fill-foreground" style={{ font: "600 38px Inter, sans-serif", letterSpacing: "-0.03em" }}>
        {value == null ? "—" : `${value}%`}
      </text>
    </svg>
  );
}

/** Carte KPI (référence : pastille d'icône jaune, valeur + unité, pied libellé / indicateur). */
export function StatCard({ icon: Icon, value, unit, label, hint, to }: {
  icon: LucideIcon; value: number; unit: string; label: string; hint?: ReactNode; to?: string;
}) {
  const body = (
    <>
      <span className="flex size-8 items-center justify-center rounded-full bg-primary text-primary-foreground" aria-hidden="true">
        <Icon className="size-4" strokeWidth={2} />
      </span>
      <p className="mt-3 text-[22px] font-semibold leading-tight tracking-tight tabular">
        {formatNumber(value)} <span className="text-[15px] font-medium text-foreground/80">{unit}</span>
      </p>
      <div className="mt-3 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
        <span className="shrink-0">{label}</span>
        {hint && <span className="min-w-0 truncate font-medium text-foreground/80">{hint}</span>}
      </div>
    </>
  );
  const cls = "block rounded-[22px] bg-card p-4 shadow-card transition-shadow dark:border dark:border-border";
  return to ? <Link to={to} className={cn(cls, "hover:shadow-md")}>{body}</Link> : <div className={cls}>{body}</div>;
}

/** Barre de progression jaune avec curseur (référence « Projects »). */
export function ProgressBar({ value, label }: { value: number; label: string }) {
  const v = Math.max(0, Math.min(100, value || 0));
  return (
    <div className="relative h-1.5 rounded-full bg-hover" role="progressbar" aria-label={label} aria-valuenow={v} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full bg-primary" style={{ width: `${v}%` }} />
      <span className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-primary bg-card" style={{ left: `${v}%` }} aria-hidden="true" />
    </div>
  );
}

const HEALTH: Record<ProjectHealthState, { label: string; dot: string; pill: string }> = {
  on_track: { label: "Dans les délais", dot: "bg-primary", pill: "bg-success/10 text-success" },
  at_risk: { label: "À risque", dot: "bg-warning", pill: "bg-warning/10 text-warning" },
  delayed: { label: "En retard", dot: "bg-destructive", pill: "bg-destructive/10 text-destructive" },
};

// ─── Ma journée ──────────────────────────────────────────────────────────────

export function DayCard({ data }: { data: DashboardInsights }) {
  const { planned, done, completed_today } = data.day;
  const ratio = planned ? Math.round((done / planned) * 100) : null;
  return (
    <Card className="p-5 sm:p-6">
      <WidgetHeader title="Ma journée" action={<span className="text-xs font-semibold text-muted-foreground">Aujourd'hui</span>} />
      <p className="mt-0.5 text-xs capitalize text-muted-foreground">{longDate.format(parseISODate(data.today))}</p>
      <div className="mt-4">
        <RingGauge value={ratio} label={ratio == null ? "Aucune tâche prévue aujourd'hui" : `${ratio} % des tâches du jour terminées`}>
          {ratio == null ? (
            <>
              <span className="text-4xl font-semibold tracking-tight">—</span>
              <span className="mt-1 max-w-28 text-xs text-muted-foreground">Aucune tâche prévue aujourd'hui</span>
            </>
          ) : (
            <>
              <span className="text-[42px] font-semibold leading-none tracking-tight tabular">{ratio}<span className="ml-1 text-lg font-normal text-muted-foreground">%</span></span>
              <span className="mt-2 max-w-[7.5rem] text-center text-xs leading-snug text-muted-foreground">tâches du jour terminées</span>
            </>
          )}
        </RingGauge>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <Link to="/my-day" className="rounded-2xl bg-gradient-to-br from-primary-soft to-primary-faint p-3.5 transition hover:brightness-[0.98]">
          <p className="text-2xl font-semibold tracking-tight tabular">{done}<span className="text-sm font-normal text-muted-foreground"> / {planned}</span></p>
          <p className="mt-1 text-xs text-foreground/80">Tâches faites</p>
        </Link>
        <Link to="/projects" className="rounded-2xl bg-gradient-to-br from-primary-soft to-primary-faint p-3.5 transition hover:brightness-[0.98]">
          <p className="text-2xl font-semibold tracking-tight tabular">{data.health.on_track}<span className="text-sm font-normal text-muted-foreground"> projets</span></p>
          <p className="mt-1 text-xs text-foreground/80">Dans les délais</p>
        </Link>
      </div>
      {completed_today > done && (
        <p className="mt-3 text-xs text-muted-foreground">{completed_today} tâche(s) terminée(s) aujourd'hui au total.</p>
      )}
    </Card>
  );
}

// ─── Mes priorités ───────────────────────────────────────────────────────────

const PRIORITY_PILL: Record<string, string> = {
  CRITICAL: "bg-destructive/10 text-destructive",
  HIGH: "bg-primary-faint text-brand",
};

function FocusRow({ task, today }: { task: FocusTask; today: string }) {
  const qc = useQueryClient();
  const done = useMutation({
    mutationFn: () => api(`tasks/${task.id}/toggle-complete/`, { method: "POST", body: {} }),
    onSuccess: () => {
      toast.success("Tâche terminée.");
      void qc.invalidateQueries({ queryKey: INSIGHTS_KEY });
      void qc.invalidateQueries({ queryKey: ["dashboard", "summary"] });
    },
    onError: (e) => toast.error(e.message),
  });
  const StatusIcon = task.status === "IN_PROGRESS" ? CircleDot : task.status === "BLOCKED" ? Flag : Circle;
  return (
    <li className="flex items-center gap-3 border-b px-5 py-3 last:border-b-0 sm:px-6">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground" title={task.status_label}>
        <StatusIcon className="size-4" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <Link to={`/tasks/${task.id}`} className="block truncate text-sm font-medium hover:text-brand">{task.title}</Link>
        <p className="truncate text-xs text-muted-foreground">{task.project || "Sans projet"} · {task.status_label}</p>
      </div>
      <span className={cn("hidden rounded-full px-2.5 py-0.5 text-[11px] font-semibold sm:inline-flex", PRIORITY_PILL[task.priority] ?? "text-foreground/80")}>
        {task.priority_label}
      </span>
      <Avatar name={task.assignee || "?"} className="hidden size-7 text-[10px] md:flex" />
      <span className={cn("w-24 shrink-0 text-right text-xs", task.overdue ? "font-semibold text-destructive" : "text-muted-foreground")}>
        {dueLabel(task.due_date, today)}
      </span>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" className="size-8" aria-label={`Actions pour « ${task.title} »`}><MoreHorizontal /></Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem asChild><Link to={`/tasks/${task.id}`}>Ouvrir la tâche</Link></DropdownMenuItem>
          <DropdownMenuItem disabled={done.isPending} onSelect={() => done.mutate()}><CheckCircle2 />Marquer terminée</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  );
}

export function TaskFocusList({ data }: { data: DashboardInsights }) {
  return (
    <Card className="overflow-hidden">
      <div className="border-b px-5 py-4 sm:px-6">
        <WidgetHeader title="Mes priorités" meta={`${data.focus_total} tâche(s) ouverte(s)`} action={<ViewAll to="/my-day" />} />
      </div>
      {data.focus.length ? (
        <ul>{data.focus.map((t) => <FocusRow key={t.id} task={t} today={data.today} />)}</ul>
      ) : (
        <p className="px-6 py-10 text-center text-sm text-muted-foreground">Aucune tâche ouverte ne vous est assignée.</p>
      )}
    </Card>
  );
}

// ─── Heatmap d'activité ──────────────────────────────────────────────────────

const LEVEL = ["bg-hatch", "bg-primary-faint", "bg-primary-soft", "bg-primary", "bg-primary-strong"];
const WEEK_OPTIONS = [8, 15, 26, 52];

export function ActivityHeatmap({ data, weeks, onWeeks, className }: { data: DashboardInsights; weeks: number; onWeeks: (w: number) => void; className?: string }) {
  const cells = data.heatmap;
  const max = Math.max(0, ...cells.map((c) => c.count));
  const first = cells[0] ? parseISODate(cells[0].date) : new Date();
  const lead = (first.getDay() + 6) % 7; // lundi = 0
  const columns = Math.ceil((lead + cells.length) / 7);
  const grid: ({ date: string; count: number } | null)[] = [...Array(lead).fill(null), ...cells];
  const months = Array.from({ length: columns }, (_, col) => {
    const cell = grid.slice(col * 7, col * 7 + 7).find(Boolean);
    if (!cell) return "";
    const d = parseISODate(cell.date);
    const prev = col > 0 ? grid.slice((col - 1) * 7, col * 7).find(Boolean) : null;
    return !prev || parseISODate(prev.date).getMonth() !== d.getMonth() ? monthLabel.format(d).replace(".", "") : "";
  });
  const level = (n: number) => (n === 0 || !max ? 0 : Math.min(4, Math.ceil((n / max) * 4)));
  return (
    <Card className={cn("p-5 sm:p-7", className)}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-[26px] font-semibold leading-tight tracking-tight sm:text-[30px]">Activité</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {formatNumber(data.completed_in_period)} tâche(s) terminée(s) sur les {weeks} dernières semaines
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex" aria-hidden="true">
            Moins {LEVEL.slice(1).map((c) => <span key={c} className={cn("size-4 rounded-[5px]", c)} />)} Plus
          </div>
          <label className="sr-only" htmlFor="heatmap-weeks">Période</label>
          <select id="heatmap-weeks" value={weeks} onChange={(e) => onWeeks(Number(e.target.value))}
            className="h-8 rounded-full border bg-card px-3 text-xs font-medium text-foreground">
            {WEEK_OPTIONS.map((w) => <option key={w} value={w}>{w} semaines</option>)}
          </select>
        </div>
      </div>
      <div className="mt-6 overflow-x-auto">
        <div className="min-w-[420px]">
          <div className="mb-2 grid gap-1.5 text-[11px] text-muted-foreground" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }} aria-hidden="true">
            {months.map((m, i) => <span key={i} className="truncate capitalize">{m}</span>)}
          </div>
          <div role="img" aria-label={`Heatmap : ${data.completed_in_period} tâches terminées, maximum ${max} par jour`}
            className="grid grid-flow-col gap-1.5" style={{ gridTemplateRows: "repeat(7, minmax(0, 1fr))", gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
            {grid.map((c, i) => c ? (
              <span key={c.date} title={`${c.count} tâche(s) terminée(s) · ${longDate.format(parseISODate(c.date))}`}
                className={cn("aspect-square rounded-[5px]", LEVEL[level(c.count)])} />
            ) : <span key={`pad-${i}`} className="aspect-square" />)}
          </div>
        </div>
      </div>
    </Card>
  );
}

// ─── Santé des projets ───────────────────────────────────────────────────────

export function ProjectHealth({ data }: { data: DashboardInsights }) {
  const h = data.health;
  const rows: [ProjectHealthState, number][] = [["on_track", h.on_track], ["at_risk", h.at_risk], ["delayed", h.delayed]];
  return (
    <Card className="p-5 sm:p-6">
      <WidgetHeader title="Santé des projets" action={<ViewAll to="/projects" />} />
      {h.active ? (
        <>
          <div className="mx-auto mt-4 max-w-[260px]">
            <TickGauge value={h.healthy_percent} label={`${h.healthy_percent} % des projets actifs dans les délais`} />
          </div>
          <div className="mt-3 flex items-center justify-between">
            <p className="text-xl font-semibold tabular">{h.healthy_percent}%</p>
            <p className="flex items-center gap-1.5 text-xs font-medium text-success">
              <span className="size-2 rounded-full bg-success" aria-hidden="true" />{h.active} projet(s) actif(s)
            </p>
          </div>
          <ul className="mt-3 space-y-2 text-sm">
            {rows.map(([k, n]) => (
              <li key={k} className="flex items-center gap-2">
                <span className={cn("size-2 rounded-sm", HEALTH[k].dot)} aria-hidden="true" />
                <span className="text-muted-foreground">{HEALTH[k].label}</span>
                <span className="ml-auto font-semibold tabular">{n}</span>
              </li>
            ))}
          </ul>
        </>
      ) : <p className="py-8 text-center text-sm text-muted-foreground">Aucun projet actif.</p>}
    </Card>
  );
}

// ─── À venir ─────────────────────────────────────────────────────────────────

const KIND_ICON = { task: CheckCircle2, meeting: Users, milestone: Milestone } as const;
const KIND_LABEL = { task: "Échéance", meeting: "Réunion", milestone: "Jalon" } as const;

export function UpcomingEvents({ data }: { data: DashboardInsights }) {
  const groups = new Map<string, DashboardInsights["upcoming"]>();
  data.upcoming.forEach((u) => groups.set(u.date, [...(groups.get(u.date) ?? []), u]));
  const heading = (iso: string) => {
    const d = dayDiff(iso, data.today);
    return d === 0 ? "Aujourd'hui" : d === 1 ? "Demain" : longDate.format(parseISODate(iso));
  };
  return (
    <Card className="p-5 sm:p-6">
      <WidgetHeader title="À venir" action={<span className="rounded-full border px-2.5 py-0.5 text-[11px] text-muted-foreground">7 jours</span>} />
      {data.upcoming.length ? (
        <div className="mt-3 space-y-4">
          {[...groups].map(([date, items]) => (
            <section key={date} aria-label={heading(date)}>
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{heading(date)}</h3>
              <ul className="mt-2 divide-y">
                {items.map((u) => {
                  const Icon = KIND_ICON[u.kind];
                  return (
                    <li key={`${u.kind}-${u.id}`}>
                      <Link to={u.url} className="flex items-center gap-3 py-2.5 hover:text-brand">
                        <span className={cn("h-9 w-[3px] shrink-0 rounded-full", dayDiff(date, data.today) === 0 ? "bg-primary" : "bg-border")} aria-hidden="true" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">{u.title}</span>
                          <span className="flex items-center gap-1 truncate text-xs text-muted-foreground">
                            <Icon className="size-3" aria-hidden="true" />{KIND_LABEL[u.kind]}{u.subtitle ? ` · ${u.subtitle}` : ""}
                          </span>
                        </span>
                        <span className="shrink-0 text-xs text-muted-foreground tabular">{u.time ?? ""}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      ) : <p className="py-6 text-center text-sm text-muted-foreground">Rien de prévu dans les 7 prochains jours.</p>}
      <Button variant="outline" className="mt-4 w-full" asChild>
        <Link to="/meetings/dashboard"><CalendarClock />Voir l'agenda des réunions</Link>
      </Button>
    </Card>
  );
}

// ─── Projets ─────────────────────────────────────────────────────────────────

export function ProjectsCard({ data, className }: { data: DashboardInsights; className?: string }) {
  return (
    <Card className={cn("p-5 sm:p-6", className)}>
      <WidgetHeader title="Projets" action={<ViewAll to="/projects" />} />
      {data.projects.length ? (
        <ul className="mt-3 space-y-4">
          {data.projects.map((p) => (
            <li key={p.id}>
              <div className="flex items-center gap-2">
                <div className="min-w-0 flex-1">
                  <Link to={`/projects/${p.id}`} className="block truncate text-sm font-semibold hover:text-brand">{p.name}</Link>
                  <p className="truncate text-xs text-muted-foreground">{p.status_label}{p.members_count ? ` · ${p.members_count} membre(s)` : ""}</p>
                </div>
                {p.members.length > 0 && (
                  <span className="flex -space-x-2" aria-label={`Membres : ${p.members.join(", ")}`}>
                    {p.members.map((m) => <Avatar key={m} name={m} className="size-6 text-[9px]" />)}
                  </span>
                )}
                <span className={cn("hidden rounded-full px-2 py-0.5 text-[10px] font-semibold 2xl:inline-flex", HEALTH[p.health].pill)}>{HEALTH[p.health].label}</span>
                <span className="w-9 text-right text-sm font-semibold tabular">{p.progress_percent}%</span>
              </div>
              <div className="mt-2.5"><ProgressBar value={p.progress_percent} label={`Avancement de ${p.name}`} /></div>
            </li>
          ))}
        </ul>
      ) : <p className="py-6 text-center text-sm text-muted-foreground">Aucun projet actif.</p>}
    </Card>
  );
}

// ─── Activité récente ────────────────────────────────────────────────────────

export function RecentActivity({ items, className }: { items: { id: number; title: string; actor: string; created_at: string | null }[]; className?: string }) {
  return (
    <Card className={cn("p-5 sm:p-6", className)}>
      <WidgetHeader title="Activité" action={<ViewAll to="/m/activity-log">Tout</ViewAll>} />
      {items.length ? (
        <ol className="mt-2 divide-y">
          {items.slice(0, 6).map((a) => (
            <li key={a.id} className="flex items-start gap-3 py-3">
              <Avatar name={a.actor || "Système"} className="size-8 text-[10px]" />
              <div className="min-w-0 flex-1">
                <p className="text-sm"><span className="font-semibold">{a.actor || "Système"}</span> <span className="text-muted-foreground">{a.title}</span></p>
              </div>
              {a.created_at && <time dateTime={a.created_at} className="shrink-0 text-[11px] text-muted-foreground">{timeAgo(a.created_at)}</time>}
            </li>
          ))}
        </ol>
      ) : <p className="py-6 text-center text-sm text-muted-foreground">Aucune activité récente.</p>}
    </Card>
  );
}
