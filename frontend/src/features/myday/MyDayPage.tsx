import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlarmClock, CheckCircle2, Flag } from "lucide-react";
import { Link } from "react-router";
import { toast } from "sonner";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate, toISODate } from "@/lib/format";
import { api } from "@/services/api";

interface DayTask { id: number; title: string; status: string; due_date: string | null; project_name: string; is_flagged: boolean; assignee_id: number | null }
interface MyDay {
  today: string;
  stats: Record<string, number>;
  tasks_today: DayTask[]; tasks_overdue: DayTask[]; tasks_in_progress: DayTask[];
  meeting_action_items: { id: number; title: string; due_date: string | null; meeting_id: number; meeting_title: string }[];
  ai_insights: { id: number; title: string; summary?: string }[];
}

const KEY = ["me", "today"];
const STAT_LABELS: Record<string, string> = {
  due_today: "Échéance aujourd'hui", overdue: "En retard", in_progress: "En cours", unread_notifs: "Notifications non lues",
};

function TaskList({ title, tasks, tone }: { title: string; tasks: DayTask[]; tone?: string }) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: KEY });
  const done = useMutation({
    mutationFn: (id: number) => api(`tasks/${id}/toggle-complete/`, { method: "POST", body: {} }),
    onSuccess: () => { toast.success("Tâche terminée."); void refresh(); }, onError: (e) => toast.error(e.message),
  });
  const snooze = useMutation({
    mutationFn: (id: number) => {
      const d = new Date(); d.setDate(d.getDate() + 1);
      return api(`tasks/${id}/snooze/`, { method: "POST", body: { until: toISODate(d) } });
    },
    onSuccess: () => { toast.success("Tâche reportée à demain."); void refresh(); }, onError: (e) => toast.error(e.message),
  });
  return (
    <Card>
      <CardHeader><CardTitle className={tone}>{title} ({tasks.length})</CardTitle></CardHeader>
      <CardContent>
        {!tasks.length ? <p className="text-sm text-muted-foreground">Rien ici.</p> : (
          <ul className="divide-y">
            {tasks.map((t) => (
              <li key={t.id} className="flex items-center gap-2 py-2 text-sm">
                {t.is_flagged && <Flag className="size-3.5 text-destructive" aria-label="Signalée" />}
                <span className="min-w-0 flex-1"><Link className="font-medium hover:text-brand" to={`/tasks/${t.id}`}>{t.title}</Link>
                  <span className="block truncate text-xs text-muted-foreground">{t.project_name} · échéance {formatDate(t.due_date)}</span></span>
                <Button size="icon" variant="ghost" aria-label={`Reporter « ${t.title} » à demain`} disabled={snooze.isPending} onClick={() => snooze.mutate(t.id)}><AlarmClock /></Button>
                <Button size="icon" variant="ghost" aria-label={`Terminer « ${t.title} »`} disabled={done.isPending} onClick={() => done.mutate(t.id)}><CheckCircle2 /></Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/** Ma journée : même service que /my-day/ (MyDayService), actions rapides réservées à l'assigné côté Django. */
export function MyDayPage() {
  const day = useQuery({ queryKey: KEY, queryFn: ({ signal }) => api<MyDay>("me/today/", { signal }) });
  if (day.isPending) return <PageSkeleton />;
  if (day.isError) return <ErrorState message={day.error.message} onRetry={() => void day.refetch()} />;
  const d = day.data;
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Focus" title="Ma journée" description={formatDate(d.today)} />
      <section aria-label="Indicateurs" className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {Object.entries(d.stats).map(([k, v]) => (
          <Card key={k}><CardContent className="pt-5"><p className="text-xs text-muted-foreground">{STAT_LABELS[k] ?? k.replace(/_/g, " ")}</p><p className="font-serif text-2xl font-semibold tabular-nums">{v}</p></CardContent></Card>
        ))}
      </section>
      <div className="grid gap-6 xl:grid-cols-2">
        <TaskList title="En retard" tasks={d.tasks_overdue} tone="text-destructive" />
        <TaskList title="Aujourd'hui" tasks={d.tasks_today} />
        <TaskList title="En cours" tasks={d.tasks_in_progress} />
        <Card>
          <CardHeader><CardTitle>Actions de réunion ({d.meeting_action_items.length})</CardTitle></CardHeader>
          <CardContent>
            {!d.meeting_action_items.length ? <p className="text-sm text-muted-foreground">Aucune action en attente.</p> : (
              <ul className="space-y-2 text-sm">{d.meeting_action_items.map((a) => (
                <li key={a.id}><p className="font-medium">{a.title}</p><p className="text-xs text-muted-foreground"><Link className="hover:text-brand" to={`/m/meeting/${a.meeting_id}`}>{a.meeting_title}</Link>{a.due_date ? ` · ${formatDate(a.due_date)}` : ""}</p></li>
              ))}</ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
