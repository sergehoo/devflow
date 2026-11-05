import { Check, Eye, Lock, Play, RotateCcw, Unlock } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useQuickUpdate, type TaskState } from "./api";

type Payload = { status?: string; progress_percent?: number; spent_hours?: number | string; comment?: string };

/** Port React du panneau « Mise à jour rapide » (task_quick_update_panel.html) — même API, mêmes règles. */
function shortcuts(status: string): { label: string; icon: typeof Play; status: string; primary?: boolean }[] {
  switch (status) {
    case "TODO": return [{ label: "Démarrer", icon: Play, status: "IN_PROGRESS", primary: true }];
    case "IN_PROGRESS": return [{ label: "Terminer", icon: Check, status: "DONE", primary: true }, { label: "Envoyer en review", icon: Eye, status: "REVIEW" }];
    case "REVIEW": return [{ label: "Valider / terminer", icon: Check, status: "DONE", primary: true }, { label: "Reprendre", icon: RotateCcw, status: "IN_PROGRESS" }];
    case "BLOCKED": return [{ label: "Débloquer", icon: Unlock, status: "IN_PROGRESS", primary: true }];
    case "DONE": return [{ label: "Rouvrir", icon: RotateCcw, status: "IN_PROGRESS" }];
    default: return [{ label: "Démarrer", icon: Play, status: "IN_PROGRESS", primary: true }];
  }
}

export function QuickUpdatePanel({ taskId, state }: { taskId: number; state: TaskState }) {
  const mutation = useQuickUpdate(taskId);
  const [form, setForm] = useState({ status: state.status, progress: state.progress_percent, hours: "", comment: "" });
  const [error, setError] = useState("");

  if (!state.can_update) {
    return (
      <p className="flex items-start gap-2 rounded-2xl bg-muted px-4 py-3 text-sm text-muted-foreground">
        <Lock className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <span>Lecture seule : seule la personne assignée (<strong>{state.assignee_name || "personne"}</strong>) peut mettre à jour cette tâche. Utilisez « Réaffecter » pour changer de mandataire.</span>
      </p>
    );
  }

  const send = (payload: Payload) => {
    setError("");
    mutation.mutate(payload, {
      onSuccess: (s) => {
        toast.success("Tâche mise à jour.");
        setForm({ status: s.status, progress: s.progress_percent, hours: "", comment: "" });
      },
      onError: (e) => { setError(e.message); toast.error(e.message); },
    });
  };

  const dirty = form.status !== state.status || form.progress !== state.progress_percent || Number(form.hours) > 0 || form.comment.trim() !== "";
  const submit = () => {
    const payload: Payload = {};
    if (form.status !== state.status) payload.status = form.status;
    if (form.progress !== state.progress_percent) payload.progress_percent = form.progress;
    if (Number(form.hours) > 0) payload.spent_hours = form.hours;
    if (form.comment.trim()) payload.comment = form.comment.trim();
    send(payload);
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2">
        {shortcuts(state.status).map((a) => (
          <Button key={a.label} variant={a.primary ? "default" : "outline"} disabled={mutation.isPending} onClick={() => send({ status: a.status })}>
            <a.icon />{a.label}
          </Button>
        ))}
        {[0.5, 1, 2, 4].map((h) => (
          <Button key={h} variant="outline" disabled={mutation.isPending} title={`Ajouter ${h} h à votre timesheet du jour`} onClick={() => send({ spent_hours: h })}>
            +{h < 1 ? "30 min" : `${h} h`}
          </Button>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <fieldset>
          <legend className="mb-1.5 text-xs font-semibold text-muted-foreground">Statut</legend>
          <div className="flex flex-wrap gap-1.5">
            {state.statuses.map((s) => (
              <button key={s.value} type="button" aria-pressed={form.status === s.value} onClick={() => setForm((f) => ({ ...f, status: s.value }))}
                className={cn("rounded-full border px-3 py-1 text-xs font-semibold transition-colors",
                  form.status === s.value ? "border-primary bg-primary text-primary-foreground" : "bg-card text-muted-foreground hover:border-primary")}>
                {s.label}
              </button>
            ))}
          </div>
        </fieldset>
        <div>
          <Label htmlFor="qu-progress" className="flex justify-between">Avancement <span className="text-foreground">{form.progress} %</span></Label>
          <input id="qu-progress" type="range" min={0} max={100} step={5} value={form.progress} disabled={form.status === "DONE"}
            onChange={(e) => setForm((f) => ({ ...f, progress: Number(e.target.value) }))} className="w-full accent-primary" />
        </div>
        <div>
          <Label htmlFor="qu-hours">Temps passé aujourd'hui (h)</Label>
          <Input id="qu-hours" type="number" min={0} max={24} step={0.25} placeholder="0" value={form.hours}
            onChange={(e) => setForm((f) => ({ ...f, hours: e.target.value }))} />
          <p className="mt-1 text-xs text-subtle-foreground">
            Ajouté à votre timesheet · total passé : {state.spent_hours} h{state.estimate_hours ? ` / ${state.estimate_hours} h estimées` : ""}
          </p>
        </div>
        <div>
          <Label htmlFor="qu-comment">Commentaire {form.status === "BLOCKED" && <span className="text-destructive">(raison du blocage obligatoire)</span>}</Label>
          <Textarea id="qu-comment" rows={2} placeholder="Point d'avancement, blocage, prochaine étape…" value={form.comment}
            onChange={(e) => setForm((f) => ({ ...f, comment: e.target.value }))} />
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-3">
        {error && <p role="alert" className="mr-auto text-sm text-destructive">{error}</p>}
        <Button disabled={mutation.isPending || !dirty} onClick={submit}><Check />{mutation.isPending ? "Enregistrement…" : "Enregistrer la mise à jour"}</Button>
      </div>
    </div>
  );
}
