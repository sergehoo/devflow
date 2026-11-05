import { useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { LegacyForm } from "@/components/forms/LegacyForm";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { patchThroughForm, useResourceMutation } from "@/features/resources/api";
import { TASKS_KEY, type TaskOverview } from "./api";

type Adding = { name: string; title: string; query: Record<string, string>; hidden: string[]; exclude?: string[] } | null;

/**
 * Checklists, dépendances et labels de la tâche : formulaires et suppressions
 * exécutés par les vues Django (droits réels sur la tâche appliqués côté serveur).
 */
export function TaskStructure({ taskId, o }: { taskId: number; o: TaskOverview }) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState<Adding>(null);
  const [busy, setBusy] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: [...TASKS_KEY, taskId] });
  const delChecklist = useResourceMutation("task-checklist");
  const delItem = useResourceMutation("checklist-item");
  const delDep = useResourceMutation("task-dependency");
  const delLabel = useResourceMutation("task-label");
  const remove = (m: ReturnType<typeof useResourceMutation>, id: number) =>
    m.mutate({ id, action: "delete" }, { onSuccess: () => void refresh(), onError: (e) => toast.error(e.message) });
  const toggle = async (itemId: number, checked: boolean) => {
    setBusy(true);
    try { await patchThroughForm("checklist-item", itemId, { is_checked: checked }); await refresh(); }
    catch (e) { toast.error((e as Error).message); }
    finally { setBusy(false); }
  };
  const edit = o.can_edit;
  const add = (a: NonNullable<Adding>) => edit && (
    <Button size="sm" variant="ghost" onClick={() => setAdding(a)}><Plus />{a.title}</Button>
  );

  return (
    <>
      <Card>
        <CardHeader className="flex-row items-center justify-between gap-2"><CardTitle>Checklists</CardTitle>
          {add({ name: "task-checklist", title: "Checklist", query: { task: String(taskId) }, hidden: ["task", "position"] })}
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          {o.checklists.map((c) => (
            <div key={c.id}>
              <div className="flex items-center gap-2">
                <p className="font-semibold">{c.title}</p>
                <span className="text-xs text-muted-foreground">{c.items.filter((i) => i.is_checked).length}/{c.items.length}</span>
                {edit && <Button size="icon" variant="ghost" className="ml-auto size-7" aria-label={`Supprimer la checklist ${c.title}`} onClick={() => remove(delChecklist, c.id)}><X /></Button>}
              </div>
              <ul className="mt-1 space-y-1">
                {c.items.map((i) => (
                  <li key={i.id} className="group flex items-center gap-2">
                    <input type="checkbox" className="size-4 accent-primary" checked={i.is_checked} disabled={!edit || busy}
                      aria-label={i.text} onChange={(e) => void toggle(i.id, e.target.checked)} />
                    <span className={i.is_checked ? "text-muted-foreground line-through" : ""}>{i.text}</span>
                    {edit && <button type="button" className="ml-auto text-subtle-foreground opacity-0 hover:text-destructive group-hover:opacity-100 focus:opacity-100"
                      aria-label={`Supprimer ${i.text}`} onClick={() => remove(delItem, i.id)}><X className="size-3.5" /></button>}
                  </li>
                ))}
              </ul>
              {add({ name: "checklist-item", title: "Élément", query: { checklist: String(c.id) }, hidden: ["checklist", "position"], exclude: ["is_checked", "checked_by"] })}
            </div>
          ))}
          {!o.checklists.length && <p className="text-muted-foreground">Aucune checklist.</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-2"><CardTitle>Dépendances</CardTitle>
          {add({ name: "task-dependency", title: "Dépendance", query: { from_task: String(taskId) }, hidden: ["from_task"] })}
        </CardHeader>
        <CardContent className="space-y-1.5 text-sm">
          {o.dependencies.map((d) => (
            <p key={`${d.direction}-${d.id}`} className="group flex items-center gap-1.5">
              {d.direction === "out"
                ? <span>Cette tâche <span className="text-muted-foreground">{d.type.toLowerCase()}</span> <Link className="font-medium hover:text-primary" to={`/tasks/${d.task_id}`}>{d.title}</Link></span>
                : <span><Link className="font-medium hover:text-primary" to={`/tasks/${d.task_id}`}>{d.title}</Link> <span className="text-muted-foreground">{d.type.toLowerCase()}</span> cette tâche</span>}
              {edit && d.direction === "out" && <button type="button" className="ml-auto text-subtle-foreground opacity-0 hover:text-destructive group-hover:opacity-100 focus:opacity-100"
                aria-label={`Supprimer la dépendance vers ${d.title}`} onClick={() => remove(delDep, d.id)}><X className="size-3.5" /></button>}
            </p>
          ))}
          {!o.dependencies.length && <p className="text-muted-foreground">Aucune dépendance.</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-2"><CardTitle>Labels</CardTitle>
          {add({ name: "task-label", title: "Label", query: { task: String(taskId) }, hidden: ["task"] })}
        </CardHeader>
        <CardContent className="flex flex-wrap gap-1.5">
          {o.labels.map((l) => (
            <span key={l.id} className="inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium">
              <span className="size-2 rounded-full" style={{ backgroundColor: l.color }} aria-hidden="true" />{l.name}
              {edit && <button type="button" aria-label={`Retirer le label ${l.name}`} className="text-subtle-foreground hover:text-destructive" onClick={() => remove(delLabel, l.id)}><X className="size-3" /></button>}
            </span>
          ))}
          {!o.labels.length && <p className="text-sm text-muted-foreground">Aucun label.</p>}
        </CardContent>
      </Card>

      <Dialog open={!!adding} onOpenChange={(v) => !v && setAdding(null)} title={adding ? `Ajouter : ${adding.title.toLowerCase()}` : ""}>
        {adding && (
          <LegacyForm compact name={adding.name} query={adding.query} hidden={adding.hidden} exclude={adding.exclude} submitLabel="Ajouter"
            onCancel={() => setAdding(null)}
            onSuccess={() => { setAdding(null); void refresh(); }} />
        )}
      </Dialog>
    </>
  );
}
