import { Plus, Search, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge, Skeleton } from "@/components/ui/misc";
import { useDebouncedValue } from "@/lib/hooks";
import { useTeams } from "./api";

export function TeamsPage() {
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search);
  const { data, isPending, isError, error, refetch } = useTeams(q);
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Organisation" title="Équipes"
        actions={<><Button variant="outline" asChild><Link to="/members"><Users />Membres</Link></Button><Button asChild><Link to="/teams/new"><Plus />Nouvelle équipe</Link></Button></>} />
      <div className="relative max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden="true" />
        <Input type="search" className="pl-9" placeholder="Rechercher une équipe…" aria-label="Rechercher une équipe" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      {isPending ? <Skeleton className="h-64" /> : isError ? <ErrorState message={error.message} onRetry={() => void refetch()} /> : data.results.length === 0 ? (
        <EmptyState title="Aucune équipe" />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {data.results.map((t) => (
            <li key={t.id}>
              <Link to={`/teams/${t.id}`} className="group block h-full">
                <Card className="h-full transition-shadow group-hover:shadow-md">
                  <CardContent className="space-y-3">
                    <div className="flex items-center gap-3">
                      <span className="size-3 shrink-0 rounded-full" style={{ backgroundColor: t.color || "#7C6FF7" }} aria-hidden="true" />
                      <p className="truncate font-semibold group-hover:text-primary">{t.name}</p>
                      <Badge className="ml-auto">{t.team_type_label}</Badge>
                      {!t.is_active && <Badge>Inactive</Badge>}
                    </div>
                    {t.description && <p className="line-clamp-2 text-sm text-muted-foreground">{t.description}</p>}
                    <p className="text-xs text-muted-foreground">Lead : {t.lead_name || "—"} · {t.members_count ?? 0} membre(s) · {t.projects_count ?? 0} projet(s)</p>
                  </CardContent>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
