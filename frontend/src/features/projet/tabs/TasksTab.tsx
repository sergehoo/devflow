import { KanbanSquare, List, Plus, UserRoundCog, Zap } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/misc";
import { useTaskOverview } from "@/features/tasks/api";
import { STATUS_BADGE, isOverdue } from "@/features/tasks/constants";
import { QuickUpdatePanel } from "@/features/tasks/QuickUpdatePanel";
import { ReassignDialog } from "@/features/tasks/TaskDetailPage";
import { formatDate, formatHours } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useInvalidateProject, type TasksTab as Data } from "../api";
import { ActionBar, EmptyLine, Pill, Section, Stat, StatGrid, Table, Td } from "../ui";
import { DependencyList } from "./PlanningTab";

/** Mise à jour rapide (même panneau et mêmes règles que la fiche tâche : assigné uniquement). */
function QuickUpdateDialog({ taskId, title, onClose }: { taskId: number; title: string; onClose: () => void }) {
  const overview = useTaskOverview(taskId);
  const o = overview.data;
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title="Mise à jour rapide" description={title}>
      {o ? <QuickUpdatePanel key={`${o.state.status}-${o.state.progress_percent}-${o.state.spent_hours}`} taskId={taskId} state={o.state} />
        : overview.isError ? <p className="text-sm text-destructive">{overview.error.message}</p> : <Skeleton className="h-40" />}
    </Dialog>
  );
}

/** Board Kanban du projet (colonnes configurées) : section « Board Kanban » de l'ancienne fiche. */
function ProjectBoard({ data }: { data: Data }) {
  const byId = new Map(data.tasks.map((t) => [t.id, t]));
  return (
    <Section title="Board Kanban" description="Vue opérationnelle par colonnes du projet" count={data.board.length}>
      <div className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-1">
        {data.board.map((col) => (
          <div key={col.id} className={cn("w-64 shrink-0 rounded-xl border bg-muted/30 p-2.5", col.over_wip && "border-destructive/50")}>
            <p className="flex items-center justify-between gap-2 text-[11px] font-semibold uppercase tracking-wide">
              <span className="truncate">{col.name}</span>
              <span className={col.over_wip ? "text-destructive" : "text-muted-foreground"} title={col.over_wip ? "Limite WIP dépassée" : undefined}>
                {col.count}{col.wip_limit != null ? ` / ${col.wip_limit}` : ""}
              </span>
            </p>
            {col.task_ids.length ? (
              <ul className="mt-2 max-h-96 space-y-1.5 overflow-y-auto">
                {col.task_ids.map((id) => byId.get(id)).filter((t): t is Data["tasks"][number] => !!t).map((t) => (
                  <li key={t.id} className="rounded-lg border bg-card p-2 text-xs">
                    <Link to={`/tasks/${t.id}`} className="line-clamp-2 font-medium hover:text-brand">{t.title}</Link>
                    <p className={cn("mt-0.5 truncate text-[11px] text-muted-foreground", isOverdue(t.due_date, t.status) && "text-destructive")}>
                      {[t.assignee, t.priority_label, t.due_date ? formatDate(t.due_date) : ""].filter(Boolean).join(" · ")}
                    </p>
                  </li>
                ))}
              </ul>
            ) : <p className="mt-2 text-xs text-muted-foreground">{col.mapped_status ? "Aucune tâche." : "Colonne sans statut associé."}</p>}
          </div>
        ))}
      </div>
    </Section>
  );
}

