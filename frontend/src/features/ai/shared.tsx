import { Bot, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/misc";
import { cn } from "@/lib/utils";
import type { AIStatus } from "./api";
import { STATUS_TONE } from "./constants";

export function StatusBadge({ status, label, className }: { status: string; label: string; className?: string }) {
  return <Badge className={cn(STATUS_TONE[status] ?? "", className)}>{label}</Badge>;
}

/** Fournisseur IA actif ; sinon les services basculent sur leurs heuristiques (jamais d'erreur). */
export function AIStatusNotice({ ai, fallback, className }: { ai?: AIStatus; fallback: string; className?: string }) {
  if (!ai) return null;
  return (
    <p role="status" className={cn(
      "flex items-start gap-2 rounded-2xl border px-4 py-3 text-sm",
      ai.available ? "border-primary/20 bg-primary/5 text-foreground" : "border-warning/30 bg-warning/10 text-foreground",
      className,
    )}>
      {ai.available ? <Sparkles className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden="true" />
        : <Bot className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />}
      <span>{ai.available ? <>IA active : <strong className="font-semibold">{ai.provider}</strong>.</> : fallback}</span>
    </p>
  );
}

export function ProgressBar({ value, label }: { value: number; label: string }) {
  const v = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={v}
      className="h-2 overflow-hidden rounded-full bg-muted">
      <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${v}%` }} />
    </div>
  );
}

export function Stat({ label, value, hint, accent }: { label: string; value: ReactNode; hint?: string; accent?: string }) {
  return (
    <div className="min-w-0 rounded-[22px] border border-transparent bg-card shadow-card dark:border-border p-4">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={cn("mt-1 font-serif text-2xl font-semibold tabular-nums", accent)}>{value}</p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
