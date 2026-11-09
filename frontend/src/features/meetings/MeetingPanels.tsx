import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown, ArrowRight, ArrowUp, Check, CheckCircle2, Clock, GripVertical, Hand, HelpCircle, Pencil, Plus, Save, Trash2, User, X,
} from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Field, Input, Label, Select, Textarea } from "@/components/ui/input";
import { Avatar, Badge } from "@/components/ui/misc";
import { cn } from "@/lib/utils";
import {
  MEETINGS_KEY, postAction, useRun,
  type AgendaItem, type FormValue, type MeetingDetail, type ReviewField, type ReviewForm,
} from "./api";
import {
  ACTION_STATUS_BADGE, AGENDA_STATUS_BADGE, ATTENDANCE_BADGE, PRIORITY_BADGE, RSVP_BADGE, fmtDate, fmtDateTime, humanSeconds,
  RECORDING_STATUS_BADGE,
} from "./constants";
import { RichHtml } from "./Content";
import { MeetingRecorder } from "./Recorder";
import { RecordingProgress } from "./RecordingProgress";

function Section({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
        {actions}
      </div>
      {children}
    </section>
  );
}

const userOptions = (m: MeetingDetail) => m.participations.map((p) => p.user);

// ─────────────────────────────────────────────────────────────────────
// Notes & ordre du jour
// ─────────────────────────────────────────────────────────────────────
function AgendaItemForm({ m, item, onDone, onCancel }: { m: MeetingDetail; item?: AgendaItem; onDone: () => void; onCancel: () => void }) {
  const [run, pending] = useRun();
  const [title, setTitle] = useState(item?.title ?? "");
  const [owner, setOwner] = useState(item?.owner ? String(item.owner.id) : "");
  const [duration, setDuration] = useState(String(item?.duration_minutes ?? 5));
  const [description, setDescription] = useState(item?.description ?? "");
  const [notes, setNotes] = useState(item?.notes ?? "");
  const idp = item ? `agenda-${item.id}` : "agenda-new";
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    const data: Record<string, FormValue> = { title: title.trim(), owner, duration_minutes: duration || "0", description };
    if (item) data.notes = notes;
    run(item ? `meetings/${m.id}/agenda/${item.id}/` : `meetings/${m.id}/agenda/`, data, onDone);
  };
  return (
    <form onSubmit={submit} className="grid gap-3 rounded-xl border bg-muted/30 p-3 sm:grid-cols-12">
      <div className="sm:col-span-6"><Field id={`${idp}-title`} label="Titre du point *">
        <Input id={`${idp}-title`} required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field></div>
      <div className="sm:col-span-4"><Field id={`${idp}-owner`} label="Responsable">
        <Select id={`${idp}-owner`} value={owner} onChange={(e) => setOwner(e.target.value)}>
          <option value="">— Aucun —</option>
          {userOptions(m).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
        </Select>
      </Field></div>
      <div className="sm:col-span-2"><Field id={`${idp}-duration`} label="Durée (min)">
        <Input id={`${idp}-duration`} type="number" min={0} step={1} value={duration} onChange={(e) => setDuration(e.target.value)} />
      </Field></div>
      <div className="sm:col-span-12"><Field id={`${idp}-description`} label="Description">
        <Textarea id={`${idp}-description`} rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field></div>
      {item && (
        <div className="sm:col-span-12"><Field id={`${idp}-notes`} label="Notes prises pendant le point">
          <Textarea id={`${idp}-notes`} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field></div>
      )}
      <div className="flex justify-end gap-2 sm:col-span-12">
        <Button type="button" variant="outline" size="sm" onClick={onCancel}><X />Annuler</Button>
        <Button type="submit" size="sm" disabled={pending || !title.trim()}><Check />{item ? "Enregistrer" : "Ajouter"}</Button>
      </div>
    </form>
  );
}

