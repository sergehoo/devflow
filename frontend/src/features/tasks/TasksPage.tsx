import type { ColumnDef } from "@tanstack/react-table";
import { Flag, KanbanSquare, List, Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { DataTable } from "@/components/data/DataTable";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { useFormSchema } from "@/components/forms/schema";
import { PageHeader, Pagination } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Badge, Skeleton } from "@/components/ui/misc";
import { useMe } from "@/features/auth/api";
import { formatDate } from "@/lib/format";
import { useDebouncedValue } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { TASKS_KEY, useTasks, type Task, type TaskFilters } from "./api";
import { STATUS_BADGE, isOverdue } from "./constants";
import { TaskBoard } from "./TaskBoard";

const columns: ColumnDef<Task, unknown>[] = [
  {
    id: "title", header: "Tâche", meta: { sortKey: "title" },
    cell: ({ row: { original: t } }) => (
      <Link to={`/tasks/${t.id}`} className="font-medium hover:text-brand">
        {t.is_flagged && <Flag className="mr-1 inline size-3.5 text-destructive" aria-label="Signalée" />}{t.title}
      </Link>
    ),
  },
  { id: "project", header: "Projet", meta: { sortKey: "project__name" }, cell: ({ row }) => row.original.project_name || "—" },
  { id: "status", header: "Statut", meta: { sortKey: "status" }, cell: ({ row: { original: t } }) => <Badge className={STATUS_BADGE[t.status]}>{t.status_label}</Badge> },
  { id: "priority", header: "Priorité", meta: { sortKey: "priority" }, cell: ({ row }) => row.original.priority_label },
  { id: "assignee", header: "Assigné à", cell: ({ row }) => row.original.assignee_name || "—" },
  {
    id: "due", header: "Échéance", meta: { sortKey: "due_date" },
    cell: ({ row: { original: t } }) => <span className={cn(isOverdue(t.due_date, t.status) && "font-semibold text-destructive")}>{formatDate(t.due_date)}</span>,
  },
  { id: "progress", header: "Avancement", meta: { sortKey: "progress_percent" }, cell: ({ row }) => `${row.original.progress_percent} %` },
];

export function TasksPage() {
  const { data: me } = useMe();
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "board" ? "board" : "list";
  const [filters, setFilters] = useState<TaskFilters>(() => ({
    search: "", status: params.get("status") ?? "", priority: "", project: params.get("project") ?? "",
    assignee: params.get("assignee") ?? "", is_flagged: "", ordering: "", page: 1,
  }));
  const search = useDebouncedValue(filters.search);
  const query = { ...filters, search, page: view === "board" ? 1 : filters.page };
  const pageSize = view === "board" ? 500 : undefined;
  const { data, isPending, isError, error, refetch } = useTasks(query, pageSize);
  const schema = useFormSchema("task");
  const choices = useMemo(() => Object.fromEntries((schema.data?.fields ?? []).map((f) => [f.name, f.choices ?? []])), [schema.data]);
  const set = (patch: Partial<TaskFilters>) => setFilters((f) => ({ ...f, page: 1, ...patch }));
  const mine = me && filters.assignee === String(me.id);
  const newHref = filters.project ? `/tasks/new?project=${filters.project}` : "/tasks/new";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Exécution"
        title="Tâches"
        description={data ? `${data.count} tâche(s)` : undefined}
        actions={
          <>
            <div role="group" aria-label="Affichage" className="flex rounded-xl border bg-card p-1">
              {([["list", "Liste", List], ["board", "Kanban", KanbanSquare]] as const).map(([v, label, Icon]) => (
                <Button key={v} size="sm" variant={view === v ? "default" : "ghost"} aria-pressed={view === v}
                  onClick={() => setParams((p) => { p.set("view", v); return p; })}>
                  <Icon />{label}
                </Button>
              ))}
            </div>
            <Button asChild><Link to={newHref}><Plus />Nouvelle tâche</Link></Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[2fr_repeat(4,1fr)]">
        <div className="relative sm:col-span-2 lg:col-span-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden="true" />
          <Input type="search" className="pl-9" placeholder="Titre, description, projet, personne…" aria-label="Rechercher une tâche"
            value={filters.search} onChange={(e) => set({ search: e.target.value })} />
        </div>
        {([["status", "Statut"], ["priority", "Priorité"], ["project", "Projet"], ["assignee", "Assigné à"]] as const).map(([key, label]) => (
          <Select key={key} aria-label={label} value={filters[key]} onChange={(e) => set({ [key]: e.target.value })}>
            <option value="">{label} : tous</option>
            {(choices[key] ?? []).filter((c) => c.value).map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </Select>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {me && (
          <Button size="sm" variant={mine ? "default" : "outline"} aria-pressed={!!mine} onClick={() => set({ assignee: mine ? "" : String(me.id) })}>
            Mes tâches
          </Button>
        )}
        <Button size="sm" variant={filters.is_flagged ? "default" : "outline"} aria-pressed={!!filters.is_flagged}
          onClick={() => set({ is_flagged: filters.is_flagged ? "" : "true" })}>
          <Flag />Signalées
        </Button>
      </div>

      {isPending ? (
        <Skeleton className="h-96" />
      ) : isError ? (
        <ErrorState message={error.message} onRetry={() => void refetch()} />
      ) : view === "board" ? (
        <TaskBoard tasks={data.results} meId={me?.id} queryKey={[...TASKS_KEY, "list", query, pageSize]} />
      ) : data.results.length === 0 ? (
        <EmptyState title="Aucune tâche" description="Aucune tâche ne correspond à ces critères." />
      ) : (
        <>
          <DataTable caption="Liste des tâches" columns={columns} data={data.results} rowKey={(t) => t.id}
            ordering={filters.ordering} onOrderingChange={(ordering) => setFilters((f) => ({ ...f, ordering }))} />
          <Pagination page={filters.page} count={data.count} onPage={(page) => setFilters((f) => ({ ...f, page }))} />
        </>
      )}
    </div>
  );
}
