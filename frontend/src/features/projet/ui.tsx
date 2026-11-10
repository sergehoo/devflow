/** Briques d'affichage de la fiche projet (tokens du thème uniquement, clair / sombre). */
import { FileDown } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/misc";
import { cn, legacyUrl } from "@/lib/utils";
import { TONE, type Tone } from "./format";

export function Pill({ tone = "muted", className, children }: { tone?: Tone; className?: string; children: ReactNode }) {
  return <Badge className={cn(TONE[tone], className)}>{children}</Badge>;
}

export function Stat({ label, value, hint, className }: { label: string; value: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <Card className={cn("min-w-0", className)}>
      <CardContent className="p-4">
        <p className="truncate text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
        <div className="mt-1 break-words font-serif text-xl font-semibold leading-tight tabular-nums sm:text-2xl">{value}</div>
        {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
      </CardContent>
    </Card>
  );
}

export function StatGrid({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("grid grid-cols-2 gap-3 md:grid-cols-4", className)}>{children}</div>;
}

export function Section({ title, description, count, actions, children, className }: {
  title: string; description?: string; count?: number; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <Card className={cn("min-w-0", className)}>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2">{title}{count != null && <Badge>{count}</Badge>}</CardTitle>
          {description && <CardDescription className="mt-0.5 text-xs">{description}</CardDescription>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

/** Barre « Actions rapides » en tête de chaque onglet. */
export function ActionBar({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{title}</h3>
          {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
        </div>
        <div className="flex flex-wrap gap-2">{children}</div>
      </CardContent>
    </Card>
  );
}

export function EmptyLine({ children }: { children: ReactNode }) {
  return <p className="rounded-2xl border border-dashed bg-muted/30 px-4 py-8 text-center text-sm text-muted-foreground">{children}</p>;
}

export function ProgressBar({ value, label, className, barClassName }: { value: number; label: string; className?: string; barClassName?: string }) {
  const v = Math.max(0, Math.min(100, Number(value) || 0));
  return (
    <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={v}
      className={cn("h-1.5 overflow-hidden rounded-full bg-muted", className)}>
      <div className={cn("h-full rounded-full bg-primary transition-[width]", barClassName)} style={{ width: `${v}%` }} />
    </div>
  );
}

/** Tableau responsive : défilement horizontal interne (jamais de débordement de page). */
export function Table({ caption, head, children, minWidth = "min-w-[640px]" }: { caption: string; head: ReactNode[]; children: ReactNode; minWidth?: string }) {
  return (
    <div className="-mx-1 overflow-x-auto px-1">
      <table className={cn("w-full text-sm", minWidth)}>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b text-left text-[11px] uppercase tracking-wide text-muted-foreground">
            {head.map((h, i) => <th key={i} scope="col" className="px-2 py-2.5 font-semibold">{h}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y">{children}</tbody>
      </table>
    </div>
  );
}

export const Td = ({ className, children, colSpan }: { className?: string; children?: ReactNode; colSpan?: number }) => (
  <td colSpan={colSpan} className={cn("px-2 py-2.5 align-top", className)}>{children}</td>
);

/** Export Excel du chiffrage : fichier généré par la vue Django (ProjectBudgetExportExcelView). */
export function ExcelButton({ projectId, label = "Export Excel", variant = "outline" }: { projectId: number; label?: string; variant?: "outline" | "default" | "ghost" }) {
  return <Button size="sm" variant={variant} asChild><a href={legacyUrl(`/projects/${projectId}/budget/export-excel/`)} download><FileDown />{label}</a></Button>;
}