function AgendaPanel({ m }: { m: MeetingDetail }) {
  const qc = useQueryClient();
  const [run, pending] = useRun();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [toDelete, setToDelete] = useState<AgendaItem | null>(null);
  const [order, setOrder] = useState<number[] | null>(null);
  const [dragged, setDragged] = useState<number | null>(null);
  const byId = new Map(m.agenda_items.map((i) => [i.id, i]));
  const ids = (order ?? m.agenda_items.map((i) => i.id)).filter((id) => byId.has(id));
  const items = ids.map((id) => byId.get(id)!).concat(m.agenda_items.filter((i) => !ids.includes(i.id)));

  const saveOrder = async (next: number[]) => {
    setOrder(next);
    try {
      await postAction(`meetings/${m.id}/agenda/reorder/`, { order: next.join(",") });
      await qc.invalidateQueries({ queryKey: [...MEETINGS_KEY, m.id] });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setOrder(null);
    }
  };
  const move = (index: number, delta: number) => {
    const next = items.map((i) => i.id);
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target]!, next[index]!];
    void saveOrder(next);
  };
  const dropOn = (targetId: number) => {
    if (dragged == null || dragged === targetId) return;
    const next = items.map((i) => i.id).filter((id) => id !== dragged);
    next.splice(next.indexOf(targetId), 0, dragged);
    setDragged(null);
    void saveOrder(next);
  };

  return (
    <Section title={`Ordre du jour (${m.agenda_items.length})`}
      actions={<Button size="sm" variant="outline" onClick={() => setAdding((v) => !v)} aria-expanded={adding}><Plus />Ajouter un point</Button>}>
      {adding && <AgendaItemForm m={m} onDone={() => setAdding(false)} onCancel={() => setAdding(false)} />}
      <ol className="space-y-2" aria-label="Points de l'ordre du jour">
        {items.map((item, index) => (
          <li key={item.id} draggable={editing !== item.id}
            onDragStart={() => setDragged(item.id)} onDragEnd={() => setDragged(null)}
            onDragOver={(e) => e.preventDefault()} onDrop={() => dropOn(item.id)}
            className={cn("rounded-xl border bg-card p-3", dragged === item.id && "opacity-50", editing === item.id && "ring-1 ring-primary")}>
            {editing === item.id ? (
              <AgendaItemForm m={m} item={item} onDone={() => setEditing(null)} onCancel={() => setEditing(null)} />
            ) : (
              <div className="flex items-start gap-2">
                <span className="mt-1 hidden cursor-move text-subtle-foreground sm:inline" title="Glisser pour réordonner" aria-hidden="true"><GripVertical className="size-4" /></span>
                <Badge className={cn("mt-0.5 shrink-0", AGENDA_STATUS_BADGE[item.status])}>{index + 1}</Badge>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{item.title}</p>
                  {item.description_html && <RichHtml html={item.description_html} className="mt-1 text-xs text-muted-foreground" />}
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                    {item.owner && <span className="inline-flex items-center gap-1"><User className="size-3" aria-hidden="true" />{item.owner.name}</span>}
                    <span className="inline-flex items-center gap-1"><Clock className="size-3" aria-hidden="true" />{item.duration_minutes} min</span>
                    <Badge className={AGENDA_STATUS_BADGE[item.status]}>{item.status_label}</Badge>
                  </div>
                  {item.notes_html && (
                    <div className="mt-2 rounded-lg bg-muted/50 p-2 text-xs"><span className="font-semibold text-brand">Notes : </span><RichHtml html={item.notes_html} className="inline text-xs" /></div>
                  )}
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <Select aria-label={`Statut du point ${item.title}`} className="h-8 w-32 text-xs" value={item.status} disabled={pending}
                    onChange={(e) => run(`meetings/${m.id}/agenda/${item.id}/`, { status: e.target.value })}>
                    {m.agenda_status_choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                  </Select>
                  <div className="flex gap-1">
                    <Button size="icon" variant="ghost" className="size-8" aria-label={`Monter ${item.title}`} disabled={index === 0 || order != null} onClick={() => move(index, -1)}><ArrowUp /></Button>
                    <Button size="icon" variant="ghost" className="size-8" aria-label={`Descendre ${item.title}`} disabled={index === items.length - 1 || order != null} onClick={() => move(index, 1)}><ArrowDown /></Button>
                    <Button size="icon" variant="ghost" className="size-8" aria-label={`Modifier ${item.title}`} onClick={() => setEditing(item.id)}><Pencil /></Button>
                    <Button size="icon" variant="ghost" className="size-8 text-destructive" aria-label={`Supprimer ${item.title}`} onClick={() => setToDelete(item)}><Trash2 /></Button>
                  </div>
                </div>
              </div>
            )}
          </li>
        ))}
        {!items.length && <li className="rounded-xl border border-dashed p-4 text-center text-sm text-muted-foreground">Aucun point. Cliquez sur « Ajouter un point » pour commencer.</li>}
      </ol>
      <ConfirmDialog open={!!toDelete} onOpenChange={(o) => !o && setToDelete(null)} destructive pending={pending}
        title="Supprimer ce point ?" description={toDelete?.title ?? ""} confirmLabel="Supprimer"
        onConfirm={() => toDelete && run(`meetings/${m.id}/agenda/${toDelete.id}/delete/`, undefined, () => setToDelete(null))} />
    </Section>
  );
}

