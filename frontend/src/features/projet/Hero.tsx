/** En-tête riche de la fiche projet (port de _hero_header.html + génération IA avec suivi de progression). */
import {
  Archive, ArrowLeft, Bot, Boxes, CheckCircle2, ChevronDown, FileUp, Flag, FolderOpen, History, ListChecks, Loader2,
  Pencil, Plus, Trash2, Users, Wand2, X,
} from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useMe } from "@/features/auth/api";
import { useProjectAction } from "@/features/projects/api";
import { HEALTH } from "@/features/projects/constants";
import { formatDate } from "@/lib/format";
import { can } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { isGenerating, projectEditPath, useGenerationStatus, useTriggerGeneration, type GenerationStatus, type ProjectDetail, type TabKey } from "./api";
import type { FormSpec } from "./formDialog";
import { ExcelButton, Pill, ProgressBar } from "./ui";

/**
 * Bandeau de progression de la génération IA (roadmap, jalons, sprints, backlog, tâches).
 * L'issue n'est affichée que pour la proposition suivie (lancée ici ou observée en cours).
 */
function GenerationBanner({ projectId, s, watchedId, onDismiss }: {
  projectId: number; s: GenerationStatus | undefined; watchedId: number | null; onDismiss: () => void;
}) {
  const running = isGenerating(s);
  // Issue de la proposition suivie ou d'une plus récente (le worker peut créer sa propre proposition).
  const finished = !running && watchedId != null && (s?.proposal_id ?? 0) >= watchedId && !!s?.status;
  useEffect(() => {
    if (!finished) return;
    const t = setTimeout(onDismiss, 12_000);
    return () => clearTimeout(t);
  }, [finished, onDismiss]);
  if (!running && !finished) return null;
  const failed = s?.status === "FAILED";
  return (
    <div role="status" aria-live="polite"
      className={cn("rounded-2xl border p-4", finished && !failed ? "border-success/30 bg-success/5" : failed ? "border-destructive/30 bg-destructive/5" : "bg-card")}>
      <div className="flex items-center gap-3">
        {running ? <Loader2 className="size-6 shrink-0 animate-spin text-brand" aria-hidden="true" />
          : failed ? <X className="size-6 shrink-0 text-destructive" aria-hidden="true" />
            : <CheckCircle2 className="size-6 shrink-0 text-success" aria-hidden="true" />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold">{running ? "Génération PMO en cours" : failed ? "Échec de la génération" : "Génération terminée"}</p>
            <p className="text-xs text-muted-foreground">
              {s?.progress ?? 0} %{running && (s?.eta_seconds ?? 0) > 0 ? ` · reste ≈ ${s?.eta_seconds} s` : ""}
              {finished && !failed && <> · <Link to={`/projects/${projectId}/ai-proposals`} className="font-semibold text-brand underline">voir la proposition</Link></>}
            </p>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{s?.step_label}</p>
          <ProgressBar value={running ? s?.progress ?? 0 : failed ? 0 : 100} label="Progression de la génération IA" className="mt-2"
            barClassName={finished && !failed ? "bg-success" : undefined} />
        </div>
        {finished && <Button size="icon" variant="ghost" aria-label="Masquer le bandeau" onClick={onDismiss}><X /></Button>}
      </div>
    </div>
  );
}

export function ProjectHero({ detail, onTab, openForm }: { detail: ProjectDetail; onTab: (k: TabKey) => void; openForm: (s: FormSpec) => void }) {
  const p = detail.project;
  const id = p.id;
  const navigate = useNavigate();
  const { data: me } = useMe();
  const action = useProjectAction();
  const status = useGenerationStatus(id);
  const trigger = useTriggerGeneration(id);
  const generating = trigger.isPending || isGenerating(status.data);
  const [confirm, setConfirm] = useState<"archive" | "delete" | null>(null);
  // Proposition suivie : lancée depuis la fiche, ou en cours à l'ouverture (ajustement d'état pendant le rendu).
  const [watchedId, setWatchedId] = useState<number | null>(null);
  const runningId = isGenerating(status.data) ? status.data?.proposal_id ?? null : null;
  if (runningId != null && runningId !== watchedId) setWatchedId(runningId);
  const dismiss = useCallback(() => setWatchedId(null), []);

  const generate = () => trigger.mutate(undefined, {
    onSuccess: (r) => { setWatchedId(r.proposal_id); toast.success("Génération IA lancée : roadmap, jalons, sprints, backlog et tâches."); },
    onError: (e) => toast.error(e.message),
  });
  const run = (kind: "archive" | "delete") =>
    action.mutate({ id, action: kind }, {
      onSuccess: () => { toast.success(kind === "archive" ? "Projet archivé." : "Projet supprimé."); navigate("/projects"); },
      onError: (e) => toast.error(e.message),
      onSettled: () => setConfirm(null),
    });

  return (
    <Card className="relative overflow-hidden">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 bg-gradient-to-br from-primary/10 via-info/5 to-transparent" />
      <CardContent className="relative space-y-5 p-5 lg:p-7">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0">
            <div className="flex items-start gap-3">
              <span aria-hidden="true" className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
                <Boxes className="size-6" />
              </span>
              <div className="min-w-0">
                <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-brand">{p.workspace}</p>
                <h1 className="break-words font-serif text-3xl font-semibold lg:text-4xl">{p.name}</h1>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {p.code && <Pill>{p.code}</Pill>}
                  {p.category && <Pill>{p.category}</Pill>}
                  <Pill tone="primary">{p.status_label}</Pill>
                  <Pill tone="warning">Priorité {p.priority_label}</Pill>
                  <Pill className={HEALTH[p.health_status]}>Santé : {p.health_status_label}</Pill>
                  {p.budget_status_label && <Pill>Budget : {p.budget_status_label}</Pill>}
                  {p.labels.map((l) => (
                    // Couleur du label = donnée saisie par l'utilisateur.
                    <span key={l.id} className="inline-flex items-center rounded-full bg-primary px-2.5 py-0.5 text-[11px] font-semibold text-primary-foreground"
                      style={l.color ? { backgroundColor: l.color } : undefined}>{l.name}</span>
                  ))}
                </div>
              </div>
            </div>
            {p.description_html && (
              // HTML nettoyé côté Django (filtre safe_html / bleach, comme l'ancienne fiche).
              <div className="mt-4 max-w-4xl text-sm leading-6 text-muted-foreground [&_a]:text-brand [&_a]:underline [&_li]:my-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-2 [&_strong]:text-foreground [&_ul]:list-disc [&_ul]:pl-5"
                dangerouslySetInnerHTML={{ __html: p.description_html }} />
            )}
            <dl aria-label="Cadrage du projet" className="mt-4 grid max-w-4xl grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3 lg:grid-cols-5">
              {([
                ["Début", formatDate(p.start_date)],
                ["Échéance cible", formatDate(p.target_date)],
                ["Livré le", p.delivered_at ? formatDate(p.delivered_at) : "—"],
                ["Équipe", p.team_id ? <Link to={`/teams/${p.team_id}`} className="hover:text-brand">{p.team}</Link> : "—"],
                ["Stack technique", p.tech_stack || "—"],
              ] as [string, ReactNode][]).map(([k, v]) => (
                <div key={k} className="min-w-0">
                  <dt className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{k}</dt>
                  <dd className="mt-0.5 break-words font-medium">{v}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {detail.can_view_financials && <ExcelButton projectId={id} variant="outline" />}
            <Button size="sm" onClick={generate} disabled={generating} title="Générer roadmap, jalons, sprints, backlog et tâches via l'IA">
              {generating ? <Loader2 className="animate-spin" /> : <Wand2 />}{generating ? "IA en cours…" : "Générer suggestions IA"}
            </Button>
            <Button size="sm" variant="outline" asChild><Link to={`/projects/${id}/ai-proposals`}><History />Propositions IA</Link></Button>
            <Button size="sm" variant="outline" asChild><Link to={`/projects/${id}/copilot`}><Bot />Copilote IA</Link></Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild><Button size="sm" variant="outline">Actions<ChevronDown /></Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuItem onSelect={() => onTab("equipes")}><Users />Membres du projet</DropdownMenuItem>
                <DropdownMenuItem asChild><Link to={projectEditPath(id, p.workspace_id)}><Pencil />Modifier le projet</Link></DropdownMenuItem>
                <DropdownMenuItem asChild><Link to={`/tasks/new?project=${id}`}><Plus />Nouvelle tâche</Link></DropdownMenuItem>
                <DropdownMenuItem onSelect={() => openForm({ name: "sprint", title: "Nouveau sprint", query: { project: String(id) }, hidden: ["project"], submitLabel: "Créer" })}><Flag />Nouveau sprint</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => openForm({ name: "project-import", title: "Importer un document", query: { project: String(id) }, hidden: ["project", "status"], submitLabel: "Importer" })}><FileUp />Importer un document IA</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem disabled={generating} onSelect={generate}><Wand2 />Générer suggestions IA</DropdownMenuItem>
                <DropdownMenuItem asChild><Link to={`/projects/${id}/ai-proposals`}><History />Historique des propositions IA</Link></DropdownMenuItem>
                <DropdownMenuItem onSelect={() => onTab("documents")}><FolderOpen />Voir les documents</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => onTab("taches")}><ListChecks />Voir les tâches</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => setConfirm("archive")}><Archive />Archiver</DropdownMenuItem>
                {can(me?.permissions, "project.delete") && (
                  <DropdownMenuItem onSelect={() => setConfirm("delete")} className="text-destructive [&_svg]:text-destructive"><Trash2 />Supprimer le projet</DropdownMenuItem>
                )}
                <DropdownMenuItem asChild><Link to="/projects"><ArrowLeft />Retour à la liste</Link></DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
        <GenerationBanner projectId={id} s={status.data} watchedId={watchedId} onDismiss={dismiss} />
      </CardContent>

      <ConfirmDialog open={confirm === "archive"} onOpenChange={(o) => !o && setConfirm(null)} pending={action.isPending}
        title="Archiver ce projet ?" description="Il disparaît des listes ; ses données sont conservées." confirmLabel="Archiver" onConfirm={() => run("archive")} />
      <ConfirmDialog open={confirm === "delete"} onOpenChange={(o) => !o && setConfirm(null)} pending={action.isPending} destructive
        title="Supprimer définitivement ce projet ?" description="Tâches, budget et historique liés seront supprimés. Action irréversible." confirmLabel="Supprimer" onConfirm={() => run("delete")} />
    </Card>
  );
}
