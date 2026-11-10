import { ArrowUpCircle, ExternalLink, Lock, Paperclip, Send, SquarePlus, UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { WidgetHeader } from "@/features/dashboard/widgets";
import { ApiError } from "@/services/api";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useAssignable, useTicket, useTicketAction, type TicketDetail } from "./api";
import { PriorityPill, StatusPill } from "./components";
import { CATEGORIES, EVENT_LABELS, PRIORITIES, SEVERITIES, remaining } from "./constants";

const NOTE_REQUIRED = new Set(["CANCELLED"]);
const NOTE_SUGGESTED = new Set(["RESOLVED", "WAITING", "CANCELLED"]);

function useRun(id: number) {
  const action = useTicketAction(id);
  const run = (name: string, body: Record<string, unknown> | FormData, ok: string, after?: () => void) =>
    action.mutate({ action: name, body }, {
      onSuccess: () => { toast.success(ok); after?.(); },
      onError: (e) => toast.error(e.message),
    });
  return [run, action.isPending] as const;
}

function TransitionBar({ t }: { t: TicketDetail }) {
  const [run, pending] = useRun(t.id);
  const [target, setTarget] = useState<{ value: string; label: string } | null>(null);
  const [note, setNote] = useState("");
  if (!t.allowed_transitions.length) return null;
  const go = (value: string, label: string) => (NOTE_SUGGESTED.has(value) ? setTarget({ value, label }) : run("transition", { status: value }, `Statut : ${label}`));
  return (
    <>
      <div className="flex flex-wrap gap-2">
        {t.allowed_transitions.map((s) => (
          <Button key={s.value} size="sm" variant={s.value === "RESOLVED" ? "default" : "outline"} disabled={pending} onClick={() => go(s.value, s.label)}>
            {s.label}
          </Button>
        ))}
      </div>
      <Dialog open={target != null} onOpenChange={(o) => !o && setTarget(null)} title={`Passer en « ${target?.label} »`}
        description={target && NOTE_REQUIRED.has(target.value) ? "Le motif est obligatoire." : "Le message est publié au déclarant (facultatif)."}>
        <form className="space-y-4" onSubmit={(e) => {
          e.preventDefault();
          if (!target) return;
          run("transition", { status: target.value, note }, `Statut : ${target.label}`, () => { setTarget(null); setNote(""); });
        }}>
          <Field id="transition-note" label={target && NOTE_REQUIRED.has(target.value) ? "Motif" : "Message au déclarant"}>
            <Textarea id="transition-note" value={note} onChange={(e) => setNote(e.target.value)} required={Boolean(target && NOTE_REQUIRED.has(target.value))} maxLength={2000} />
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setTarget(null)}>Annuler</Button>
            <Button type="submit" disabled={pending}>Confirmer</Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}

