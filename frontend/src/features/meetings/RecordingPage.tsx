import {
  AlertTriangle, ArrowLeft, Check, FileText, FileType2, Gavel, Lightbulb, Link2, ListChecks, Loader2, PenLine, RefreshCw, Save, Send, Sparkles, Trash2,
  UserCircle,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, Select, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/misc";
import { cn, legacyUrl } from "@/lib/utils";
import { DownloadButton } from "./DownloadButton";
import { ApiError } from "@/services/api";
import { MEETINGS_KEY, messagesOf, postAction, useRecording, useRun, type Extraction, type RecordingDetail } from "./api";
import { PRIORITY_BADGE, fmtDateTime } from "./constants";
import { Markdown } from "./Content";
import { RecordingProgress } from "./RecordingProgress";

function Block({ title, icon, children, description }: { title: string; icon: ReactNode; children: ReactNode; description?: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">{icon}{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

const fmtClock = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// ─── Identification des voix (ancienne page `recording_speakers.html`) ───
function SpeakersBlock({ rec }: { rec: RecordingDetail }) {
  const [run, pending] = useRun();
  const [mapping, setMapping] = useState<Record<string, string>>(
    () => Object.fromEntries(rec.speakers.map((sp) => [sp.label, sp.mapped_participant_id ? String(sp.mapped_participant_id) : ""])),
  );
  // Associations modifiées non enregistrées : la génération utiliserait l'ancien mapping.
  const dirty = rec.speakers.some((sp) => (mapping[sp.label] ?? "") !== (sp.mapped_participant_id ? String(sp.mapped_participant_id) : ""));
  const save = (e: FormEvent) => {
    e.preventDefault();
    const data = Object.fromEntries(Object.entries(mapping).filter(([, v]) => v).map(([label, v]) => [`speaker_${label}`, v]));
    run(`meetings/recordings/${rec.id}/speakers/`, data);
  };
  return (
    <Block title="Identifier les voix" icon={<UserCircle className="size-4" aria-hidden="true" />}
      description={`${rec.speakers.length} voix distincte(s) détectée(s). Écoutez chaque extrait et associez-le à un participant : cette étape est obligatoire pour générer un compte-rendu nominatif.`}>
      <form onSubmit={save} className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          {rec.speakers.map((sp) => {
            const suggested = Boolean(sp.mapped_participant_id) && !sp.is_confirmed;
            const id = `speaker-${sp.label}`;
            return (
              <div key={sp.label} className={cn("rounded-2xl border p-4", suggested ? "border-primary/40 bg-primary/5" : "bg-card")}>
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <h3 className="flex items-center gap-2 font-semibold">
                    {sp.display_name || sp.label}
                    {sp.display_name && sp.display_name !== sp.label && <span className="text-xs font-normal text-muted-foreground">({sp.label})</span>}
                    {sp.is_confirmed ? <Badge className="bg-success/15 text-success">Confirmé</Badge>
                      : suggested ? <Badge className="bg-primary/10 text-primary" title="Voix reconnue grâce aux identifications précédentes — vérifiez avant de confirmer"><Sparkles className="mr-1 size-3" />Suggéré IA</Badge> : null}
                  </h3>
                  <span className="text-[11px] text-muted-foreground">{Math.round(sp.total_duration_seconds)} s · {sp.total_segments} seg.</span>
                </div>
                {sp.sample_url
                  ? <audio controls preload="metadata" className="mb-3 w-full" src={legacyUrl(sp.sample_url)} aria-label={`Extrait audio de ${sp.label}`} />
                  : <p className="mb-3 text-xs italic text-muted-foreground">Extrait audio non disponible</p>}
                <Field id={id} label={suggested ? "Associer à (pré-rempli par l'IA, à vérifier)" : "Associer à"}>
                  <Select id={id} value={mapping[sp.label] ?? ""} onChange={(e) => setMapping((s) => ({ ...s, [sp.label]: e.target.value }))}>
                    <option value="">— Sélectionner —</option>
                    {rec.participants.map((p) => <option key={p.id} value={p.id}>{p.full_name}{p.email ? ` (${p.email})` : ""}</option>)}
                  </Select>
                </Field>
              </div>
            );
          })}
          {!rec.speakers.length && <p className="rounded-2xl border p-6 text-center text-sm text-muted-foreground md:col-span-2">Aucune voix détectée — le traitement est peut-être encore en cours.</p>}
        </div>
        {rec.speakers.length > 0 && (
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="submit" variant="outline" disabled={pending}><Save />Enregistrer les associations</Button>
            {rec.all_mapped && (
              <Button type="button" disabled={pending || dirty} title={dirty ? "Enregistrez d'abord les associations modifiées" : undefined} onClick={() => run(`meetings/recordings/${rec.id}/confirm-speakers/`, undefined, undefined, "Génération du compte-rendu IA lancée.")}>
                <Check />Confirmer et générer le CR
              </Button>
            )}
          </div>
        )}
      </form>
    </Block>
  );
}

// ─── Extractions IA à valider (cases à cocher → vue Django correspondante) ───
function Checklist({ items, name, path, submitLabel, render, primary, locked }: {
  items: Extraction[]; name: string; path: string; submitLabel: string; render: (e: Extraction) => ReactNode; primary?: boolean;
  /** Élément non sélectionnable (droits Django insuffisants). */
  locked?: (e: Extraction) => boolean;
}) {
  const [run, pending] = useRun();
  const [checked, setChecked] = useState<number[]>([]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(path, { [name]: checked }, () => setChecked([]));
  };
  return (
    <form onSubmit={submit} className="space-y-2">
      {items.map((x) => (
        <label key={x.id} className={cn("flex cursor-pointer items-start gap-3 rounded-xl border bg-muted/30 p-3 hover:bg-muted/50",
          (x.is_accepted || locked?.(x)) && "cursor-default opacity-80")}>
          <input type="checkbox" className="mt-1 size-4 accent-primary" disabled={x.is_accepted || Boolean(locked?.(x))}
            checked={x.is_accepted || checked.includes(x.id)}
            onChange={(e) => setChecked((s) => (e.target.checked ? [...s, x.id] : s.filter((v) => v !== x.id)))} />
          <span className="min-w-0 flex-1">{render(x)}</span>
        </label>
      ))}
      <div className="flex justify-end pt-1">
        <Button type="submit" size="sm" variant={primary ? "default" : "outline"} disabled={pending || !checked.length}>{primary && <Check />}{submitLabel}</Button>
      </div>
    </form>
  );
}

const Hints = ({ x }: { x: Extraction }) => (
  <span className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
    {x.assignee_hint && <span>{x.assignee_hint}</span>}
    {x.due_date_hint && <span>{x.due_date_hint}</span>}
    {x.priority_hint && <Badge className={PRIORITY_BADGE[x.priority_hint.toUpperCase()]}>{x.priority_hint.toUpperCase()}</Badge>}
    {x.confidence > 0 && <span>Confiance IA {Math.round(x.confidence)} %</span>}
  </span>
);

function EmailDialog({ rec, open, onOpenChange }: { rec: RecordingDetail; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [run, pending] = useRun();
  const [extra, setExtra] = useState("");
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Envoyer le compte-rendu par email"
      description={`Le compte-rendu (Word) est envoyé à tous les participants internes (${rec.meeting.internal_participants_count})${rec.meeting.has_external_participants ? " et aux adresses des participants externes" : ""}.`}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); run(`meetings/recordings/${rec.id}/send-minutes/`, { extra_emails: extra }, () => { setExtra(""); onOpenChange(false); }); }}>
        <Field id="extra-emails" label="Adresses supplémentaires (facultatif — virgule ou retour à la ligne)">
          <Textarea id="extra-emails" rows={2} className="font-mono text-xs" placeholder="exemple@client.com, marie.dupont@autre.fr" value={extra} onChange={(e) => setExtra(e.target.value)} />
        </Field>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
          <Button type="submit" disabled={pending}><Send />Envoyer maintenant</Button>
        </div>
      </form>
    </Dialog>
  );
}