/** Onglet Tâches : indicateurs, board Kanban, liste complète (réaffectation, mise à jour rapide), dépendances. */
export function TasksTab({ projectId, data }: { projectId: number; data: Data }) {
  const invalidate = useInvalidateProject(projectId);
  const [dialog, setDialog] = useState<{ kind: "reassign" | "update"; id: number; title: string } | null>(null);
  const close = () => { setDialog(null); void invalidate(); };
  const s = data.stats;
  return (
    <div className="space-y-6">
      <ActionBar title="Actions rapides · Tâches" description="Création et pilotage du backlog opérationnel.">
        <Button size="sm" asChild><Link to={`/tasks/new?project=${projectId}`}><Plus />Nouvelle tâche</Link></Button>
        <Button size="sm" variant="outline" asChild><Link to={`/tasks?project=${projectId}`}><List />Voir toutes les tâches</Link></Button>
        <Button size="sm" variant="outline" asChild><Link to={`/tasks?project=${projectId}&view=board`}><KanbanSquare />Voir le board</Link></Button>
      </ActionBar>

      <StatGrid>
        <Stat label="Total" value={s.total} />
        <Stat label="En retard" value={<span className={s.overdue ? "text-destructive" : undefined}>{s.overdue}</span>} />
        <Stat label="Charge estimée" value={formatHours(s.total_estimate_hours)} />
        <Stat label="Temps passé" value={formatHours(s.total_spent_hours)} />
        <Stat label="À faire" value={s.todo} />
        <Stat label="En cours" value={s.in_progress} />
        <Stat label="Review" value={s.review} />
        <Stat label="Bloquées" value={s.blocked} />
      </StatGrid>

      {data.has_board && data.board.length > 0 && <ProjectBoard data={data} />}

      <Section title="Liste des tâches" description="Backlog détaillé du projet" count={data.tasks.length}>
        {data.tasks.length ? (
          <Table caption="Tâches du projet" minWidth="min-w-[860px]" head={["Tâche", "Statut", "Priorité", "Assigné à", "Estimation", "Passé", "Échéance"]}>
            {data.tasks.map((t) => (
              <tr key={t.id} className="hover:bg-muted/40">
                <Td className="min-w-56">
                  <Link to={`/tasks/${t.id}`} className="font-medium hover:text-brand">{t.title}</Link>
                  {t.backlog_item && <span className="block text-xs text-muted-foreground">Backlog : {t.backlog_item}</span>}
                  {t.parent && <span className="block text-xs text-muted-foreground">Parent : {t.parent_id ? <Link to={`/tasks/${t.parent_id}`} className="hover:text-brand">{t.parent}</Link> : t.parent}</span>}
                </Td>
                <Td><Pill className={STATUS_BADGE[t.status]}>{t.status_label}</Pill></Td>
                <Td className="text-muted-foreground">{t.priority_label}</Td>
                <Td>
                  <span className="block">{t.assignee || "—"}</span>
                  <span className="mt-1 flex gap-1">
                    <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => setDialog({ kind: "reassign", id: t.id, title: t.title })}
                      aria-label={`Réaffecter « ${t.title} »`}><UserRoundCog />Réaffecter</Button>
                    <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => setDialog({ kind: "update", id: t.id, title: t.title })}
                      aria-label={`Mise à jour rapide de « ${t.title} »`}><Zap /></Button>
                  </span>
                </Td>
                <Td className="text-right tabular-nums">{formatHours(t.estimate_hours)}</Td>
                <Td className="text-right tabular-nums">{formatHours(t.spent_hours)}</Td>
                <Td className={cn("whitespace-nowrap", isOverdue(t.due_date, t.status) && "font-semibold text-destructive")}>{formatDate(t.due_date)}</Td>
              </tr>
            ))}
          </Table>
        ) : <EmptyLine>Aucune tâche pour ce projet.</EmptyLine>}
      </Section>

      <Section title="Dépendances entre tâches" description="Vue des relations critiques" count={data.dependencies.count}>
        <DependencyList deps={data.dependencies} />
      </Section>

      {dialog?.kind === "reassign" && <ReassignDialog taskId={dialog.id} open onOpenChange={(v) => !v && close()} />}
      {dialog?.kind === "update" && <QuickUpdateDialog taskId={dialog.id} title={dialog.title} onClose={close} />}
    </div>
  );
}
