import { Archive, ArrowRightLeft, Pencil, Settings2, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Avatar, Badge } from "@/components/ui/misc";
import { useWorkspace, useWorkspaceAction, useWorkspaceOverview, type Workspace } from "./api";
import { TransferOwnershipDialog } from "./TransferOwnership";

const SETTINGS_LINKS: [string, string][] = [
  ["Paramètres", "/m/workspace-settings"], ["Invitations", "/m/workspace-invitation"], ["Labels", "/m/label"],
  ["Intégrations", "/m/integration"], ["Webhooks", "/m/webhook"], ["Clés API", "/m/api-key"], ["Journal d'activité", "/m/activity-log"],
];

function Identity({ ws }: { ws: Workspace }) {
  const rows: [string, string][] = [
    ["Raison sociale", ws.legal_name], ["Slogan", ws.tagline], ["RCCM", ws.legal_rccm], ["Compte contribuable", ws.legal_cc],
    ["N° fiscal", ws.legal_tax_id], ["Adresse", [ws.address_line1, ws.address_line2, [ws.postal_code, ws.city].filter(Boolean).join(" "), ws.country].filter(Boolean).join(", ")],
    ["Téléphone", ws.phone], ["Site web", ws.website], ["Email", ws.email], ["Fuseau horaire", ws.timezone],
  ];
  const filled = rows.filter(([, v]) => v);
  if (!filled.length) return <p className="text-sm text-muted-foreground">Aucune information légale renseignée.</p>;
  return (
    <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
      {filled.map(([k, v]) => (
        <div key={k}><dt className="text-xs text-muted-foreground">{k}</dt><dd className="break-words font-medium">{v}</dd></div>
      ))}
    </dl>
  );
}

export function WorkspaceDetailPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const { data: ws, isPending, isError, error, refetch } = useWorkspace(id);
  const overview = useWorkspaceOverview(id);
  const action = useWorkspaceAction();
  const [confirm, setConfirm] = useState<"archive" | "delete" | null>(null);
  const [transfer, setTransfer] = useState(false);

  if (isPending) return <PageSkeleton />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;

  const run = (kind: "archive" | "delete") =>
    action.mutate({ id, action: kind }, {
      onSuccess: () => { toast.success(kind === "archive" ? "Workspace archivé." : "Workspace supprimé."); navigate("/workspaces"); },
      onError: (e) => toast.error(e.message),
      onSettled: () => setConfirm(null),
    });

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Workspace"
        title={ws.name}
        description={<>{ws.owner_name}{ws.quarter_label ? ` · ${ws.quarter_label}` : ""} {ws.is_archived && <Badge>Archivé</Badge>}</>}
        actions={
          <>
            {ws.can_manage && <Button variant="outline" asChild><Link to={`/workspaces/${id}/edit`}><Pencil />Modifier</Link></Button>}
            {ws.can_manage && <Button variant="outline" onClick={() => setTransfer(true)}><ArrowRightLeft />Transférer la propriété</Button>}
            {ws.can_manage && !ws.is_archived && <Button variant="outline" onClick={() => setConfirm("archive")}><Archive />Archiver</Button>}
            {ws.can_delete && <Button variant="destructive" onClick={() => setConfirm("delete")}><Trash2 />Supprimer</Button>}
          </>
        }
      />
      {ws.description && <p className="max-w-3xl text-sm text-muted-foreground">{ws.description}</p>}

      <div className="grid gap-4 sm:grid-cols-3">
        {([["Projets", ws.projects_count], ["Équipes", ws.teams_count], ["Membres", ws.memberships_count]] as const).map(([k, v]) => (
          <Card key={k}><CardContent><p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{k}</p><p className="mt-1 font-serif text-2xl font-semibold">{v ?? 0}</p></CardContent></Card>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader><CardTitle>Identité et papier en-tête</CardTitle></CardHeader>
          <CardContent><Identity ws={ws} /></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Équipes</CardTitle></CardHeader>
          <CardContent>
            {overview.data?.teams.length ? (
              <ul className="space-y-2 text-sm">{overview.data.teams.map((t) => (
                <li key={t.id} className="flex justify-between gap-2"><span className="font-medium">{t.name}</span><span className="text-muted-foreground">{t.team_type}</span></li>
              ))}</ul>
            ) : <p className="text-sm text-muted-foreground">{overview.isPending ? "Chargement…" : "Aucune équipe."}</p>}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Projets</CardTitle></CardHeader>
          <CardContent>
            {overview.data?.projects.length ? (
              <ul className="divide-y text-sm">{overview.data.projects.map((p) => (
                <li key={p.id} className="flex items-center gap-2 py-2">
                  <Link to={`/projects/${p.id}`} className="font-medium hover:text-primary">{p.name}</Link>
                  <Badge>{p.status_label}</Badge>
                  <span className="ml-auto text-muted-foreground">{p.progress_percent} %</span>
                </li>
              ))}</ul>
            ) : <p className="text-sm text-muted-foreground">{overview.isPending ? "Chargement…" : "Aucun projet."}</p>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Membres</CardTitle></CardHeader>
          <CardContent>
            {overview.data?.members.length ? (
              <ul className="space-y-2.5 text-sm">{overview.data.members.map((m) => (
                <li key={m.id} className="flex items-center gap-3">
                  <Avatar name={m.name} className="size-8" />
                  <div className="min-w-0"><p className="truncate font-medium">{m.name}</p><p className="truncate text-xs text-muted-foreground">{m.job_title || m.email}</p></div>
                </li>
              ))}</ul>
            ) : <p className="text-sm text-muted-foreground">{overview.isPending ? "Chargement…" : "Aucun membre."}</p>}
          </CardContent>
        </Card>
      </div>

      {ws.can_manage && (
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><Settings2 className="size-4" />Administration</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {SETTINGS_LINKS.map(([label, to]) => <Button key={to} variant="outline" size="sm" asChild><Link to={`${to}?workspace=${id}`}>{label}</Link></Button>)}
          </CardContent>
        </Card>
      )}
      <TransferOwnershipDialog workspaceId={id} open={transfer} onOpenChange={setTransfer} />
      <ConfirmDialog
        open={confirm === "archive"} onOpenChange={(o) => !o && setConfirm(null)} pending={action.isPending}
        title="Archiver ce workspace ?" description="Il ne sera plus proposé dans les listes. Les données sont conservées."
        confirmLabel="Archiver" onConfirm={() => run("archive")}
      />
      <ConfirmDialog
        open={confirm === "delete"} onOpenChange={(o) => !o && setConfirm(null)} pending={action.isPending} destructive
        title="Supprimer définitivement ce workspace ?" description="Toutes ses données (projets, tâches, timesheets…) seront supprimées. Action irréversible."
        confirmLabel="Supprimer" onConfirm={() => run("delete")}
      />
    </div>
  );
}
