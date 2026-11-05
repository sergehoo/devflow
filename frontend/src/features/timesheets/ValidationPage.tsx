import { Check, Eye, X } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { toast } from "sonner";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { PageHeader, Pagination } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Label, Select, Textarea } from "@/components/ui/input";
import { Badge, Skeleton } from "@/components/ui/misc";
import { formatDate, formatHours } from "@/lib/format";
import { useWeekAction, useWeeks, type WeekGroup } from "./api";
import { APPROVAL_STATUSES, STATUS_TONE, statusLabel } from "./constants";
import { TimesheetTabs } from "./TimesheetNav";

/** Suivi des validations : semaines visibles (soi + subordonnés), validation/rejet réservés au N+1 direct (`can_review`). */
export function ValidationPage() {
  const [params] = useSearchParams(); // liens de notification : ?scope=all&status=
  const [status, setStatus] = useState(params.get("status") ?? "SUBMITTED");
  const [scope, setScope] = useState<"review" | "all">(params.get("scope") === "all" ? "all" : "review");
  const [page, setPage] = useState(1);
  const { data, isPending, isError, error, refetch } = useWeeks({ status, scope: scope === "review" ? "review" : undefined, page });
  const action = useWeekAction();
  const [rejecting, setRejecting] = useState<WeekGroup | null>(null);
  const [comment, setComment] = useState("");

  const run = (g: WeekGroup, kind: "approve" | "reject") =>
    action.mutate({ user: g.user.id, monday: g.monday, action: kind, comment }, {
      onSuccess: (r) => { (r.messages?.length ? r.messages : ["Semaine traitée."]).forEach((m) => toast.success(m)); setRejecting(null); setComment(""); },
      onError: (e) => toast.error(e.message),
    });

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Timesheets" title="Validation des timesheets" description="Seul le manager direct (N+1) peut valider ou rejeter une semaine." />
      <TimesheetTabs />
      <div className="flex flex-wrap gap-3">
        <div role="group" aria-label="Périmètre" className="flex rounded-xl border bg-card p-1">
          {([["review", "À valider par moi"], ["all", "Toutes les semaines visibles"]] as const).map(([v, l]) => (
            <Button key={v} size="sm" variant={scope === v ? "default" : "ghost"} aria-pressed={scope === v} onClick={() => { setScope(v); setPage(1); }}>{l}</Button>
          ))}
        </div>
        <Select aria-label="Statut" className="w-56" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">Statut : tous</option>{APPROVAL_STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </Select>
      </div>

      {isPending ? <Skeleton className="h-72" /> : isError ? <ErrorState message={error.message} onRetry={() => void refetch()} /> : data.results.length === 0 ? (
        <EmptyState title="Rien à traiter" description="Aucune semaine ne correspond à ces critères." />
      ) : (
        <>
          <div className="overflow-x-auto rounded-2xl border bg-card">
            <table className="w-full min-w-[760px] text-sm">
              <caption className="sr-only">Semaines à valider</caption>
              <thead className="border-b bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>{["Collaborateur", "Semaine", "Heures", "Saisies", "Statut", ""].map((h) => <th key={h} scope="col" className="px-4 py-3 font-semibold">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y">
                {data.results.map((g) => (
                  <tr key={`${g.user.id}-${g.monday}`}>
                    <td className="px-4 py-2.5 font-medium">{g.user.name}{g.is_mine && <Badge className="ml-2">Moi</Badge>}</td>
                    <td className="px-4 py-2.5">S{g.iso_week} · {formatDate(g.monday)} → {formatDate(g.sunday)}</td>
                    <td className="px-4 py-2.5 font-semibold tabular-nums">{formatHours(g.total_hours)}</td>
                    <td className="px-4 py-2.5 tabular-nums">{g.entry_count}</td>
                    <td className="px-4 py-2.5"><Badge className={STATUS_TONE[g.status]}>{statusLabel(g.status, g.status_label)}</Badge></td>
                    <td className="px-4 py-2.5">
                      <span className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" asChild><Link to={`/timesheets?${g.is_mine ? "" : `user=${g.user.id}&`}date=${g.monday}`}><Eye />Voir</Link></Button>
                        {g.can_review && g.status === "SUBMITTED" && (
                          <>
                            <Button size="sm" disabled={action.isPending} onClick={() => run(g, "approve")}><Check />Valider</Button>
                            <Button size="sm" variant="destructive" onClick={() => setRejecting(g)}><X />Rejeter</Button>
                          </>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} count={data.count} onPage={setPage} />
        </>
      )}

      <Dialog open={!!rejecting} onOpenChange={(o) => !o && setRejecting(null)} title="Rejeter la semaine"
        description={rejecting ? `${rejecting.user.name} — semaine ${rejecting.iso_week}. Le commentaire est obligatoire.` : undefined}>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (rejecting) run(rejecting, "reject"); }}>
          <div><Label htmlFor="reject-comment">Commentaire *</Label><Textarea id="reject-comment" rows={3} required value={comment} onChange={(e) => setComment(e.target.value)} /></div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setRejecting(null)}>Annuler</Button>
            <Button type="submit" variant="destructive" disabled={!comment.trim() || action.isPending}>Rejeter</Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
