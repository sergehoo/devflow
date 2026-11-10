import { Archive, CalendarClock, Flag, Paperclip, Pencil, Send, Trash2, UserRoundCog, XCircle } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Avatar, Badge } from "@/components/ui/misc";
import { useMe } from "@/features/auth/api";
import { formatDate, formatDateTime } from "@/lib/format";
import { useDebouncedValue } from "@/lib/hooks";
import { useAssignees, useReassign, useTask, useTaskAction, useTaskOverview } from "./api";
import { STATUS_BADGE, isOverdue } from "./constants";
import { QuickUpdatePanel } from "./QuickUpdatePanel";
import { TaskStructure } from "./TaskStructure";

export function ReassignDialog({ taskId, open, onOpenChange }: { taskId: number; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [q, setQ] = useState("");
  const [note, setNote] = useState("");
  const query = useDebouncedValue(q);
  const candidates = useAssignees(taskId, query, open);
  const reassign = useReassign(taskId);
  const pick = (userId: number | null) =>
    reassign.mutate({ user_id: userId, note }, {
      onSuccess: () => { toast.success(userId ? "Tâche réaffectée." : "Assignation retirée."); onOpenChange(false); },
      onError: (e) => toast.error(e.message),
    });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Réaffecter la tâche" description="Le nouveau mandataire est notifié par email.">
      {candidates.data && !candidates.data.can_reassign ? (
        <p className="text-sm text-muted-foreground">Vous n'êtes pas autorisé à réaffecter cette tâche.</p>
      ) : (
        <div className="space-y-3">
          <Input type="search" placeholder="Rechercher un membre…" aria-label="Rechercher un membre" value={q} onChange={(e) => setQ(e.target.value)} />
          <Textarea rows={2} placeholder="Note pour le nouveau mandataire (facultatif)" aria-label="Note" value={note} onChange={(e) => setNote(e.target.value)} />
          <ul className="max-h-72 divide-y overflow-y-auto rounded-xl border">
            {candidates.data?.users.map((u) => (
              <li key={u.id}>
                <button type="button" disabled={reassign.isPending} onClick={() => pick(u.id)} className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-hover">
                  <Avatar name={u.name} className="size-8" />
                  <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{u.name}</span><span className="block truncate text-xs text-muted-foreground">{u.job_title || u.email}</span></span>
                  {u.is_project_member && <Badge>Projet</Badge>}
                </button>
              </li>
            ))}
            {candidates.isPending && <li className="p-3 text-sm text-muted-foreground">Chargement…</li>}
          </ul>
          <Button variant="outline" disabled={reassign.isPending} onClick={() => pick(null)}>Retirer l'assignation</Button>
        </div>
      )}
    </Dialog>
  );
}