function AssignDialog({ t, open, onOpenChange }: { t: TicketDetail; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [team, setTeam] = useState<number | null>(t.team?.id ?? null);
  const [agent, setAgent] = useState<string>(t.assignee ? String(t.assignee.id) : "");
  const { data } = useAssignable(t.id, team, open);
  const [run, pending] = useRun(t.id);
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Affecter le ticket" description="Seuls les membres actifs de l'équipe ayant un droit sur les tickets sont proposés.">
      <form className="space-y-4" onSubmit={(e) => {
        e.preventDefault();
        run("assign", { team, assignee: agent ? Number(agent) : null }, "Affectation enregistrée.", () => onOpenChange(false));
      }}>
        <Field id="assign-team" label="Équipe">
          <Select id="assign-team" value={team ?? ""} onChange={(e) => { setTeam(e.target.value ? Number(e.target.value) : null); setAgent(""); }}>
            <option value="">— Choisir —</option>
            {(data?.teams ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </Select>
        </Field>
        <Field id="assign-agent" label="Agent (facultatif : sinon file de l'équipe)">
          <Select id="assign-agent" value={agent} onChange={(e) => setAgent(e.target.value)} disabled={!team}>
            <option value="">— File de l'équipe —</option>
            {(data?.agents ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </Select>
        </Field>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
          <Button type="submit" disabled={pending || !team}>Affecter</Button>
        </div>
      </form>
    </Dialog>
  );
}

function Qualification({ t }: { t: TicketDetail }) {
  const [run, pending] = useRun(t.id);
  const select = (field: string, value: string, options: readonly { value: string; label: string }[], label: string) => (
    <Field id={`q-${field}`} label={label}>
      <Select id={`q-${field}`} value={value} disabled={!t.rights.manage || pending}
        onChange={(e) => run("qualify", { [field]: e.target.value }, "Ticket qualifié.")}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </Select>
    </Field>
  );
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {select("priority", t.priority, PRIORITIES, "Priorité opérationnelle")}
      {select("severity", t.severity, SEVERITIES, "Gravité technique")}
      {select("category", t.category, CATEGORIES, "Catégorie")}
    </div>
  );
}

function Conversation({ t }: { t: TicketDetail }) {
  const [run, pending] = useRun(t.id);
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState<"PUBLIC" | "INTERNAL">("PUBLIC");
  const [files, setFiles] = useState<File[]>([]);
  const canWrite = t.rights.work || t.rights.manage;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const fd = new FormData();
    fd.append("body", body);
    fd.append("visibility", visibility);
    files.forEach((f) => fd.append("attachments", f));
    run("comment", fd, visibility === "PUBLIC" ? "Réponse envoyée au déclarant." : "Note interne ajoutée.", () => { setBody(""); setFiles([]); });
  };
  return (
    <Card className="p-5 sm:p-6">
      <WidgetHeader title="Échanges" meta={`${t.comments.length} message(s)`} />
      <ol className="mt-4 space-y-3">
        <li className="rounded-2xl bg-muted p-4">
          <p className="text-xs font-semibold text-muted-foreground">{t.reporter_name || t.application?.name} · {formatDateTime(t.created_at)}</p>
          <p className="mt-1.5 whitespace-pre-wrap text-sm">{t.description || "Aucune description."}</p>
        </li>
        {t.comments.map((c) => (
          <li key={c.id} className={cn("rounded-2xl p-4", c.visibility === "INTERNAL" ? "border border-dashed border-warning/40 bg-warning/5" : c.external ? "bg-muted" : "bg-primary-faint")}>
            <p className="flex flex-wrap items-center gap-2 text-xs font-semibold text-muted-foreground">
              {c.author}{c.external ? " (déclarant)" : ""} · {formatDateTime(c.created_at)}
              {c.visibility === "INTERNAL" && <span className="inline-flex items-center gap-1 text-warning"><Lock className="size-3" aria-hidden="true" />Interne</span>}
            </p>
            <p className="mt-1.5 whitespace-pre-wrap text-sm">{c.body}</p>
          </li>
        ))}
      </ol>
      {canWrite && t.status !== "CANCELLED" && (
        <form onSubmit={submit} className="mt-5 space-y-3">
          <div className="flex rounded-full bg-hover p-1 text-xs font-semibold" role="radiogroup" aria-label="Visibilité">
            {(["PUBLIC", "INTERNAL"] as const).map((v) => (
              <button key={v} type="button" role="radio" aria-checked={visibility === v} onClick={() => setVisibility(v)}
                className={cn("flex-1 rounded-full px-3 py-1.5", visibility === v ? "bg-card shadow-card" : "text-muted-foreground")}>
                {v === "PUBLIC" ? "Réponse au déclarant" : "Note interne"}
              </button>
            ))}
          </div>
          <label htmlFor="ticket-comment" className="sr-only">Message</label>
          <Textarea id="ticket-comment" value={body} onChange={(e) => setBody(e.target.value)} maxLength={10000} required
            placeholder={visibility === "PUBLIC" ? "Votre réponse sera visible dans l'application d'origine…" : "Visible uniquement par l'équipe DevFlow…"} />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label className="inline-flex cursor-pointer items-center gap-2 text-xs font-medium text-muted-foreground hover:text-foreground">
              <Paperclip className="size-4" aria-hidden="true" />{files.length ? `${files.length} fichier(s)` : "Joindre des fichiers"}
              <input type="file" multiple className="sr-only" accept="image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain,text/csv,application/json,application/zip,video/mp4,video/webm"
                onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, 5))} />
            </label>
            <Button type="submit" disabled={pending || !body.trim()}><Send />Envoyer</Button>
          </div>
        </form>
      )}
    </Card>
  );
}

