import { Building2, Plus, Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { PageHeader, Pagination } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge, Skeleton } from "@/components/ui/misc";
import { useDebouncedValue } from "@/lib/hooks";
import { useWorkspaces } from "./api";

export function WorkspacesPage() {
  const [search, setSearch] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [page, setPage] = useState(1);
  const debounced = useDebouncedValue(search);
  const { data, isPending, isError, error, refetch } = useWorkspaces({ search: debounced, includeArchived, page });

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Organisation"
        title="Workspaces"
        description="Espaces de travail auxquels vous avez accès."
        actions={<Button asChild><Link to="/workspaces/new"><Plus />Nouveau workspace</Link></Button>}
      />

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-60 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden="true" />
          <Input
            type="search" value={search} placeholder="Rechercher un workspace…" aria-label="Rechercher un workspace"
            className="pl-9" onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" className="size-4 accent-primary" checked={includeArchived}
            onChange={(e) => { setIncludeArchived(e.target.checked); setPage(1); }} />
          Inclure les archivés
        </label>
      </div>

      {isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-40" />)}</div>
      ) : isError ? (
        <ErrorState message={error.message} onRetry={() => void refetch()} />
      ) : data.results.length === 0 ? (
        <EmptyState title="Aucun workspace" description={search ? "Aucun résultat pour cette recherche." : undefined} />
      ) : (
        <>
          <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.results.map((ws) => (
              <li key={ws.id}>
                <Link to={`/workspaces/${ws.id}`} className="group block h-full">
                  <Card className="h-full transition-shadow group-hover:shadow-md">
                    <CardContent className="space-y-3">
                      <div className="flex items-center gap-3">
                        {ws.logo ? (
                          <img src={ws.logo} alt="" className="size-10 rounded-xl object-cover" />
                        ) : (
                          <span className="flex size-10 items-center justify-center rounded-xl text-white" style={{ backgroundColor: ws.accent_color || "#F4722B" }}>
                            <Building2 className="size-5" aria-hidden="true" />
                          </span>
                        )}
                        <div className="min-w-0">
                          <p className="truncate font-semibold group-hover:text-brand">{ws.name}</p>
                          <p className="truncate text-xs text-muted-foreground">{ws.owner_name}{ws.quarter_label ? ` · ${ws.quarter_label}` : ""}</p>
                        </div>
                        {ws.is_archived ? <Badge className="ml-auto">Archivé</Badge> : !ws.is_active ? <Badge className="ml-auto">Inactif</Badge> : null}
                      </div>
                      {ws.description && <p className="line-clamp-2 text-sm text-muted-foreground">{ws.description}</p>}
                      <dl className="grid grid-cols-3 gap-2 text-center">
                        {([["Projets", ws.projects_count], ["Équipes", ws.teams_count], ["Membres", ws.memberships_count]] as const).map(([k, v]) => (
                          <div key={k} className="rounded-xl bg-muted/60 py-2">
                            <dd className="font-semibold tabular-nums">{v ?? 0}</dd>
                            <dt className="text-[11px] text-muted-foreground">{k}</dt>
                          </div>
                        ))}
                      </dl>
                    </CardContent>
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
          <Pagination page={page} count={data.count} onPage={setPage} />
        </>
      )}
    </div>
  );
}
