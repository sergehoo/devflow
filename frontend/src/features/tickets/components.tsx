import { AlarmClock, Mail, PauseCircle, PenLine, PlugZap } from "lucide-react";
import { Link } from "react-router";
import { cn } from "@/lib/utils";
import type { TicketRow } from "./api";
import { dueIn, priorityMeta, remaining, statusMeta } from "./constants";

export function StatusPill({ status, label }: { status: string; label?: string }) {
  const m = statusMeta(status);
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-hover px-2.5 py-0.5 text-[11px] font-semibold text-foreground">
      <span className={cn("size-1.5 rounded-full", m.dot)} aria-hidden="true" />{label ?? m.label}
    </span>
  );
}

export function PriorityPill({ priority }: { priority: string }) {
  const m = priorityMeta(priority);
  return <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold", m.pill)} title={m.label}>{priority}</span>;
}

/** Échéance de résolution : dépassée (rouge), < 24 h (orange), en pause. */
export function SlaBadge({ t }: { t: Pick<TicketRow, "resolution_due" | "resolution_breached" | "first_response_breached" | "sla_paused" | "status"> }) {
  if (!["NEW", "QUALIFIED", "ASSIGNED", "IN_PROGRESS", "WAITING"].includes(t.status) || !t.resolution_due) return null;
  if (t.sla_paused) {
    return <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground"><PauseCircle className="size-3" aria-hidden="true" />SLA en pause</span>;
  }
  const s = dueIn(t.resolution_due);
  const breached = t.resolution_breached || t.first_response_breached || (s != null && s < 0);
  const soon = s != null && s < 86_400;
  return (
    <span className={cn("inline-flex items-center gap-1 text-[11px] font-medium", breached ? "text-destructive" : soon ? "text-warning" : "text-muted-foreground")}>
      <AlarmClock className="size-3" aria-hidden="true" />{breached ? "SLA dépassé" : remaining(s)}
    </span>
  );
}

export function TicketCard({ t, draggable, onDragStart }: { t: TicketRow; draggable?: boolean; onDragStart?: (e: React.DragEvent) => void }) {
  return (
    <article draggable={draggable} onDragStart={onDragStart}
      className="rounded-2xl bg-card p-3.5 shadow-card transition-shadow hover:shadow-md dark:border dark:border-border">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold text-muted-foreground">{t.reference}</span>
        <PriorityPill priority={t.priority} />
      </div>
      <Link to={`/tickets/${t.id}`} className="mt-1.5 block text-sm font-semibold leading-snug hover:text-brand">{t.title}</Link>
      <p className="mt-1 truncate text-xs text-muted-foreground">{t.application?.name}{t.team ? ` · ${t.team.name}` : " · non assigné"}</p>
      <div className="mt-2.5 flex items-center justify-between gap-2">
        <span className="truncate text-xs text-foreground/80">{t.assignee?.name ?? "—"}</span>
        <SlaBadge t={t} />
      </div>
    </article>
  );
}

const SOURCES = {
  API: { label: "API", icon: PlugZap },
  MANUAL: { label: "Manuel", icon: PenLine },
  EMAIL: { label: "E-mail", icon: Mail },
} as const;

/** Canal d'origine du ticket : API / Manuel / E-mail. */
export function SourceBadge({ source, className }: { source?: string; className?: string }) {
  const m = SOURCES[(source ?? "API") as keyof typeof SOURCES] ?? SOURCES.API;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full bg-hover px-2 py-0.5 text-[11px] font-medium text-muted-foreground", className)}>
      <m.icon className="size-3" aria-hidden="true" />{m.label}
    </span>
  );
}
