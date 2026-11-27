import { Dialog } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/misc";
import { useTaskOverview } from "./api";
import { QuickUpdatePanel } from "./QuickUpdatePanel";

/**
 * Mise à jour rapide d'une tâche (statut, avancement, temps du jour, commentaire) : même
 * panneau et mêmes règles que la fiche tâche (assigné uniquement), ouvert depuis la fiche
 * projet ou le timesheet. Les écrans qui montrent la tâche sont invalidés ensemble.
 */
export function QuickUpdateDialog({ taskId, title, onClose }: { taskId: number; title: string; onClose: () => void }) {
  const overview = useTaskOverview(taskId);
  const o = overview.data;
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title="Mise à jour rapide" description={title}>
      {o ? <QuickUpdatePanel key={`${o.state.status}-${o.state.progress_percent}-${o.state.spent_hours}`} taskId={taskId} state={o.state} />
        : overview.isError ? <p className="text-sm text-destructive">{overview.error.message}</p> : <Skeleton className="h-40" />}
    </Dialog>
  );
}
