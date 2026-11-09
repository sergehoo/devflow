import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-brand">{eyebrow}</p>}
        <h1 className="mt-1 text-[28px] font-semibold leading-tight tracking-tight sm:text-[34px]">{title}</h1>
        {description && <p className="mt-1.5 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Pagination({ page, count, pageSize = 25, onPage }: { page: number; count: number; pageSize?: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  if (pages <= 1) return null;
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
      <span>{count} élément(s) · page {page} / {pages}</span>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft />Précédent</Button>
        <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>Suivant<ChevronRight /></Button>
      </div>
    </nav>
  );
}
