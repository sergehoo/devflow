/** Briques communes au suivi : avancement et détail d'une ligne (vue consolidée, fiche projet). */
import type { ReactNode } from "react";
import { Link } from "react-router";
import { Pill, ProgressBar } from "@/features/projet/ui";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { TrackingRow } from "./api";
import { alertTone } from "./format";

export function Progress({ value, label, className }: { value: number; label: string; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <ProgressBar value={value} label={label} className="min-w-12 flex-1" barClassName={value >= 100 ? "bg-success" : undefined} />
      <span className="shrink-0 text-xs font-semibold tabular-nums">{value} %</span>
    </div>
  );
}

function Items({ title, total, children }: { title: string; total: number; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title} · {total}</h4>
      {total === 0 ? <p className="text-sm text-muted-foreground">Aucun élément.</p> : <ul className="space-y-1.5 text-sm">{children}</ul>}
    </div>
  );
}

/** Listes complètes d'une ligne : actions menées, actions à venir, alertes / décisions. */
export function RowDetail({ row }: { row: TrackingRow }) {
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <Items title="Actions menées" total={row.done_count}>
        {row.done.map((d, i) => (
          <li key={`${d.source}-${d.id ?? i}`} className="flex gap-2">
            <span className="mt-2 size-1.5 shrink-0 rounded-full bg-success" aria-hidden="true" />
            <span className="min-w-0 break-words">{d.text}{d.date && <span className="ml-1.5 text-xs text-muted-foreground">{formatDate(d.date)}</span>}</span>
          </li>
        ))}
        {row.done_count > row.done.length && <li className="text-xs text-muted-foreground">… et {row.done_count - row.done.length} plus ancienne(s).</li>}
      </Items>
      <Items title="Actions à venir" total={row.next_count}>
        {row.next.map((n) => (
          <li key={n.id} className="flex gap-2">
            <span className={cn("mt-2 size-1.5 shrink-0 rounded-full", n.late ? "bg-destructive" : "bg-info")} aria-hidden="true" />
            <span className="min-w-0 break-words">
              <Link to={`/tasks/${n.id}`} className="hover:text-brand">{n.text}</Link>
              {n.due && <span className={cn("ml-1.5 text-xs", n.late ? "font-semibold text-destructive" : "text-muted-foreground")}>{formatDate(n.due)}</span>}
            </span>
          </li>
        ))}
        {row.next_count > row.next.length && <li className="text-xs text-muted-foreground">… et {row.next_count - row.next.length} autre(s).</li>}
      </Items>
      <Items title="Alertes / décisions" total={row.alerts.length}>
        {row.alerts.map((a) => (
          <li key={`${a.type}-${a.id}`} className="flex flex-wrap items-start gap-2">
            <Pill tone={alertTone(a)}>{a.kind_label}{a.severity_label ? ` · ${a.severity_label}` : ""}</Pill>
            <span className="min-w-0 flex-1 break-words">{a.text}</span>
          </li>
        ))}
      </Items>
    </div>
  );
}
