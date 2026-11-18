import { Archive, FolderKanban, Gauge, Pencil, Trash2, UserRound, Users } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Avatar, Badge, Skeleton } from "@/components/ui/misc";
import { useMe } from "@/features/auth/api";
import { RichHtml } from "@/features/meetings/Content";
import { can } from "@/lib/permissions";
import { useTeam, useTeamAction, useTeamOverview } from "./api";

const clampPercent = (value: number) => Math.max(0, Math.min(100, Math.round(value)));

function Stat({ icon, label, value, children }: { icon: ReactNode; label: string; value: ReactNode; children?: ReactNode }) {
  return (
    <Card className="p-4">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">{icon}{label}</p>
      <p className="mt-1.5 truncate text-lg font-semibold">{value}</p>
      {children}
    </Card>
  );
}

function Meter({ percent, label }: { percent: number; label: string }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted" role="progressbar" aria-label={label}
      aria-valuenow={clampPercent(percent)} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full bg-primary" style={{ width: `${clampPercent(percent)}%` }} />
    </div>
  );
}

export function TeamDetailPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const { data: me } = useMe();
  const { data: team, isPending, isError, error, refetch } = useTeam(id);
  const overview = useTeamOverview(id);
  const action = useTeamAction();
  const [confirm, setConfirm] = useState<"team-archive" | "team-delete" | null>(null);
  if (isPending) return <PageSkeleton />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;
  const run = (name: "team-archive" | "team-delete") => action.mutate({ action: name, id }, {
    onSuccess: () => { toast.success(name === "team-archive" ? "Équipe archivée." : "Équipe supprimée."); navigate("/teams"); },
    onError: (e) => { toast.error(e.message); setConfirm(null); },
  });
  // Archivage et suppression réservés à l'administration (contrôle réel côté Django).
  const canArchive = can(me?.permissions, "team.archive");
  const canDelete = can(me?.permissions, "team.delete");
  const color = team.color || "#7C6FF7";
  const members = overview.data?.members ?? [];
  const projects = overview.data?.projects ?? [];
  const velocity = team.velocity_target ? (team.velocity_current / team.velocity_target) * 100 : 0;

  return (
    <div className="space-y-6">
      <PageHeader eyebrow={team.team_type_label} title={team.name}
        description={<span className="inline-flex items-center gap-2">
          <span className="size-2.5 rounded-full" style={{ backgroundColor: color }} aria-hidden="true" />
          {team.is_active ? "Équipe active" : "Équipe inactive"}
        </span>}
        actions={<>
          <Button variant="outline" asChild><Link to={`/teams/${id}/edit`}><Pencil />Modifier</Link></Button>
          {canArchive && <Button variant="outline" onClick={() => setConfirm("team-archive")}><Archive />Archiver</Button>}
          {canDelete && <Button variant="destructive" onClick={() => setConfirm("team-delete")}><Trash2 />Supprimer</Button>}
        </>} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat icon={<UserRound className="size-3.5" aria-hidden="true" />} label="Lead" value={team.lead_name || "Non désigné"} />
        <Stat icon={<Users className="size-3.5" aria-hidden="true" />} label="Membres" value={overview.data ? members.length : "…"} />
        <Stat icon={<FolderKanban className="size-3.5" aria-hidden="true" />} label="Projets" value={overview.data ? projects.length : "…"} />
        <Stat icon={<Gauge className="size-3.5" aria-hidden="true" />} label="Vélocité" value={`${team.velocity_current} / ${team.velocity_target}`}>
          <div className="mt-2"><Meter percent={velocity} label="Vélocité atteinte" /></div>
        </Stat>
      </div>

      <Card>
        <CardHeader><CardTitle>À propos de l'équipe</CardTitle></CardHeader>
        <CardContent className="pt-3 sm:pt-3">
          <RichHtml html={team.description_html} empty="Aucune description. Ajoutez-en une depuis « Modifier »." className="max-w-3xl" />
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Membres ({overview.data ? members.length : "…"})</CardTitle></CardHeader>
          <CardContent>
            {overview.isPending ? <Skeleton className="h-32" /> : members.length ? (
              <ul className="divide-y">
                {members.map((m) => (
                  <li key={m.id} className="flex items-center gap-3 py-2.5 text-sm">
                    <Avatar name={m.name} className="size-8" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{m.name}</p>
                      <p className="truncate text-xs text-muted-foreground">{m.job_title || m.role_label}</p>
                    </div>
                    <Badge>{m.status_label}</Badge>
                    <div className="hidden w-24 items-center gap-2 sm:flex" title="Charge actuelle">
                      <Meter percent={m.current_load_percent} label={`Charge de ${m.name}`} />
                      <span className="w-9 shrink-0 text-right text-xs tabular-nums text-muted-foreground">{m.current_load_percent} %</span>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="rounded-2xl bg-hover px-4 py-6 text-center text-sm text-muted-foreground">
                Aucun membre dans cette équipe.{" "}
                <Link to="/members" className="font-medium text-brand underline-offset-2 hover:underline">Gérer les membres</Link>
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Projets ({overview.data ? projects.length : "…"})</CardTitle></CardHeader>
          <CardContent>
            {overview.isPending ? <Skeleton className="h-32" /> : projects.length ? (
              <ul className="divide-y text-sm">
                {projects.map((p) => (
                  <li key={p.id} className="flex items-center gap-3 py-2.5">
                    <Link to={`/projects/${p.id}`} className="min-w-0 truncate font-medium hover:text-brand">{p.name}</Link>
                    <Badge className="shrink-0">{p.status_label}</Badge>
                    <div className="ml-auto flex w-28 shrink-0 items-center gap-2">
                      <Meter percent={p.progress_percent} label={`Avancement de ${p.name}`} />
                      <span className="w-9 shrink-0 text-right text-xs tabular-nums text-muted-foreground">{p.progress_percent} %</span>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="rounded-2xl bg-hover px-4 py-6 text-center text-sm text-muted-foreground">Aucun projet rattaché à cette équipe.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <ConfirmDialog open={confirm === "team-archive"} onOpenChange={(o) => !o && setConfirm(null)} pending={action.isPending}
        title="Archiver cette équipe ?" description="Elle ne sera plus proposée dans les formulaires." confirmLabel="Archiver" onConfirm={() => run("team-archive")} />
      <ConfirmDialog open={confirm === "team-delete"} onOpenChange={(o) => !o && setConfirm(null)} pending={action.isPending} destructive
        title="Supprimer définitivement cette équipe ?" description="Les adhésions liées seront supprimées. Action irréversible." confirmLabel="Supprimer" onConfirm={() => run("team-delete")} />
    </div>
  );
}
