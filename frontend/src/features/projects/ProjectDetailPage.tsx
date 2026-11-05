import { Archive, ExternalLink, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Avatar, Badge } from "@/components/ui/misc";
import { useMe } from "@/features/auth/api";
import { formatDate, formatHours, formatMoney } from "@/lib/format";
import { can } from "@/lib/permissions";
import { legacyUrl } from "@/lib/utils";
import { useProject, useProjectAction, useProjectSummary } from "./api";
import { HEALTH } from "./constants";
import { BudgetPanel, MethodologySpace } from "./ProjectPanels";

export function ProjectDetailPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const { data: me } = useMe();
  const { data: p, isPending, isError, error, refetch } = useProject(id);
  const summary = useProjectSummary(id);
  const action = useProjectAction();
  const [confirm, setConfirm] = useState<"archive" | "delete" | null>(null);

  if (isPending) return <PageSkeleton />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;

  const run = (kind: "archive" | "delete") =>
    action.mutate({ id, action: kind }, {
      onSuccess: () => { toast.success(kind === "archive" ? "Projet archivé." : "Projet supprimé."); navigate("/projects"); },
      onError: (e) => toast.error(e.message),
      onSettled: () => setConfirm(null),
    });

  const s = summary.data;
  const info: [string, string][] = [
    ["Méthodologie", p.methodology_label], ["Équipe", p.team_name || "—"], ["Responsable", p.owner_name || "—"],
    ["Product manager", p.product_manager_name || "—"], ["Début", formatDate(p.start_date)], ["Échéance", formatDate(p.target_date)],
    ["Livré le", formatDate(p.delivered_at)], ["Budget", p.budget ? formatMoney(p.budget) : "—"], ["Stack", p.tech_stack || "—"],
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={p.code || "Projet"}
        title={p.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge>{p.status_label}</Badge>
            <Badge className={HEALTH[p.health_status]}>Santé : {p.health_status_label}</Badge>
            <Badge>Priorité {p.priority_label}</Badge>
            {p.risk_score ? <Badge className={p.risk_score >= 70 ? "bg-destructive/10 text-destructive" : ""}>Risque {p.risk_score}{p.ai_risk_label ? ` · ${p.ai_risk_label}` : ""}</Badge> : null}
          </span>
        }
        actions={
          <>
            <Button variant="outline" asChild><a href={legacyUrl(`/projects/${id}/`)}><ExternalLink />Fiche complète</a></Button>
            <Button variant="outline" asChild><Link to={`/projects/${id}/edit`}><Pencil />Modifier</Link></Button>
            <Button variant="outline" onClick={() => setConfirm("archive")}><Archive />Archiver</Button>
            {can(me?.permissions, "project.delete") && <Button variant="destructive" onClick={() => setConfirm("delete")}><Trash2 />Supprimer</Button>}
          </>
        }
      />

      <section aria-label="Indicateurs" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Avancement", `${p.progress_percent} %`],
          ["Tâches", s ? `${s.tasks_total}` : "…", s ? `${s.tasks_overdue} en retard` : ""],
          ["Heures passées", s ? formatHours(s.spent_hours) : "…", s ? `sur ${formatHours(s.estimate_hours)} estimées` : ""],
          ["Membres", s ? `${s.members.length}` : "…"],
        ].map(([label, value, hint]) => (
          <Card key={label}><CardContent>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
            <p className="mt-1 font-serif text-2xl font-semibold tabular-nums">{value}</p>
            {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
          </CardContent></Card>
        ))}
      </section>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader><CardTitle>Informations</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {p.description && <p className="whitespace-pre-line text-sm text-muted-foreground">{p.description}</p>}
            <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
              {info.map(([k, v]) => <div key={k}><dt className="text-xs text-muted-foreground">{k}</dt><dd className="font-medium">{v}</dd></div>)}
            </dl>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Tâches par statut</CardTitle></CardHeader>
          <CardContent>
            {s ? (
              <ul className="space-y-2 text-sm">
                {s.tasks_by_status.filter((t) => t.count).map((t) => (
                  <li key={t.status} className="flex justify-between"><span className="text-muted-foreground">{t.label}</span><span className="font-semibold tabular-nums">{t.count}</span></li>
                ))}
                {!s.tasks_total && <li className="text-muted-foreground">Aucune tâche.</li>}
              </ul>
            ) : <p className="text-sm text-muted-foreground">Chargement…</p>}
            <Button variant="link" className="mt-3 h-auto p-0" asChild><Link to={`/tasks?project=${id}`}>Voir les tâches</Link></Button>
          </CardContent>
        </Card>
      </div>

      <MethodologySpace projectId={id} />
      <BudgetPanel projectId={id} />

      <Card>
        <CardHeader><CardTitle>Membres du projet</CardTitle></CardHeader>
        <CardContent>
          {s?.members.length ? (
            <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {s.members.map((m) => (
                <li key={m.id} className="flex items-center gap-3">
                  <Avatar name={m.name} className="size-9" />
                  <div className="min-w-0"><p className="truncate text-sm font-medium">{m.name}</p><p className="truncate text-xs text-muted-foreground">{[m.role, m.team, `${m.allocation_percent} %`].filter(Boolean).join(" · ")}</p></div>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-muted-foreground">{summary.isPending ? "Chargement…" : "Aucun membre."}</p>}
        </CardContent>
      </Card>

      <ConfirmDialog open={confirm === "archive"} onOpenChange={(o) => !o && setConfirm(null)} pending={action.isPending}
        title="Archiver ce projet ?" description="Il disparaît des listes ; ses données sont conservées." confirmLabel="Archiver" onConfirm={() => run("archive")} />
      <ConfirmDialog open={confirm === "delete"} onOpenChange={(o) => !o && setConfirm(null)} pending={action.isPending} destructive
        title="Supprimer définitivement ce projet ?" description="Tâches, budget et historique liés seront supprimés. Action irréversible." confirmLabel="Supprimer" onConfirm={() => run("delete")} />
    </div>
  );
}
