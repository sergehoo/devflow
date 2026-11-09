import { Archive, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Avatar, Badge } from "@/components/ui/misc";
import { useTeam, useTeamAction, useTeamOverview } from "./api";

export function TeamDetailPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
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
  return (
    <div className="space-y-6">
      <PageHeader eyebrow={team.team_type_label} title={team.name}
        description={`Lead : ${team.lead_name || "—"} · vélocité ${team.velocity_current}/${team.velocity_target}`}
        actions={<>
          <Button variant="outline" asChild><Link to={`/teams/${id}/edit`}><Pencil />Modifier</Link></Button>
          <Button variant="outline" onClick={() => setConfirm("team-archive")}><Archive />Archiver</Button>
          <Button variant="destructive" onClick={() => setConfirm("team-delete")}><Trash2 />Supprimer</Button>
        </>} />
      {team.description && <p className="max-w-3xl text-sm text-muted-foreground">{team.description}</p>}
      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Membres ({overview.data?.members.length ?? "…"})</CardTitle></CardHeader>
          <CardContent>
            <ul className="space-y-3">
              {overview.data?.members.map((m) => (
                <li key={m.id} className="flex items-center gap-3 text-sm">
                  <Avatar name={m.name} className="size-8" />
                  <div className="min-w-0 flex-1"><p className="truncate font-medium">{m.name}</p><p className="truncate text-xs text-muted-foreground">{m.job_title || m.role_label}</p></div>
                  <Badge>{m.status_label}</Badge><span className="w-12 text-right text-xs tabular-nums">{m.current_load_percent} %</span>
                </li>
              ))}
              {overview.data && !overview.data.members.length && <li className="text-sm text-muted-foreground">Aucun membre.</li>}
            </ul>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Projets</CardTitle></CardHeader>
          <CardContent>
            <ul className="divide-y text-sm">
              {overview.data?.projects.map((p) => (
                <li key={p.id} className="flex items-center gap-2 py-2"><Link to={`/projects/${p.id}`} className="font-medium hover:text-brand">{p.name}</Link><Badge>{p.status_label}</Badge><span className="ml-auto tabular-nums text-muted-foreground">{p.progress_percent} %</span></li>
              ))}
              {overview.data && !overview.data.projects.length && <li className="py-2 text-muted-foreground">Aucun projet.</li>}
            </ul>
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
