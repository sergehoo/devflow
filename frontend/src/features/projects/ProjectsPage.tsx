import type { ColumnDef } from "@tanstack/react-table";
import { FileUp, Plus, Search, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { DataTable } from "@/components/data/DataTable";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { useFormSchema } from "@/components/forms/schema";
import { PageHeader, Pagination } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Badge, Skeleton } from "@/components/ui/misc";
import { ExportTrackingButton } from "@/features/pilotage/ExportTrackingButton";
import { formatDate } from "@/lib/format";
import { useDebouncedValue } from "@/lib/hooks";
import { useProjects, type Project, type ProjectFilters } from "./api";
import { HEALTH } from "./constants";

const columns: ColumnDef<Project, unknown>[] = [
  {
    id: "name", header: "Projet", meta: { sortKey: "name" },
    cell: ({ row: { original: p } }) => (
      <Link to={`/projects/${p.id}`} className="font-medium hover:text-brand">
        {p.name}{p.code && <span className="ml-1.5 text-xs text-muted-foreground">{p.code}</span>}
      </Link>
    ),
  },
  { id: "status", header: "Statut", meta: { sortKey: "status" }, cell: ({ row }) => <Badge>{row.original.status_label}</Badge> },
  { id: "priority", header: "Priorité", meta: { sortKey: "priority" }, cell: ({ row }) => row.original.priority_label },
  {
    id: "health", header: "Santé",
    cell: ({ row: { original: p } }) => <Badge className={HEALTH[p.health_status]}>{p.health_status_label}</Badge>,
  },
  { id: "team", header: "Équipe", cell: ({ row }) => row.original.team_name || "—" },
  { id: "owner", header: "Responsable", cell: ({ row }) => row.original.owner_name || "—" },
  {
    id: "progress", header: "Avancement", meta: { sortKey: "progress_percent" },
    cell: ({ row: { original: p } }) => (
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary" style={{ width: `${p.progress_percent}%` }} /></div>
        <span className="text-xs tabular-nums">{p.progress_percent} %</span>
      </div>
    ),
  },
  { id: "target", header: "Échéance", meta: { sortKey: "target_date" }, cell: ({ row }) => formatDate(row.original.target_date) },
];

const EMPTY: ProjectFilters = { search: "", status: "", priority: "", health_status: "", team: "", ordering: "-updated_at", page: 1 };

export function ProjectsPage() {
  const [filters, setFilters] = useState<ProjectFilters>(EMPTY);
  const search = useDebouncedValue(filters.search);
  const { data, isPending, isError, error, refetch } = useProjects({ ...filters, search });
  const schema = useFormSchema("project");
  const choices = useMemo(
    () => Object.fromEntries((schema.data?.fields ?? []).map((f) => [f.name, f.choices ?? []])),
    [schema.data],
  );
  const set = (patch: Partial<ProjectFilters>) => setFilters((f) => ({ ...f, page: 1, ...patch }));
  const active = Object.entries(filters).some(([k, v]) => !["page", "ordering"].includes(k) && v);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Pilotage"
        title="Projets"
        description={data ? `${data.count} projet(s)` : undefined}
        actions={<>
          <ExportTrackingButton gated />
          {/* --- ai --- */}
          <Button variant="outline" asChild><Link to="/imports?new=1"><FileUp />Importer un document</Link></Button>
          <Button variant="outline" asChild><Link to="/projects/genesis"><Sparkles />Créer avec l'IA</Link></Button>
          {/* --- fin ai --- */}
          <Button asChild><Link to="/projects/new"><Plus />Nouveau projet</Link></Button>
        </>}
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[2fr_repeat(4,1fr)]">
        <div className="relative sm:col-span-2 lg:col-span-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden="true" />
          <Input type="search" className="pl-9" placeholder="Nom, code, description ou stack…" aria-label="Rechercher un projet"
            value={filters.search} onChange={(e) => set({ search: e.target.value })} />
        </div>
        {([["status", "Statut"], ["priority", "Priorité"], ["health_status", "Santé"], ["team", "Équipe"]] as const).map(([key, label]) => (
          <Select key={key} aria-label={label} value={filters[key]} onChange={(e) => set({ [key]: e.target.value })}>
            <option value="">{label} : tous</option>
            {(choices[key] ?? []).filter((c) => c.value).map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </Select>
        ))}
      </div>
      {active && <Button variant="link" className="h-auto p-0" onClick={() => setFilters(EMPTY)}>Réinitialiser les filtres</Button>}

      {isPending ? (
        <Skeleton className="h-96" />
      ) : isError ? (
        <ErrorState message={error.message} onRetry={() => void refetch()} />
      ) : data.results.length === 0 ? (
        <EmptyState title="Aucun projet" description={active ? "Aucun projet ne correspond aux filtres." : "Créez votre premier projet."} />
      ) : (
        <>
          <DataTable caption="Liste des projets" columns={columns} data={data.results} rowKey={(p) => p.id}
            ordering={filters.ordering} onOrderingChange={(ordering) => setFilters((f) => ({ ...f, ordering }))} />
          <Pagination page={filters.page} count={data.count} onPage={(page) => setFilters((f) => ({ ...f, page }))} />
        </>
      )}
    </div>
  );
}
