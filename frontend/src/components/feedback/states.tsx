import { AlertTriangle, Inbox } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-[22px] border border-dashed bg-card/60 p-10 text-center">
      <Inbox className="size-8 text-subtle-foreground" aria-hidden="true" />
      <p className="font-semibold text-foreground">{title}</p>
      {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 p-8 text-center">
      <AlertTriangle className="size-7 text-destructive" aria-hidden="true" />
      <p className="text-sm text-foreground">{message}</p>
      {onRetry && <Button variant="outline" size="sm" onClick={onRetry}>Réessayer</Button>}
    </div>
  );
}

export function PageSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Chargement">
      <Skeleton className="h-9 w-64" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-28" />)}
      </div>
      <Skeleton className="h-72" />
    </div>
  );
}