/** Enregistrement : suivi du traitement, voix, compte-rendu IA, extractions, transcription, exports. */
export function RecordingPage() {
  const params = useParams();
  const meetingId = Number(params.id);
  const recordingId = Number(params.recordingId);
  const navigate = useNavigate();
  // « Régénérer CR » sur un CR terminé : le statut reste « completed » tant que la
  // tâche Celery n'a pas démarré → suivi de la fiche jusqu'au nouveau CR (ou 5 min).
  const [regenFrom, setRegenFrom] = useState<string | null>(null);
  const awaitingRegen = (d: RecordingDetail | undefined) => regenFrom !== null && Boolean(d?.is_final) && (d?.completed_at ?? "") === regenFrom;
  const { data: rec, isPending, isError, error, refetch } = useRecording(recordingId, (d) => (awaitingRegen(d) ? 4000 : false));
  useEffect(() => {
    if (regenFrom === null) return;
    const id = setTimeout(() => setRegenFrom(null), 5 * 60_000);
    return () => clearTimeout(id);
  }, [regenFrom]);
  const [run, pending] = useRun();
  const [dialog, setDialog] = useState<"email" | "delete" | null>(null);
  const [deleting, setDeleting] = useState(false);
  const qc = useQueryClient();

  if (isPending) return <PageSkeleton />;
  // Échec d'un simple rafraîchissement : on garde la page affichée.
  if (isError && !rec) return <ErrorState message={error instanceof ApiError && error.status === 404 ? "Enregistrement introuvable." : error.message} onRetry={() => void refetch()} />;
  if (!rec) return <PageSkeleton />;
  const mId = rec.meeting.id || meetingId;
  const remove = async () => {
    setDeleting(true);
    try {
      messagesOf(await postAction(`meetings/recordings/${rec.id}/delete/`), "Enregistrement supprimé.").forEach((m) => toast.success(m));
      navigate(`/meetings/${mId}?tab=recordings`);
      void qc.invalidateQueries({ queryKey: [...MEETINGS_KEY, mId] });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setDeleting(false);
      setDialog(null);
    }
  };
  const suggestions = [...rec.project_suggestions, ...rec.sprint_suggestions, ...rec.milestone_suggestions, ...rec.task_suggestions];
  const suggestionTitle: Record<string, string> = {
    project_suggestion: "Nouveau projet", sprint_suggestion: "Sprint", milestone_suggestion: "Jalon", task_suggestion: "Tâche",
  };
  // Mêmes règles que RecordingConvertSuggestionView (contrôle effectif côté Django).
  const suggestionLocked = (s: Extraction) =>
    (s.kind === "project_suggestion" && !rec.can_create_projects) || (s.kind === "task_suggestion" && !rec.can_create_tasks);

  return (
    <div className="space-y-6">
      <PageHeader eyebrow={rec.meeting.title} title="Compte-rendu de l'enregistrement"
        description={<>Statut : {rec.status_label}{rec.summary_provider && ` · via ${rec.summary_provider}`}{rec.transcription_provider && ` · transcription ${rec.transcription_provider}`}
          {" · "}enregistré le {fmtDateTime(rec.created_at)}{rec.recorded_by && ` par ${rec.recorded_by}`}</>}
        actions={<>
          <Button variant="outline" asChild><Link to={`/meetings/${mId}?tab=recordings`}><ArrowLeft />Retour à la réunion</Link></Button>
          {rec.downloads.docx && <DownloadButton href={rec.downloads.docx} filename="compte-rendu.docx"><FileText />Word</DownloadButton>}
          {rec.downloads.pdf && <DownloadButton href={rec.downloads.pdf} filename="compte-rendu.pdf"><FileType2 />PDF</DownloadButton>}
          <Button variant="outline" onClick={() => setDialog("email")}><Send />Envoyer par email</Button>
          <Button variant="outline" disabled={pending || awaitingRegen(rec)} title="Régénérer le compte-rendu IA"
            onClick={() => {
              const from = rec.completed_at ?? "";
              run(`meetings/recordings/${rec.id}/regenerate/`, undefined, () => setRegenFrom(from), "Régénération du compte-rendu lancée.");
            }}><RefreshCw />Régénérer CR</Button>
          <Button variant="outline" className="text-destructive" onClick={() => setDialog("delete")}><Trash2 />Supprimer</Button>
        </>} />

      {(!rec.is_final || rec.status === "failed") && <RecordingProgress recordingId={rec.id} meetingId={mId} initial={rec} compact />}
      {awaitingRegen(rec) && (
        <p role="status" className="flex items-center gap-2 rounded-xl border bg-muted/40 p-3 text-sm text-muted-foreground">
          <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden="true" />
          Régénération demandée — le nouveau compte-rendu s'affichera ici automatiquement.
        </p>
      )}

      {rec.audio_url && (
        <Card><CardContent className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Audio de la réunion{rec.original_filename && ` · ${rec.original_filename}`}</p>
          <audio controls preload="none" className="w-full" src={legacyUrl(rec.audio_url)} aria-label="Audio complet de l'enregistrement" />
        </CardContent></Card>
      )}

      {(rec.speakers.length > 0 || rec.status === "waiting_speaker_mapping") && <SpeakersBlock key={rec.speakers.map((s) => `${s.label}:${s.mapped_participant_id}`).join("|")} rec={rec} />}

      {rec.summary_markdown && (
        <Block title="Résumé exécutif" icon={<PenLine className="size-4" aria-hidden="true" />}><Markdown text={rec.summary_markdown} /></Block>
      )}

      {rec.decisions.length > 0 && (
        <Block title={`Décisions détectées (${rec.decisions.length})`} icon={<Gavel className="size-4" aria-hidden="true" />}>
          <Checklist items={rec.decisions} name="accept_decision" path={`meetings/recordings/${rec.id}/decisions/`} submitLabel="Valider les décisions cochées"
            render={(d) => <>
              <span className="block text-sm font-medium">{d.title}</span>
              {d.description && <span className="mt-1 block text-xs text-muted-foreground">{d.description}</span>}
              {d.is_accepted && <span className="mt-1 block text-[10px] text-success">Validée</span>}
            </>} />
        </Block>
      )}

      {rec.actions.length > 0 && (
        <Block title={`Actions à créer (${rec.actions.length})`} icon={<ListChecks className="size-4" aria-hidden="true" />}>
          <Checklist items={rec.actions} name="accept_action" path={`meetings/recordings/${rec.id}/actions/`} submitLabel="Créer les actions cochées"
            render={(a) => <>
              <span className="block text-sm font-medium">{a.title}</span>
              <Hints x={a} />
              {a.description && <span className="mt-1 block text-xs text-muted-foreground">{a.description}</span>}
              {a.is_accepted && <span className="mt-1 block text-[10px] text-success">Action créée</span>}
            </>} />
        </Block>
      )}

      {suggestions.length > 0 && (
        <Block title="Suggestions IA — nouveaux éléments à créer" icon={<Lightbulb className="size-4" aria-hidden="true" />}
          description="L'IA propose de créer ces éléments suite aux échanges. Sélectionnez ce que vous souhaitez créer.">
          <Checklist items={suggestions} name="accept_suggestion" path={`meetings/recordings/${rec.id}/suggestions/`} submitLabel="Créer les éléments cochés" primary
            locked={suggestionLocked}
            render={(s) => <>
              <span className="block text-sm font-medium">{suggestionTitle[s.kind] ?? s.kind_label} : {s.title}</span>
              {s.kind === "task_suggestion" ? <Hints x={s} /> : s.due_date_hint ? <span className="mt-1 block text-[11px] text-muted-foreground">{s.due_date_hint}</span> : null}
              {s.description && <span className="mt-1 block line-clamp-3 text-xs text-muted-foreground">{s.description}</span>}
              {(s.kind === "sprint_suggestion" || s.kind === "milestone_suggestion") && !s.is_accepted && (
                <span className="mt-1 block text-[10px] italic text-muted-foreground">Nécessite un projet — création manuelle à finaliser ensuite.</span>
              )}
              {!s.is_accepted && suggestionLocked(s) && (
                <span className="mt-1 block text-[10px] italic text-muted-foreground">
                  {s.kind === "project_suggestion" ? "Création de projet réservée aux propriétaires et chefs de projet." : "Création de tâche réservée aux chefs de projet et responsables du projet."}
                </span>
              )}
              {s.is_accepted && <span className="mt-1 block text-[10px] text-success">Créé / accepté</span>}
            </>} />
        </Block>
      )}

      {rec.mentions.length > 0 && (
        <Block title="Entités DevFlow mentionnées" icon={<Link2 className="size-4" aria-hidden="true" />}>
          <ul className="grid gap-2 md:grid-cols-2">
            {rec.mentions.map((x) => (
              <li key={x.id} className="rounded-xl border bg-muted/30 px-3 py-2 text-sm">
                <p>{x.title}</p>
                <p className="mt-0.5 text-[10px] text-muted-foreground">{x.kind_label}{x.confidence > 0 && ` · confiance ${Math.round(x.confidence)} %`}</p>
                {x.description && <p className="mt-1 line-clamp-2 text-[11px] italic text-muted-foreground">« {x.description} »</p>}
              </li>
            ))}
          </ul>
        </Block>
      )}

      {rec.risks.length > 0 && (
        <Block title={`Points de vigilance (${rec.risks.length})`} icon={<AlertTriangle className="size-4" aria-hidden="true" />}>
          <ul className="space-y-2">
            {rec.risks.map((x) => (
              <li key={x.id} className="rounded-xl border border-warning/30 bg-warning/10 p-3">
                <p className="text-sm font-medium text-warning">{x.title}</p>
                {x.description && <p className="mt-1 text-xs text-foreground/80">{x.description}</p>}
              </li>
            ))}
          </ul>
        </Block>
      )}

      {(rec.transcript || rec.segments.length > 0) && (
        <details className="rounded-2xl border bg-card p-5">
          <summary className="cursor-pointer font-semibold">Transcription complète</summary>
          {rec.segments.length > 0 ? (
            <ol className="mt-3 space-y-2">
              {rec.segments.map((s, i) => (
                <li key={i} className="grid gap-x-3 text-sm sm:grid-cols-[7rem_1fr]">
                  <span className="text-xs text-muted-foreground"><span className="font-mono">{fmtClock(s.start)}</span> · <strong className="text-foreground">{s.speaker}</strong></span>
                  <span className="break-words">{s.text}</span>
                </li>
              ))}
              {rec.segments_total > rec.segments.length && <li className="text-xs text-muted-foreground">… {rec.segments_total - rec.segments.length} segment(s) supplémentaire(s) dans le document Word / PDF.</li>}
            </ol>
          ) : <pre className="mt-3 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-muted-foreground">{rec.transcript}</pre>}
        </details>
      )}

      <p className="text-right text-xs text-muted-foreground">
        {rec.tokens_used} tokens utilisés{rec.completed_at && ` · terminé le ${fmtDateTime(rec.completed_at)}`}
      </p>

      <EmailDialog rec={rec} open={dialog === "email"} onOpenChange={(o) => setDialog(o ? "email" : null)} />
      <ConfirmDialog open={dialog === "delete"} onOpenChange={(o) => !o && setDialog(null)} destructive pending={deleting}
        title="Supprimer définitivement cet enregistrement ?" description="Audio, compte-rendu et extractions IA seront supprimés."
        confirmLabel="Supprimer" onConfirm={() => void remove()} />
    </div>
  );
}