export function TicketDetailPage() {
  const id = Number(useParams().id);
  const { data: t, isPending, isError, error, refetch } = useTicket(id);
  const [run, pending] = useRun(id);
  const [assignOpen, setAssignOpen] = useState(false);
  const [escalateOpen, setEscalateOpen] = useState(false);
  const [reason, setReason] = useState("");
  if (isPending) return <PageSkeleton />;
  if (isError) return <ErrorState message={error instanceof ApiError && error.status === 404 ? "Ticket introuvable." : error.message} onRetry={() => void refetch()} />;
  const sla = t.sla;
  const open = ["NEW", "QUALIFIED", "ASSIGNED", "IN_PROGRESS", "WAITING"].includes(t.status);

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-brand">{t.reference} · {t.application?.name}</p>
          <h1 className="mt-1 text-[26px] font-semibold leading-tight tracking-tight sm:text-[30px]">{t.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusPill status={t.status} label={t.status_label} /><PriorityPill priority={t.priority} />
            <span className="text-xs text-muted-foreground">{t.category_label} · gravité {t.severity_label.toLowerCase()}</span>
            {t.escalation_level > 0 && <span className="rounded-full bg-destructive/10 px-2 py-0.5 text-[11px] font-semibold text-destructive">Escalade niv. {t.escalation_level}</span>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {open && (t.rights.assign || t.rights.work) && <Button variant="outline" size="sm" onClick={() => setAssignOpen(true)}><UserPlus />Affecter</Button>}
          {open && (t.rights.manage || t.rights.work) && <Button variant="outline" size="sm" onClick={() => setEscalateOpen(true)}><ArrowUpCircle />Escalader</Button>}
          {!t.task && (t.rights.manage || t.rights.work) && (
            <Button variant="outline" size="sm" disabled={pending} onClick={() => run("create-task", {}, "Tâche DevFlow créée.")}><SquarePlus />Créer une tâche</Button>
          )}
        </div>
      </header>

      <TransitionBar t={t} />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          <Card className="p-5 sm:p-6">
            <WidgetHeader title="Qualification" />
            <div className="mt-3"><Qualification t={t} /></div>
          </Card>
          <Conversation t={t} />
          <Card className="p-5 sm:p-6">
            <WidgetHeader title="Historique" />
            <ol className="mt-3 space-y-2.5 border-l pl-4">
              {t.events.map((e) => (
                <li key={e.id} className="relative text-sm">
                  <span className="absolute -left-[21px] top-1.5 size-2 rounded-full bg-primary" aria-hidden="true" />
                  <span className="font-medium">{EVENT_LABELS[e.action] ?? e.action}</span>
                  {e.new && "status" in e.new && e.new.status ? <span className="text-muted-foreground"> → {String(e.new.status)}</span> : null}
                  <span className="block text-xs text-muted-foreground">{e.actor || "Système"} · {formatDateTime(e.created_at)}{e.public ? " · visible déclarant" : ""}</span>
                </li>
              ))}
            </ol>
          </Card>
        </div>
        <div className="space-y-5">
          <Card className="p-5 sm:p-6">
            <WidgetHeader title="SLA" meta={sla.policy} />
            <dl className="mt-3 space-y-3 text-sm">
              {([["Première réponse", sla.first_response_due, sla.first_response_remaining_seconds, sla.first_response_breached, t.first_response_at],
                ["Résolution", sla.resolution_due, sla.resolution_remaining_seconds, sla.resolution_breached, t.resolved_at]] as const).map(([label, due, rem, breached, done]) => (
                <div key={label} className="rounded-2xl bg-muted p-3">
                  <dt className="text-xs text-muted-foreground">{label}</dt>
                  <dd className={cn("mt-0.5 font-semibold", breached ? "text-destructive" : "")}>
                    {done ? `Atteint le ${formatDateTime(done)}` : breached ? "Dépassé" : sla.paused ? "En pause" : remaining(rem)}
                  </dd>
                  <dd className="text-xs text-muted-foreground">Échéance : {formatDateTime(due)}</dd>
                </div>
              ))}
            </dl>
          </Card>
          <Card className="p-5 sm:p-6">
            <WidgetHeader title="Détails" />
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Équipe</dt><dd>{t.team?.name ?? "Non assignée"}</dd>
              <dt className="text-muted-foreground">Agent</dt><dd>{t.assignee?.name ?? "—"}</dd>
              <dt className="text-muted-foreground">Projet</dt><dd>{t.project ? <Link className="hover:text-brand" to={`/projects/${t.project.id}`}>{t.project.name}</Link> : "—"}</dd>
              <dt className="text-muted-foreground">Tâche</dt><dd>{t.task ? <Link className="hover:text-brand" to={`/tasks/${t.task.id}`}>{t.task.name}</Link> : "—"}</dd>
              <dt className="text-muted-foreground">Déclarant</dt><dd className="break-all">{t.reporter_name || "—"}{t.reporter_email ? ` · ${t.reporter_email}` : ""}</dd>
              <dt className="text-muted-foreground">Réf. externe</dt><dd className="break-all">{t.external_id}</dd>
              <dt className="text-muted-foreground">Environnement</dt><dd>{[t.environment, t.app_version].filter(Boolean).join(" · ") || "—"}</dd>
              {t.url && <><dt className="text-muted-foreground">URL</dt><dd className="break-all"><a href={t.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 hover:text-brand">{t.url}<ExternalLink className="size-3" aria-hidden="true" /></a></dd></>}
            </dl>
            {Object.keys(t.metadata).length > 0 && (
              <details className="mt-3 text-xs"><summary className="cursor-pointer text-muted-foreground">Contexte technique (assaini)</summary>
                <pre className="mt-2 max-h-60 overflow-auto rounded-xl bg-muted p-3">{JSON.stringify(t.metadata, null, 2)}</pre>
              </details>
            )}
          </Card>
          <Card className="p-5 sm:p-6">
            <WidgetHeader title="Pièces jointes" meta={String(t.attachments.length)} />
            {t.attachments.length ? (
              <ul className="mt-3 space-y-2 text-sm">
                {t.attachments.map((a) => (
                  <li key={a.id} className="flex items-center gap-2">
                    <Paperclip className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                    <a href={a.download_url} className="min-w-0 flex-1 truncate hover:text-brand">{a.name}</a>
                    {a.visibility === "INTERNAL" && <Lock className="size-3.5 text-warning" aria-label="Interne" />}
                    <span className="text-xs text-muted-foreground">{Math.max(1, Math.round(a.size / 1024))} Ko</span>
                  </li>
                ))}
              </ul>
            ) : <p className="mt-2 text-sm text-muted-foreground">Aucune pièce jointe.</p>}
          </Card>
        </div>
      </div>

      {assignOpen && <AssignDialog t={t} open={assignOpen} onOpenChange={setAssignOpen} />}
      <Dialog open={escalateOpen} onOpenChange={setEscalateOpen} title="Escalader le ticket" description="Les responsables d'équipe et le propriétaire du workspace sont notifiés.">
        <form className="space-y-4" onSubmit={(e) => {
          e.preventDefault();
          run("escalate", { reason }, "Ticket escaladé.", () => { setEscalateOpen(false); setReason(""); });
        }}>
          <Field id="escalate-reason" label="Motif"><Input id="escalate-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} required /></Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setEscalateOpen(false)}>Annuler</Button>
            <Button type="submit" disabled={pending}>Escalader</Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
