import { Loader2, Paperclip, Plus, Route, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { useMe } from "@/features/auth/api";
import { can } from "@/lib/permissions";
import { ApiError } from "@/services/api";
import { useCanCreateTicket, useCreateOptions, useCreateTicket, useTeamAgents } from "./api";
import { ATTACHMENT_ACCEPT, CATEGORIES, PRIORITIES, SEVERITIES } from "./constants";

const SEVERITY_PRIORITY: Record<string, string> = { CRITICAL: "P1", MAJOR: "P2", MINOR: "P3", TRIVIAL: "P4" };

interface Draft {
  application: string; project: string | null; category: string; severity: string; priority: string; title: string;
  description: string; team: string; assignee: string; reporter_name: string; reporter_email: string;
}

const EMPTY: Draft = {
  application: "", project: null, category: "BUG", severity: "MINOR", priority: "", title: "", description: "",
  team: "", assignee: "", reporter_name: "", reporter_email: "",
};

/** Erreurs de validation Django par champ ({champ: message}). */
function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || !error.data || typeof error.data !== "object") return {};
  return Object.fromEntries(Object.entries(error.data as Record<string, unknown>)
    .filter(([k]) => k !== "detail")
    .map(([k, v]) => [k, Array.isArray(v) ? v.join(" ") : String(v)]));
}

/** Bouton « Nouveau ticket » (masqué sans le droit ticket.create ; le contrôle reste côté Django). */
export function NewTicketButton({ projectId, variant = "default" }: { projectId?: number; variant?: "default" | "outline" }) {
  const allowed = useCanCreateTicket();
  const [open, setOpen] = useState(false);
  if (!allowed) return null;
  return (
    <>
      <Button size="sm" variant={variant} onClick={() => setOpen(true)}><Plus />Nouveau ticket</Button>
      {open && <NewTicketDialog open={open} onOpenChange={setOpen} projectId={projectId} />}
    </>
  );
}

