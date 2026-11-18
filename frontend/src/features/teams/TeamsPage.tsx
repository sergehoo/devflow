import { FolderKanban, Plus, Search, UserRound, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Avatar, Badge, Skeleton } from "@/components/ui/misc";
import { useDebouncedValue } from "@/lib/hooks";
import { useTeams, type Team } from "./api";

const DEFAULT_COLOR = "#7C6FF7";

function TeamCard({ t }: { t: Team }) {
  const color = t.color || DEFAULT_COLOR;
  return (
    <Link to={`/teams/${t.id}`} className="group block h-full rounded-[22px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <Card className="flex h-full flex-col overflow-hidden transition duration-200 group-hover:-translate-y-0.5 group-hover:shadow-md">
        <div className="h-1.5 shrink-0" style={{ backgroundColor: color }} aria-hidden="true" />
        <div className="flex flex-1 flex-col gap-3 p-5">
          <div className="flex items-start gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-2xl text-sm font-bold text-white" style={{ backgroundColor: color }} aria-hidden="true">
              {t.name.trim().charAt(0).toUpperCase() || "É"}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate font-semibold leading-tight group-hover:text-brand" title={t.name}>{t.name}</p>
              <div className="mt-1 flex flex-wrap gap-1.5">
                <Badge>{t.team_type_label}</Badge>
                {!t.is_active && <Badge className="bg-amber-500/15 text-amber-700 dark:text-amber-300">Inactive</Badge>}
              </div>
            </div>
          </div>
          {t.description_text ? (
            <p className="line-clamp-3 whitespace-pre-line text-sm leading-6 text-muted-foreground">{t.description_text}</p>
          ) : (
            <p className="text-sm italic text-subtle-foreground">Aucune description.</p>
          )}
          <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-2 border-t pt-3 text-xs text-muted-foreground">
            <span className="flex min-w-0 items-center gap-1.5">
              {t.lead_name ? <Avatar name={t.lead_name} className="size-5 text-[9px]" /> : <UserRound className="size-3.5" aria-hidden="true" />}
              <span className="truncate">{t.lead_name || "Sans lead"}</span>
            </span>
            <span className="flex items-center gap-1.5" title="Membres"><Users className="size-3.5" aria-hidden="true" />{t.members_count ?? 0} membre(s)</span>
            <span className="flex items-center gap-1.5" title="Projets"><FolderKanban className="size-3.5" aria-hidden="true" />{t.projects_count ?? 0} projet(s)</span>
          </div>
        </div>
      </Card>
    </Link>
  );
}

export function TeamsPage() {
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search);
  const { data, isPending, isError, error, refetch } = useTeams(q);
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Organisation" title="Équipes" description={data ? `${data.count} équipe(s)` : undefined}
        actions={<><Button variant="outline" asChild><Link to="/members"><Users />Membres</Link></Button><Button asChild><Link to="/teams/new"><Plus />Nouvelle équipe</Link></Button></>} />
      <div className="relative max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden="true" />
        <Input type="search" className="pl-9" placeholder="Rechercher une équipe…" aria-label="Rechercher une équipe" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      {isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-52" />)}</div>
      ) : isError ? <ErrorState message={error.message} onRetry={() => void refetch()} /> : data.results.length === 0 ? (
        <EmptyState title="Aucune équipe" description={q ? "Aucune équipe ne correspond à la recherche." : "Créez votre première équipe."} />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {data.results.map((t) => <li key={t.id}><TeamCard t={t} /></li>)}
        </ul>
      )}
    </div>
  );
}
