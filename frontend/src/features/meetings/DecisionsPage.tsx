import { LayoutDashboard } from "lucide-react";
import { Link, useSearchParams } from "react-router";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { Badge, Skeleton } from "@/components/ui/misc";
import { useDecisions } from "./api";
import { DECISION_STATUS_BADGE, fmtDate } from "./constants";

/** Registre transversal des décisions (`MeetingDecisionListView` : filtres statut / catégorie, 200 max). */
export function DecisionsPage() {
  const [search, setSearch] = useSearchParams();
  const params = Object.fromEntries(search);
  const list = useDecisions(params);
  const set = (key: string, value: string) => setSearch((s) => { if (value) s.set(key, value); else s.delete(key); return s; });
  const filtered = Boolean(search.get("status") || search.get("category"));
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Réunions" title="Registre des décisions" description="Toutes les décisions prises en réunion, par statut et catégorie."
        actions={<Button variant="outline" asChild><Link to="/meetings/dashboard"><LayoutDashboard />Vue d'ensemble</Link></Button>} />
      <div className="flex flex-wrap items-end gap-2">
        <Select aria-label="Statut" className="w-auto min-w-44 flex-1 sm:flex-none" value={search.get("status") ?? ""} onChange={(e) => set("status", e.target.value)}>
          <option value="">Tous les statuts</option>
          {list.data?.status_choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </Select>
        <Select aria-label="Catégorie" className="w-auto min-w-44 flex-1 sm:flex-none" value={search.get("category") ?? ""} onChange={(e) => set("category", e.target.value)}>
          <option value="">Toutes les catégories</option>
          {list.data?.category_choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </Select>
        {filtered && <Button variant="ghost" size="sm" onClick={() => setSearch({})}>Réinitialiser</Button>}
      </div>
      {list.isPending ? <Skeleton className="h-72" /> : list.isError ? <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />
        : !list.data.results.length ? <EmptyState title="Aucune décision" description={filtered ? "Aucune décision pour ce filtre." : "Aucune décision enregistrée."} />
          : (
            <>
              <ul className="divide-y overflow-hidden rounded-[22px] border border-transparent bg-card shadow-card dark:border-border">
                {list.data.results.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-start gap-3 px-4 py-3">
                    <div className="min-w-0 flex-1 basis-64">
                      <p className="text-sm font-medium">{d.title}</p>
                      {d.description && <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">{d.description}</p>}
                      {d.projects.length > 0 && (
                        <p className="mt-1 flex flex-wrap gap-x-2 text-[11px]">
                          {d.projects.map((p) => <Link key={p.id} to={`/projects/${p.id}`} className="text-brand hover:underline">{p.name}</Link>)}
                        </p>
                      )}
                    </div>
                    <span className="w-28 text-xs text-muted-foreground">{d.category_label}</span>
                    <Badge className={DECISION_STATUS_BADGE[d.status]}>{d.status_label}</Badge>
                    <span className="w-32 text-xs text-muted-foreground">{d.decided_by || "—"}</span>
                    <span className="w-40 min-w-0 truncate text-xs">
                      {d.meeting ? <Link to={`/meetings/${d.meeting.id}`} className="text-brand hover:underline">{d.meeting.title}</Link> : "—"}
                    </span>
                    <span className="text-xs text-muted-foreground">{fmtDate(d.decided_at)}</span>
                  </li>
                ))}
              </ul>
              <p className="text-right text-[11px] text-muted-foreground">{list.data.count} décision(s) affichée(s) (max 200)</p>
            </>
          )}
    </div>
  );
}