export function NotesTab({ m }: { m: MeetingDetail }) {
  return (
    <div className="space-y-6">
      <AgendaPanel m={m} />
      {m.agenda_html && (
        <details className="rounded-xl border bg-muted/20 p-3">
          <summary className="cursor-pointer text-xs text-muted-foreground">Ordre du jour (texte libre)</summary>
          <RichHtml html={m.agenda_html} className="mt-2" />
        </details>
      )}
      <Section title="Notes / compte-rendu"><RichHtml html={m.notes_html} empty="Aucune note enregistrée." /></Section>
      {m.blockers_html && <Section title="Points bloquants"><RichHtml html={m.blockers_html} /></Section>}
      {m.next_steps_html && <Section title="Prochaine étape"><RichHtml html={m.next_steps_html} /></Section>}
    </div>
  );
}

export function DecisionsTab({ m }: { m: MeetingDetail }) {
  return (
    <div className="space-y-6">
      <RichHtml html={m.decisions_html} empty="Aucune décision tracée." />
      {m.structured_decisions.length > 0 && (
        <Section title="Registre des décisions liées" actions={<Link to="/meetings/decisions" className="text-xs text-brand hover:underline">Registre complet</Link>}>
          <ul className="divide-y rounded-xl border">
            {m.structured_decisions.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                <span className="min-w-0 flex-1">{d.title}</span>
                <span className="flex items-center gap-2 text-xs text-muted-foreground">{d.category_label}<Badge>{d.status_label}</Badge>{fmtDate(d.decided_at)}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Actions → tâches
// ─────────────────────────────────────────────────────────────────────
export function ActionsTab({ m }: { m: MeetingDetail }) {
  const [run, pending] = useRun();
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState("MEDIUM");
  const [due, setDue] = useState("");
  const [owner, setOwner] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    run(`meetings/${m.id}/actions/`, { title: title.trim(), priority, due_date: due, owner }, () => { setTitle(""); setDue(""); setOwner(""); }, "Action ajoutée.");
  };
  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="grid gap-2 rounded-xl bg-muted/40 p-3 sm:grid-cols-12" aria-label="Nouvelle action">
        <div className="sm:col-span-5"><Label htmlFor="action-title" className="sr-only">Nouvelle action</Label>
          <Input id="action-title" placeholder="Nouvelle action…" required maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} /></div>
        <div className="sm:col-span-2"><Label htmlFor="action-priority" className="sr-only">Priorité</Label>
          <Select id="action-priority" value={priority} onChange={(e) => setPriority(e.target.value)}>
            {m.action_priority_choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </Select></div>
        <div className="sm:col-span-2"><Label htmlFor="action-owner" className="sr-only">Responsable</Label>
          <Select id="action-owner" value={owner} onChange={(e) => setOwner(e.target.value)}>
            <option value="">Responsable…</option>
            {userOptions(m).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </Select></div>
        <div className="sm:col-span-2"><Label htmlFor="action-due" className="sr-only">Échéance</Label>
          <Input id="action-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} /></div>
        <Button type="submit" className="sm:col-span-1" disabled={pending || !title.trim()} aria-label="Ajouter l'action"><Plus /><span className="sm:hidden">Ajouter</span></Button>
      </form>
      {!m.project && m.action_items.some((a) => !a.converted_task_id) && (
        <p className="text-xs text-muted-foreground">Sans projet principal, la conversion d'une action en tâche est refusée : rattachez un projet à la réunion.</p>
      )}
      {m.project && !m.can_convert_actions && m.action_items.some((a) => !a.converted_task_id) && (
        <p className="text-xs text-muted-foreground">La conversion en tâche est réservée aux chefs de projet et aux responsables du projet.</p>
      )}
      <ul className="divide-y rounded-xl border">
        {m.action_items.map((a) => (
          <li key={a.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
            <div className="min-w-0 flex-1">
              <p className="font-medium">{a.title}</p>
              {a.description && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{a.description}</p>}
              <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                {a.owner && <span className="inline-flex items-center gap-1"><User className="size-3" aria-hidden="true" />{a.owner.name}</span>}
                {a.due_date && <span className="text-warning">Échéance {fmtDate(a.due_date)}</span>}
                <Badge className={PRIORITY_BADGE[a.priority]}>{a.priority_label}</Badge>
                <Badge className={ACTION_STATUS_BADGE[a.status]}>{a.status_label}</Badge>
              </div>
            </div>
            {a.converted_task_id ? (
              <Button size="sm" variant="outline" asChild><Link to={`/tasks/${a.converted_task_id}`}><CheckCircle2 />Tâche liée</Link></Button>
            ) : (
              <Button size="sm" variant="outline" disabled={pending || !m.project || !m.can_convert_actions}
                onClick={() => run(`meetings/actions/${a.id}/convert/`, undefined, undefined, "Tâche créée.")}><ArrowRight />Convertir en tâche</Button>
            )}
          </li>
        ))}
        {!m.action_items.length && <li className="px-4 py-6 text-center text-sm text-muted-foreground">Aucune action décidée. Lancez l'analyse IA pour les extraire automatiquement des notes.</li>}
      </ul>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Participants : RSVP, présence, pointage
// ─────────────────────────────────────────────────────────────────────
const RSVP_BUTTONS: [string, string, ReactNode][] = [
  ["ACCEPTED", "J'accepte", <Check key="a" />], ["TENTATIVE", "Peut-être", <HelpCircle key="t" />], ["DECLINED", "Je décline", <X key="d" />],
];

export function ParticipantsTab({ m }: { m: MeetingDetail }) {
  const [run, pending] = useRun();
  const [marks, setMarks] = useState<Record<number, string>>({});
  const mine = m.my_participation;
  const stats = m.participations_stats;
  const saveAttendance = () => {
    const data: Record<string, FormValue> = {};
    m.participations.forEach((p) => { data[`attendance_${p.user.id}`] = marks[p.user.id] ?? p.attendance_status; });
    run(`meetings/${m.id}/attendance/`, data, () => setMarks({}));
  };
  return (
    <div className="space-y-6">
      {mine && (
        <div className="rounded-2xl border border-primary/30 bg-primary/5 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-brand">Votre statut</p>
              <p className="mt-1 text-sm">RSVP : <strong>{mine.rsvp_label}</strong>
                {mine.attendance_status !== "UNKNOWN" && <> · Présence : <strong>{mine.attendance_label}</strong></>}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {RSVP_BUTTONS.map(([value, label, icon]) => (
                <Button key={value} size="sm" variant={mine.rsvp_status === value ? "default" : "outline"} aria-pressed={mine.rsvp_status === value}
                  disabled={pending} onClick={() => run(`meetings/${m.id}/rsvp/`, { rsvp_status: value })}>{icon}{label}</Button>
              ))}
              {!mine.self_confirmed && (
                <Button size="sm" disabled={pending} onClick={() => run(`meetings/${m.id}/confirm-presence/`)}><Hand />Je confirme ma présence</Button>
              )}
            </div>
          </div>
        </div>
      )}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-2 lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Participants internes ({m.participations.length})</h3>
            {m.can_mark_attendance && <span className="text-[11px] text-muted-foreground">Vous pouvez marquer la présence</span>}
          </div>
          <ul className="divide-y overflow-hidden rounded-2xl border">
            {m.participations.map((p) => (
              <li key={p.user.id} className="flex flex-wrap items-center gap-3 p-3">
                <Avatar name={p.user.name} className="size-8" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">{p.user.name}</p>
                  <div className="mt-0.5 flex flex-wrap gap-1">
                    <Badge className={RSVP_BADGE[p.rsvp_status]}>RSVP : {p.rsvp_label}</Badge>
                    {!m.can_mark_attendance && <Badge className={ATTENDANCE_BADGE[p.attendance_status]}>{p.attendance_label}</Badge>}
                    {p.self_confirmed && <Badge className="bg-success/15 text-success">Auto-confirmé</Badge>}
                  </div>
                </div>
                {m.can_mark_attendance && (
                  <Select aria-label={`Présence de ${p.user.name}`} className="h-9 w-36 text-xs" value={marks[p.user.id] ?? p.attendance_status}
                    onChange={(e) => setMarks((s) => ({ ...s, [p.user.id]: e.target.value }))}>
                    {m.attendance_choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                  </Select>
                )}
              </li>
            ))}
            {!m.participations.length && <li className="p-6 text-center text-sm text-muted-foreground">Aucun participant interne.</li>}
          </ul>
          {m.can_mark_attendance && m.participations.length > 0 && (
            <div className="flex justify-end"><Button size="sm" disabled={pending} onClick={saveAttendance}><Save />Enregistrer la présence</Button></div>
          )}
        </div>
        <div className="space-y-4">
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Externes</h3>
            <p className="whitespace-pre-line rounded-xl bg-muted/40 p-3 text-sm">{m.external_participants || "—"}</p>
          </div>
          <dl className="space-y-2 rounded-2xl border bg-muted/20 p-4 text-xs">
            <dt className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-brand">Statistiques RSVP</dt>
            {([["Accepté", stats.accepted, "text-success"], ["Peut-être", stats.tentative, "text-info"], ["Décliné", stats.declined, "text-destructive"],
              ["Sans réponse", stats.pending, "text-warning"], ["Présents", stats.present, "text-success"], ["Absents", stats.absent, "text-destructive"]] as const)
              .map(([label, value, tone]) => (
                <div key={label} className="flex justify-between"><span>{label}</span><strong className={tone}>{value ?? 0}</strong></div>
              ))}
          </dl>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Tour de table (formset MeetingProjectReview)
// ─────────────────────────────────────────────────────────────────────
const initialReviewValue = (f: ReviewField): string | boolean =>
  f.type === "checkbox" ? Boolean(f.value) : f.value == null ? "" : String(f.value);

function ReviewInput({ f, name, value, onChange }: { f: ReviewField; name: string; value: string | boolean; onChange: (v: string | boolean) => void }) {
  const id = `review-${name}`;
  if (f.type === "checkbox") {
    return (
      <label className="flex items-center gap-2 text-xs text-destructive">
        <input id={id} type="checkbox" className="size-4 accent-primary" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        {f.name === "DELETE" ? "Supprimer ce projet de la revue" : f.label}
      </label>
    );
  }
  let control: ReactNode;
  if (f.type === "select") {
    control = <Select id={id} value={String(value)} onChange={(e) => onChange(e.target.value)}>{f.choices?.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</Select>;
  } else if (f.type === "textarea") {
    control = <Textarea id={id} rows={2} value={String(value)} onChange={(e) => onChange(e.target.value)} />;
  } else {
    control = <Input id={id} type={f.type === "number" ? "number" : f.type === "date" ? "date" : "text"} min={f.min ?? undefined} max={f.max ?? undefined}
      maxLength={f.max_length ?? undefined} value={String(value)} onChange={(e) => onChange(e.target.value)} />;
  }
  return <Field id={id} label={f.label}>{control}</Field>;
}

const REVIEW_WIDE = new Set(["achievements", "actions_to_take"]);

export function ReviewsTab({ m }: { m: MeetingDetail }) {
  const reviews = m.reviews;
  const [run, pending] = useRun();
  const [values, setValues] = useState<Record<string, string | boolean>>(() => {
    const out: Record<string, string | boolean> = {};
    reviews?.forms.forEach((form) => form.fields.forEach((f) => { out[`${form.prefix}-${f.name}`] = initialReviewValue(f); }));
    return out;
  });
  if (!reviews || !reviews.forms.length) {
    return (
      <p className="text-sm text-muted-foreground">
        Aucun projet rattaché à cette réunion. <Link className="text-brand hover:underline" to={`/meetings/${m.id}/edit`}>Modifiez la réunion</Link> pour ajouter des projets à passer en revue.
      </p>
    );
  }
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const data: Record<string, FormValue> = { ...reviews.management };
    Object.entries(values).forEach(([k, v]) => { data[k] = v; });
    run(`meetings/${m.id}/reviews/`, data);
  };
  const label = (form: ReviewForm) => form.project?.name ?? "— Nouveau —";
  return (
    <form onSubmit={submit} className="space-y-4">
      <p className="text-sm text-muted-foreground">Pour chaque projet : statut, avancement, réalisations, bloquants, décisions et actions à mener.</p>
      {reviews.forms.map((form, index) => (
        <details key={form.prefix} open={index === 0} className="rounded-2xl border bg-muted/20 p-4">
          <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2 text-sm font-semibold">
            <span>{label(form)}</span>
            <span className="text-[11px] font-normal text-muted-foreground">{form.status_label} · {form.progress_pct} %</span>
          </summary>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {form.fields.filter((f) => f.type !== "hidden").map((f) => {
              const name = `${form.prefix}-${f.name}`;
              return (
                <div key={name} className={REVIEW_WIDE.has(f.name) || f.type === "checkbox" ? "md:col-span-2" : undefined}>
                  <ReviewInput f={f} name={name} value={values[name] ?? ""} onChange={(v) => setValues((s) => ({ ...s, [name]: v }))} />
                </div>
              );
            })}
          </div>
        </details>
      ))}
      <div className="flex justify-end"><Button type="submit" disabled={pending}><Save />Enregistrer les revues</Button></div>
    </form>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Enregistrements
// ─────────────────────────────────────────────────────────────────────
/**
 * Capture + suivi du traitement IA — toujours monté sous les onglets (comme
 * `recorder_widget.html`) : la capture continue pendant qu'on édite l'ordre du
 * jour, les notes ou les présences.
 */
export function RecorderPanel({ m, activeId, onUploaded, onDeleted }: {
  m: MeetingDetail; activeId: number | null; onUploaded: (recordingId: number) => void; onDeleted?: (recordingId: number) => void;
}) {
  const live = activeId ?? m.recordings.find((r) => !r.is_final)?.id ?? null;
  return (
    <section aria-label="Enregistrement de la réunion" className="space-y-4">
      {live != null && (
        <Card>
          <CardHeader><CardTitle>Traitement en cours</CardTitle></CardHeader>
          <CardContent><RecordingProgress key={live} recordingId={live} meetingId={m.id} initial={m.recordings.find((r) => r.id === live)} onDeleted={onDeleted} /></CardContent>
        </Card>
      )}
      <MeetingRecorder meetingId={m.id} maxUploadMb={m.max_upload_mb} onUploaded={onUploaded} />
    </section>
  );
}

/** Liste des enregistrements de la réunion (la capture est dans `RecorderPanel`). */
export function RecordingsTab({ m, onDeleted }: { m: MeetingDetail; onDeleted?: (recordingId: number) => void }) {
  const [run, pending] = useRun();
  const [toDelete, setToDelete] = useState<number | null>(null);
  return (
    <div className="space-y-6">
      <Section title={`Enregistrements (${m.recordings.length})`}>
        <ul className="divide-y rounded-2xl border">
          {m.recordings.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{fmtDateTime(r.created_at)}</p>
                <p className="text-xs text-muted-foreground">{r.recorded_by || "—"} · {humanSeconds(r.duration_seconds)}</p>
              </div>
              <Badge className={RECORDING_STATUS_BADGE[r.status]}>{r.status_label}</Badge>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" asChild>
                  <Link to={`/meetings/${m.id}/recordings/${r.id}`}>
                    {r.status === "waiting_speaker_mapping" ? "Identifier les voix" : r.has_summary || r.status === "completed" ? "Compte-rendu" : "Suivre"}
                  </Link>
                </Button>
                <Button size="sm" variant="ghost" className="text-destructive" aria-label={`Supprimer l'enregistrement du ${fmtDateTime(r.created_at)}`}
                  onClick={() => setToDelete(r.id)}><Trash2 /></Button>
              </div>
            </li>
          ))}
          {!m.recordings.length && <li className="p-6 text-center text-sm text-muted-foreground">Aucun enregistrement pour cette réunion.</li>}
        </ul>
      </Section>
      <ConfirmDialog open={toDelete != null} onOpenChange={(o) => !o && setToDelete(null)} destructive pending={pending}
        title="Supprimer définitivement cet enregistrement ?" description="L'audio, la transcription, le compte-rendu et les extractions IA seront supprimés."
        confirmLabel="Supprimer" onConfirm={() => toDelete != null && run(`meetings/recordings/${toDelete}/delete/`, undefined, () => {
          onDeleted?.(toDelete);
          setToDelete(null);
        })} />
    </div>
  );
}
