import {
  DndContext, KeyboardSensor, PointerSensor, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent,
} from "@dnd-kit/core";
import { useQueryClient } from "@tanstack/react-query";
import { Flag } from "lucide-react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Avatar } from "@/components/ui/misc";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Paginated } from "@/types/api";
import { TASKS_KEY, useMoveTask, type Task } from "./api";
import { STATUS_COLUMNS, isOverdue } from "./constants";

function Card({ task, meId }: { task: Task; meId?: number }) {
  const movable = task.assignee === meId;
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: task.id, disabled: !movable, data: task });
  return (
    <li
      ref={setNodeRef}
      style={transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined}
      className={cn("rounded-xl border bg-card p-3 shadow-sm", movable && "cursor-grab", isDragging && "z-10 opacity-80 shadow-lg")}
      {...attributes}
      {...listeners}
      aria-roledescription={movable ? "tâche déplaçable" : "tâche"}
    >
      <Link to={`/tasks/${task.id}`} className="block text-sm font-medium hover:text-primary" onPointerDown={(e) => e.stopPropagation()}>
        {task.is_flagged && <Flag className="mr-1 inline size-3.5 text-destructive" aria-label="Signalée" />}
        {task.title}
      </Link>
      <p className="mt-1 truncate text-xs text-muted-foreground">{task.project_name || "Sans projet"}</p>
      <div className="mt-2 flex items-center gap-2 text-xs">
        {task.assignee_name && <Avatar name={task.assignee_name} className="size-6 text-[10px]" />}
        <span className={cn("ml-auto", isOverdue(task.due_date, task.status) ? "font-semibold text-destructive" : "text-muted-foreground")}>
          {task.due_date ? formatDate(task.due_date) : ""}
        </span>
      </div>
    </li>
  );
}

function Column({ status, label, dot, tasks, meId }: { status: string; label: string; dot: string; tasks: Task[]; meId?: number }) {
  const { setNodeRef, isOver } = useDroppable({ id: status });
  return (
    <section ref={setNodeRef} aria-label={label} className={cn("flex w-72 shrink-0 flex-col rounded-2xl bg-muted/60 p-3", isOver && "ring-2 ring-primary/40")}>
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <span className={cn("size-2.5 rounded-full", dot)} aria-hidden="true" />{label}
        <span className="ml-auto text-xs text-muted-foreground">{tasks.length}</span>
      </h2>
      <ul className="flex min-h-24 flex-col gap-2">{tasks.map((t) => <Card key={t.id} task={t} meId={meId} />)}</ul>
    </section>
  );
}

/** Kanban par statut. Seul l'assigné peut déplacer sa tâche (règle Django, vérifiée par l'API). */
export function TaskBoard({ tasks, meId, queryKey }: { tasks: Task[]; meId?: number; queryKey: readonly unknown[] }) {
  const qc = useQueryClient();
  const move = useMoveTask();
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }), useSensor(KeyboardSensor));

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    const task = active.data.current as Task | undefined;
    const status = over?.id as string | undefined;
    if (!task || !status || status === task.status) return;
    const label = STATUS_COLUMNS.find((c) => c.value === status)?.label ?? status;
    qc.setQueryData<Paginated<Task>>(queryKey, (old) =>
      old ? { ...old, results: old.results.map((t) => (t.id === task.id ? { ...t, status, status_label: label } : t)) } : old);
    move.mutate({ id: task.id, status }, {
      onSuccess: () => toast.success(`« ${task.title} » → ${label}`),
      onError: (e) => { toast.error(e.message); void qc.invalidateQueries({ queryKey: TASKS_KEY }); },
    });
  };

  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <div className="-mx-4 flex gap-4 overflow-x-auto px-4 pb-4 sm:mx-0 sm:px-0">
        {STATUS_COLUMNS.map((c) => (
          <Column key={c.value} status={c.value} label={c.label} dot={c.dot} meId={meId} tasks={tasks.filter((t) => t.status === c.value)} />
        ))}
      </div>
    </DndContext>
  );
}
