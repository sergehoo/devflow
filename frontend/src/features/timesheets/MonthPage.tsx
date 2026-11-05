import { useMemo } from "react";
import { Link, useSearchParams } from "react-router";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Card, CardContent } from "@/components/ui/card";
import { useMe } from "@/features/auth/api";
import { formatHours, parseISODate, toISODate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useEntries } from "./api";
import { PeriodNav, TimesheetTabs } from "./TimesheetNav";

const WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

/** Fiche mensuelle : totaux journaliers de ses propres saisies (lecture), accès à la semaine pour saisir. */
export function MonthPage() {
  const { data: me } = useMe();
  const [params, setParams] = useSearchParams();
  const ref = parseISODate(params.get("date") ?? toISODate(new Date()));
  const first = new Date(ref.getFullYear(), ref.getMonth(), 1);
  const last = new Date(ref.getFullYear(), ref.getMonth() + 1, 0);
  const { data, isPending, isError, error, refetch } = useEntries(
    { user: me?.id, date_from: toISODate(first), date_to: toISODate(last), page_size: 500 }, !!me,
  );

  const perDay = useMemo(() => {
    const map = new Map<string, { hours: number; billable: number }>();
    data?.results.forEach((e) => {
      const d = map.get(e.entry_date) ?? { hours: 0, billable: 0 };
      d.hours += e.hours;
      if (e.is_billable) d.billable += e.hours;
      map.set(e.entry_date, d);
    });
    return map;
  }, [data]);

  const offset = (first.getDay() + 6) % 7;
  const cells = Array.from({ length: offset + last.getDate() }, (_, i) => (i < offset ? null : new Date(first.getFullYear(), first.getMonth(), i - offset + 1)));
  const today = toISODate(new Date());
  const label = first.toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
  const go = (d: string) => setParams((p) => { p.set("date", d); return p; });

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Timesheets" title="Mes heures" />
      <TimesheetTabs />
      <PeriodNav label={label} date={toISODate(first)} onChange={go}
        prev={toISODate(new Date(first.getFullYear(), first.getMonth() - 1, 1))} next={toISODate(new Date(first.getFullYear(), first.getMonth() + 1, 1))} />
      {isPending ? <PageSkeleton /> : isError ? <ErrorState message={error.message} onRetry={() => void refetch()} /> : (
        <>
          <section aria-label="Totaux du mois" className="grid gap-3 sm:grid-cols-3">
            {([["Total du mois", data.totals.hours], ["Facturable", data.totals.billable_hours], ["Non facturable", data.totals.non_billable_hours]] as const).map(([k, v]) => (
              <Card key={k}><CardContent className="py-4"><p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{k}</p><p className="mt-1 font-serif text-xl font-semibold tabular-nums">{formatHours(v)}</p></CardContent></Card>
            ))}
          </section>
          <div className="grid grid-cols-7 gap-1.5 text-sm" role="grid" aria-label={`Heures de ${label}`}>
            {WEEKDAYS.map((d) => <div key={d} role="columnheader" className="pb-1 text-center text-xs font-semibold text-muted-foreground">{d}</div>)}
            {cells.map((d, i) => {
              if (!d) return <div key={`empty-${i}`} aria-hidden="true" />;
              const iso = toISODate(d);
              const t = perDay.get(iso);
              return (
                <Link key={iso} to={`/timesheets?date=${iso}`} role="gridcell" aria-label={`${d.toLocaleDateString("fr-FR")} : ${t ? formatHours(t.hours) : "aucune saisie"}`}
                  className={cn("flex min-h-20 flex-col rounded-xl border bg-card p-2 hover:border-primary", iso === today && "border-primary", d.getDay() % 6 === 0 && "bg-muted/50")}>
                  <span className="text-xs text-muted-foreground">{d.getDate()}</span>
                  {t && <span className="mt-auto font-semibold tabular-nums">{formatHours(t.hours)}</span>}
                  {t && t.billable < t.hours && <span className="text-[11px] text-muted-foreground">{formatHours(t.hours - t.billable)} non fact.</span>}
                </Link>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
