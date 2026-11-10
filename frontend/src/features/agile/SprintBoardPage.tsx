import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { toast } from "sonner";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { useMe } from "@/features/auth/api";
import type { Task } from "@/features/tasks/api";
import { TaskBoard } from "@/features/tasks/TaskBoard";
import { formatDate } from "@/lib/format";
import { api } from "@/services/api";
import type { Paginated } from "@/types/api";

interface Sprint { id: number; name: string; status: string; status_label?: string; start_date: string; end_date: string; goal?: string; project: number; project_name?: string }

const STATUSES = [["PLANNED", "Planifié"], ["ACTIVE", "Actif"], ["REVIEW", "En revue"], ["DONE", "Terminé"], ["CANCELLED", "Annulé"]] as const;

/** Board d'un sprint : tâches du sprint (Kanban existant) + statut du sprint (RBAC sprint.edit côté Django). */
export function SprintBoardPage() {
  const id = Number(useParams().id);
  const { data: me } = useMe();
  const qc = useQueryClient();
  const sprint = useQuery({ queryKey: ["sprints", id], queryFn: ({ signal }) => api<Sprint>(`sprints/${id}/`, { signal }) });
  const tasksKey = ["tasks", "sprint-board", id] as const;
  const tasks = useQuery({ queryKey: tasksKey, queryFn: ({ signal }) => api<Paginated<Task>>("tasks/", { signal, params: { sprint: id, page_size: 200, is_archived: "false" } }) });
  const status = useMutation({
    mutationFn: (value: string) => api<Sprint>(`sprints/${id}/status/`, { method: "POST", body: { status: value } }),
    onSuccess: () => { toast.success("Statut du sprint mis à jour."); void qc.invalidateQueries({ queryKey: ["sprints", id] }); },
    onError: (e) => toast.error(e.message),
  });
  if (sprint.isPending || tasks.isPending) return <PageSkeleton />;
  if (sprint.isError) return <ErrorState message={sprint.error.message} onRetry={() => void sprint.refetch()} />;
  if (tasks.isError) return <ErrorState message={tasks.error.message} onRetry={() => void tasks.refetch()} />;
  const s = sprint.data;
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Sprint" title={s.name} description={`${formatDate(s.start_date)} → ${formatDate(s.end_date)}${s.goal ? ` · ${s.goal}` : ""}`}
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            <label className="sr-only" htmlFor="sprint-status">Statut du sprint</label>
            <Select id="sprint-status" className="h-10 w-44" value={s.status} disabled={status.isPending} onChange={(e) => status.mutate(e.target.value)}>
              {STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </Select>
            <Button asChild variant="outline"><Link to={`/m/sprint/${id}`}>Fiche du sprint</Link></Button>
            <Button asChild variant="outline"><Link to={`/projects/${s.project}`}>Projet</Link></Button>
          </div>
        )} />
      <TaskBoard tasks={tasks.data.results} meId={me?.id} queryKey={tasksKey} />
    </div>
  );
}
