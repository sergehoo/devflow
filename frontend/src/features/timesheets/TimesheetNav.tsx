import * as Popover from "@radix-ui/react-popover";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { DayPicker } from "react-day-picker";
import { fr } from "react-day-picker/locale";
import "react-day-picker/style.css";
import { NavLink } from "react-router";
import { Button } from "@/components/ui/button";
import { parseISODate, toISODate } from "@/lib/format";
import { cn } from "@/lib/utils";

const TABS = [
  { to: "/timesheets", label: "Semaine", end: true },
  { to: "/timesheets/month", label: "Mois" },
  { to: "/timesheets/history", label: "Historique" },
  { to: "/timesheets/validation", label: "Validation" },
];

export function TimesheetTabs() {
  return (
    <nav aria-label="Timesheets" className="flex gap-1 overflow-x-auto border-b">
      {TABS.map((t) => (
        <NavLink key={t.to} to={t.to} end={t.end}
          className={({ isActive }) => cn("whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-semibold",
            isActive ? "border-primary text-brand" : "border-transparent text-muted-foreground hover:text-foreground")}>
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}

/** Navigation de période : précédent / suivant / aujourd'hui + calendrier (React Day Picker). */
export function PeriodNav({ label, date, prev, next, onChange }: { label: string; date: string; prev: string; next: string; onChange: (d: string) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="icon" aria-label="Période précédente" onClick={() => onChange(prev)}><ChevronLeft /></Button>
      <Popover.Root>
        <Popover.Trigger asChild>
          <Button variant="outline"><CalendarDays />{label}</Button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content sideOffset={6} className="z-50 rounded-2xl border bg-card p-3 shadow-[0_12px_32px_rgba(32,32,32,0.12)]">
            <DayPicker mode="single" locale={fr} weekStartsOn={1} showWeekNumber selected={parseISODate(date)}
              defaultMonth={parseISODate(date)} onSelect={(d) => d && onChange(toISODate(d))} />
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
      <Button variant="outline" size="icon" aria-label="Période suivante" onClick={() => onChange(next)}><ChevronRight /></Button>
      <Button variant="ghost" onClick={() => onChange(toISODate(new Date()))}>Aujourd'hui</Button>
    </div>
  );
}