export function TaskDetailPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const { data: me } = useMe();
  const { data: task, isPending, isError, error, refetch } = useTask(id);
  const overview = useTaskOverview(id);
  const action = useTaskAction(id);
  const [dialog, setDialog] = useState<"reassign" | "archive" | "delete" | "extend" | "expire" | null>(null);
  const [comment, setComment] = useState("");
  const [due, setDue] = useState("");

  if (isPending) return <PageSkeleton />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;
  const o = overview.data;
  const isAssignee = task.assignee === me?.id;

  const run = (name: string, data?: Record<string, string | Blob>, after?: () => void) =>
    action.mutate({ action: name, data }, {
      onSuccess: (r) => { (r.messages?.length ? r.messages : ["Action effectuée."]).forEach((m) => toast.success(m)); setDialog(null); after?.(); },
      onError: (e) => { toast.error(e.message); setDialog(null); },
    });

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={task.project_name || "Tâche"}
        title={task.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge className={STATUS_BADGE[task.status]}>{task.status_label}</Badge>
            <Badge>Priorité {task.priority_label}</Badge>
            {task.is_flagged && <Badge className="bg-destructive/10 text-destructive">Signalée</Badge>}
            <span className={isOverdue(task.due_date, task.status) ? "font-semibold text-destructive" : ""}>Échéance {formatDate(task.due_date)}</span>
          </span>
        }
        actions={
          <>
            {o?.can_edit && <Button variant="outline" asChild><Link to={`/tasks/${id}/edit`}><Pencil />Modifier</Link></Button>}
            <Button variant="outline" onClick={() => setDialog("reassign")}><UserRoundCog />Réaffecter</Button>
            {isAssignee && <Button variant="outline" disabled={action.isPending} onClick={() => run("task-flag")}><Flag />{task.is_flagged ? "Retirer le signalement" : "Signaler"}</Button>}
            {o?.can_arbitrate && <Button variant="outline" onClick={() => { setDue(task.due_date ?? ""); setDialog("extend"); }}><CalendarClock />Prolonger</Button>}
            {o?.can_arbitrate && !["DONE", "CANCELLED", "EXPIRED"].includes(task.status) && <Button variant="outline" onClick={() => setDialog("expire")}><XCircle />Expirer</Button>}
            {o?.can_delete && <Button variant="outline" onClick={() => setDialog("archive")}><Archive />Archiver</Button>}
            {o?.can_delete && <Button variant="destructive" onClick={() => setDialog("delete")}><Trash2 />Supprimer</Button>}
          </>
        }
      />

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <Card>
            <CardHeader><CardTitle>Mise à jour rapide</CardTitle></CardHeader>
            <CardContent>{o ? <QuickUpdatePanel key={`${o.state.status}-${o.state.progress_percent}-${o.state.spent_hours}`} taskId={id} state={o.state} /> : <p className="text-sm text-muted-foreground">Chargement…</p>}</CardContent>
          </Card>

          {o?.description && (
            <Card><CardHeader><CardTitle>Description</CardTitle></CardHeader><CardContent><p className="whitespace-pre-line text-sm">{o.description}</p></CardContent></Card>
          )}

          <Card>
            <CardHeader><CardTitle>Commentaires ({o?.comments.length ?? 0})</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              {isAssignee && (
                <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (comment.trim()) run("task-comment", { body: comment.trim() }, () => setComment("")); }}>
                  <Label htmlFor="new-comment" className="sr-only">Nouveau commentaire</Label>
                  <Textarea id="new-comment" rows={2} placeholder="Ajouter un commentaire…" value={comment} onChange={(e) => setComment(e.target.value)} />
                  <Button type="submit" size="icon" aria-label="Publier le commentaire" disabled={action.isPending || !comment.trim()}><Send /></Button>
                </form>
              )}
              <ol className="space-y-4">
                {o?.comments.map((c) => (
                  <li key={c.id} className="flex gap-3">
                    <Avatar name={c.author} className="size-8" />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs text-muted-foreground"><span className="font-semibold text-foreground">{c.author}</span> · {formatDateTime(c.created_at)} {c.is_internal && <Badge>Interne</Badge>}</p>
                      <p className="mt-0.5 whitespace-pre-line text-sm">{c.body}</p>
                    </div>
                  </li>
                ))}
                {o && !o.comments.length && <li className="text-sm text-muted-foreground">Aucun commentaire.</li>}
              </ol>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader><CardTitle>Détails</CardTitle></CardHeader>
            <CardContent>
              <dl className="space-y-2.5 text-sm">
                {([
                  ["Assigné à", task.assignee_name || "—"], ["Rapporteur", o?.reporter || "—"],
                  ["Projet", task.project ? <Link key="p" to={`/projects/${task.project}`} className="hover:text-brand">{task.project_name}</Link> : "—"],
                  ["Sprint", task.sprint_name || "—"], ["Début", formatDate(task.start_date)], ["Échéance", formatDate(task.due_date)],
                  ["Estimation", task.estimate_hours ? `${task.estimate_hours} h` : "—"], ["Temps passé", `${task.spent_hours ?? 0} h`],
                ] as const).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3"><dt className="text-muted-foreground">{k}</dt><dd className="text-right font-medium">{v}</dd></div>
                ))}
              </dl>
              {o && o.assignments.length > 1 && (
                <p className="mt-3 text-xs text-muted-foreground">Co-affectés : {o.assignments.filter((a) => a.is_active).map((a) => `${a.user} (${a.allocation_percent} %)`).join(", ")}</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Pièces jointes</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {o?.attachments.map((a) => (
                <a key={a.id} href={a.url ?? "#"} target="_blank" rel="noreferrer" className="flex items-center gap-2 text-sm hover:text-brand">
                  <Paperclip className="size-4 shrink-0" aria-hidden="true" /><span className="truncate">{a.name}</span>
                  <span className="ml-auto shrink-0 text-xs text-muted-foreground">{a.uploaded_by}</span>
                </a>
              ))}
              {o && !o.attachments.length && <p className="text-sm text-muted-foreground">Aucune pièce jointe.</p>}
              {isAssignee && (
                <label className="block">
                  <span className="sr-only">Ajouter une pièce jointe</span>
                  <Input type="file" className="pt-2" disabled={action.isPending}
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) run("task-attachment", { file: f }); e.target.value = ""; }} />
                </label>
              )}
            </CardContent>
          </Card>

          {o && o.subtasks.length > 0 && (
            <Card>
              <CardHeader><CardTitle>Sous-tâches</CardTitle></CardHeader>
              <CardContent>
                <ul className="space-y-1 text-sm">{o.subtasks.map((t) => <li key={t.id}><Link to={`/tasks/${t.id}`} className="hover:text-brand">{t.title}</Link> <span className="text-xs text-muted-foreground">· {t.status_label}</span></li>)}</ul>
              </CardContent>
            </Card>
          )}
          {o && <TaskStructure taskId={id} o={o} />}
        </div>
      </div>

      <ReassignDialog taskId={id} open={dialog === "reassign"} onOpenChange={(v) => setDialog(v ? "reassign" : null)} />
      <Dialog open={dialog === "extend"} onOpenChange={(v) => !v && setDialog(null)} title="Prolonger la tâche" description="Nouvelle échéance fixée par le chef de projet.">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); run("task-extend", { due_date: due }); }}>
          <div><Label htmlFor="extend-due">Nouvelle échéance</Label><Input id="extend-due" type="date" required value={due} onChange={(e) => setDue(e.target.value)} /></div>
          <div className="flex justify-end gap-2"><Button type="button" variant="outline" onClick={() => setDialog(null)}>Annuler</Button><Button type="submit" disabled={!due || action.isPending}>Prolonger</Button></div>
        </form>
      </Dialog>
      <ConfirmDialog open={dialog === "expire"} onOpenChange={(v) => !v && setDialog(null)} pending={action.isPending}
        title="Marquer la tâche comme expirée ?" description="Elle ne générera plus de relances." confirmLabel="Expirer" onConfirm={() => run("task-expire")} />
      <ConfirmDialog open={dialog === "archive"} onOpenChange={(v) => !v && setDialog(null)} pending={action.isPending}
        title="Archiver cette tâche ?" description="Elle disparaît des listes ; son historique est conservé." confirmLabel="Archiver" onConfirm={() => run("task-archive", undefined, () => navigate("/tasks"))} />
      <ConfirmDialog open={dialog === "delete"} onOpenChange={(v) => !v && setDialog(null)} pending={action.isPending} destructive
        title="Supprimer définitivement cette tâche ?" description="Commentaires, pièces jointes et temps saisis liés seront perdus." confirmLabel="Supprimer" onConfirm={() => run("task-delete", undefined, () => navigate("/tasks"))} />
    </div>
  );
}