export function NewTicketDialog({ open, onOpenChange, projectId }: { open: boolean; onOpenChange: (o: boolean) => void; projectId?: number }) {
  const { data: me } = useMe();
  const options = useCreateOptions(me?.workspace?.id, open);
  const create = useCreateTicket();
  const navigate = useNavigate();
  const [d, setD] = useState<Draft>(() => ({ ...EMPTY, project: projectId ? String(projectId) : null }));
  const [files, setFiles] = useState<File[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const o = options.data;
  const canAssign = Boolean(o?.can_assign);
  const agents = useTeamAgents(d.team ? Number(d.team) : null, canAssign);

  // Valeurs par défaut dérivées : application unique, projet de l'application (sauf choix explicite).
  const application = d.application || (o?.applications.length === 1 ? String(o.applications[0]!.id) : "");
  const app = o?.applications.find((a) => String(a.id) === application);
  const project = d.project ?? (app?.project ? String(app.project) : "");
  const set = (patch: Partial<Draft>) => {
    setD((x) => ({ ...x, ...patch }));
    setErrors((e) => Object.fromEntries(Object.entries(e).filter(([k]) => !(k in patch))));
  };

  const addFiles = (list: FileList | null) => {
    if (!o || !list) return;
    const next = [...files, ...Array.from(list)].slice(0, o.max_files);
    const tooBig = next.find((f) => f.size > o.max_attachment_mb * 1024 * 1024);
    if (tooBig) {
      setErrors((e) => ({ ...e, attachments: `« ${tooBig.name} » dépasse ${o.max_attachment_mb} Mo.` }));
      return;
    }
    setFiles(next);
    setErrors((e) => Object.fromEntries(Object.entries(e).filter(([k]) => k !== "attachments")));
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!application) errs.application = "Choisissez l'application source.";
    if (d.title.trim().length < 3) errs.title = "Titre trop court (3 caractères minimum).";
    if (d.assignee && !d.team) errs.team = "Choisissez l'équipe de l'agent.";
    if (Object.keys(errs).length) {
      setErrors(errs);
      return;
    }
    const fd = new FormData();
    const fields: Record<string, string> = {
      application, title: d.title.trim(), description: d.description, category: d.category, severity: d.severity,
      priority: d.priority, project, team: d.team, assignee: d.assignee, reporter_name: d.reporter_name.trim(),
      reporter_email: d.reporter_email.trim(),
    };
    Object.entries(fields).forEach(([k, v]) => { if (v) fd.append(k, v); });
    files.forEach((f) => fd.append("attachments", f));
    create.mutate(fd, {
      onSuccess: (t) => {
        toast.success(`Ticket ${t.reference} créé.`);
        onOpenChange(false);
        navigate(`/tickets/${t.id}`);
      },
      onError: (err) => {
        setErrors(fieldErrors(err));
        toast.error(err.message);
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Nouveau ticket" className="sm:max-w-2xl"
      description="Référence, SLA et routage sont appliqués automatiquement, comme pour les tickets reçus par API ou e-mail.">
      {options.isPending ? (
        <p className="flex items-center gap-2 py-8 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" aria-hidden="true" />Chargement du formulaire…</p>
      ) : options.isError ? (
        <p role="alert" className="rounded-2xl bg-destructive/10 p-4 text-sm text-destructive">
          {options.error instanceof ApiError && options.error.status === 403 ? "Vous n'avez pas le droit de créer un ticket dans ce workspace." : options.error.message}
        </p>
      ) : !o?.applications.length ? (
        <div className="rounded-2xl bg-primary-faint p-4 text-sm">
          <p className="font-semibold">Aucune application active</p>
          <p className="mt-1 text-muted-foreground">Chaque ticket est rattaché à une application source.
            {can(me?.permissions, "ticket.admin") ? <> <Link to="/tickets/applications" className="font-semibold text-brand underline-offset-2 hover:underline" onClick={() => onOpenChange(false)}>Créer une application</Link>.</> : " Demandez à un administrateur du support d'en créer une."}
          </p>
        </div>
      ) : (
        <form onSubmit={submit} noValidate className="grid gap-3 sm:grid-cols-2" aria-busy={create.isPending}>
          <Field id="nt-app" label="Application source" error={errors.application}>
            <Select id="nt-app" required value={application} onChange={(e) => set({ application: e.target.value, project: projectId ? d.project : null })}
              aria-invalid={Boolean(errors.application)}>
              <option value="">— Choisir —</option>
              {o.applications.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </Select>
          </Field>
          <Field id="nt-project" label="Projet" error={errors.project}>
            <Select id="nt-project" value={project} onChange={(e) => set({ project: e.target.value })}>
              <option value="">— Aucun —</option>
              {o.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>
          </Field>
          <div className="sm:col-span-2">
            <Field id="nt-title" label="Titre" error={errors.title}>
              <Input id="nt-title" required minLength={3} maxLength={200} value={d.title} onChange={(e) => set({ title: e.target.value })}
                placeholder="Ex. L'export PDF des factures échoue" aria-invalid={Boolean(errors.title)} autoFocus />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field id="nt-desc" label="Description" error={errors.description} hint="Contexte, étapes pour reproduire, impact.">
              <Textarea id="nt-desc" rows={5} maxLength={20000} value={d.description} onChange={(e) => set({ description: e.target.value })} />
            </Field>
          </div>
          <Field id="nt-cat" label="Catégorie" error={errors.category}>
            <Select id="nt-cat" value={d.category} onChange={(e) => set({ category: e.target.value })}>
              {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </Select>
          </Field>
          <Field id="nt-sev" label="Gravité" error={errors.severity}>
            <Select id="nt-sev" value={d.severity} onChange={(e) => set({ severity: e.target.value })}>
              {SEVERITIES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </Select>
          </Field>
          {o.can_set_priority && (
            <Field id="nt-prio" label="Priorité" error={errors.priority}>
              <Select id="nt-prio" value={d.priority} onChange={(e) => set({ priority: e.target.value })}>
                <option value="">Selon la gravité ({SEVERITY_PRIORITY[d.severity]})</option>
                {PRIORITIES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
              </Select>
            </Field>
          )}
          {canAssign ? (
            <>
              <Field id="nt-team" label="Équipe" error={errors.team}>
                <Select id="nt-team" value={d.team} onChange={(e) => set({ team: e.target.value, assignee: "" })}>
                  <option value="">Routage automatique</option>
                  {o.teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </Select>
              </Field>
              <Field id="nt-agent" label="Responsable" error={errors.assignee} hint={d.team ? undefined : "Choisissez d'abord une équipe."}>
                <Select id="nt-agent" value={d.assignee} disabled={!d.team || agents.isPending} onChange={(e) => set({ assignee: e.target.value })}>
                  <option value="">{d.team && agents.isPending ? "Chargement…" : "File de l'équipe"}</option>
                  {(agents.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </Select>
              </Field>
            </>
          ) : (
            <p className="flex items-start gap-2 self-end rounded-2xl bg-muted p-3 text-xs text-muted-foreground sm:col-span-2">
              <Route className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />Équipe et responsable attribués automatiquement selon les règles de routage.
            </p>
          )}
          <details className="rounded-2xl border border-dashed p-3 sm:col-span-2">
            <summary className="cursor-pointer text-xs font-semibold text-muted-foreground">Déclarant (si vous saisissez pour le compte d'un tiers)</summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field id="nt-rname" label="Nom" error={errors.reporter_name}>
                <Input id="nt-rname" maxLength={150} value={d.reporter_name} onChange={(e) => set({ reporter_name: e.target.value })} placeholder={me?.full_name} />
              </Field>
              <Field id="nt-remail" label="E-mail" error={errors.reporter_email}>
                <Input id="nt-remail" type="email" maxLength={254} value={d.reporter_email} onChange={(e) => set({ reporter_email: e.target.value })} />
              </Field>
            </div>
          </details>
          <div className="sm:col-span-2">
            <p className="mb-1.5 text-xs font-semibold text-muted-foreground">Pièces jointes ({files.length}/{o.max_files}, {o.max_attachment_mb} Mo max. chacune)</p>
            {files.length > 0 && (
              <ul className="mb-2 flex flex-wrap gap-2">
                {files.map((f, i) => (
                  <li key={`${f.name}-${i}`} className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-hover py-1 pl-3 pr-1 text-xs">
                    <span className="truncate">{f.name}</span>
                    <button type="button" className="rounded-full p-1 hover:bg-card" aria-label={`Retirer ${f.name}`}
                      onClick={() => setFiles(files.filter((_, j) => j !== i))}><X className="size-3" /></button>
                  </li>
                ))}
              </ul>
            )}
            {files.length < o.max_files && (
              <label className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-dashed px-3 py-1.5 text-xs font-medium text-muted-foreground hover:border-primary hover:text-foreground">
                <Paperclip className="size-3.5" aria-hidden="true" />Joindre des fichiers
                <input type="file" multiple className="sr-only" accept={ATTACHMENT_ACCEPT} onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
              </label>
            )}
            {errors.attachments && <p role="alert" className="mt-1.5 text-xs text-destructive">{errors.attachments}</p>}
          </div>
          <div className="flex justify-end gap-2 pt-1 sm:col-span-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Plus />}Créer le ticket
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}
