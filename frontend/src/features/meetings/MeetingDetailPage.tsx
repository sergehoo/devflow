import { Bot, Clock, FileText, FileType2, Link2, MapPin, PenLine, Pencil, Send, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/misc";
import { cn } from "@/lib/utils";
import { DownloadButton } from "./DownloadButton";
import { ApiError, api } from "@/services/api";
import { messagesOf, toForm, useMeeting, useMeetingAction } from "./api";
import { MEETING_STATUS_BADGE, TABS, fmtDateTime, type TabId } from "./constants";
import { Markdown } from "./Content";
import { ActionsTab, DecisionsTab, NotesTab, ParticipantsTab, RecorderPanel, RecordingsTab, ReviewsTab } from "./MeetingPanels";

interface AIProcessResult { ok?: boolean; action_items_created?: number; risks_created?: number; used_provider?: string; messages?: string[] }

/** Fiche réunion complète (ancienne `meeting/detail.html` + widget d'enregistrement). */
export function MeetingDetailPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const { data: m, isPending, isError, error, refetch } = useMeeting(id);
  const action = useMeetingAction();
  const [dialog, setDialog] = useState<"send" | "delete" | null>(null);
  const [includeExternal, setIncludeExternal] = useState(true);
  const [deleting, setDeleting] = useState(false);
  const [activeRecording, setActiveRecording] = useState<number | null>(null);
  const forgetRecording = (rid: number) => setActiveRecording((cur) => (cur === rid ? null : cur));
  const tab = (TABS.some((t) => t.id === search.get("tab")) ? search.get("tab") : "notes") as TabId;
  // Mobile : l'onglet actif (ex. ?tab=recordings) est ramené dans la barre défilante, sans faire défiler la page.
  useEffect(() => {
    const el = document.getElementById(`tab-${tab}`);
    const list = el?.parentElement;
    if (!el || !list) return;
    const [d, l] = [el.getBoundingClientRect(), list.getBoundingClientRect()];
    if (d.left < l.left || d.right > l.right) list.scrollLeft += d.left - l.left - 12;
  }, [tab, isPending]);

  if (isPending) return <PageSkeleton />;
  // Échec d'un simple rafraîchissement : on garde la fiche (et l'enregistreur) montée.
  if (isError && !m) return <ErrorState message={error instanceof ApiError && error.status === 404 ? "Réunion introuvable." : error.message} onRetry={() => void refetch()} />;
  if (!m) return <PageSkeleton />;

  const aiProcess = () => action.mutate({ path: `meetings/${id}/ai-process/` }, {
    onSuccess: (r) => {
      const res = r as AIProcessResult;
      toast.success(res.ok ? `IA (${res.used_provider || "—"}) — ${res.action_items_created ?? 0} action(s), ${res.risks_created ?? 0} risque(s) créé(s).`
        : messagesOf(r, "Analyse terminée.")[0]);
    },
    onError: (e) => toast.error(e.message),
  });
  const aiSummary = () => action.mutate({ path: `meetings/${id}/ai-summary/` }, {
    onSuccess: (r) => messagesOf(r, "Résumé IA généré.").forEach((msg) => toast.success(msg)),
    onError: (e) => toast.error(e.message),
  });
  const sendMinutes = () => action.mutate({ path: `meetings/${id}/send-minutes/`, data: { include_external: includeExternal ? "1" : "0" } }, {
    onSuccess: (r) => { messagesOf(r, "Envoi lancé.").forEach((msg) => toast.success(msg)); setDialog(null); },
    onError: (e) => toast.error(e.message),
  });
  const remove = async () => {
    setDeleting(true);
    try {
      const r = await api<{ messages?: string[] }>(`resources/meeting/${id}/delete/`, { method: "POST", body: toForm() });
      messagesOf(r, "Réunion supprimée.").forEach((msg) => toast.success(msg));
      navigate("/meetings");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setDeleting(false);
      setDialog(null);
    }
  };
  const setTab = (t: TabId) => setSearch((s) => { if (t === "notes") s.delete("tab"); else s.set("tab", t); return s; }, { replace: true });
  const counts: Partial<Record<TabId, number>> = { actions: m.action_items.length, participants: m.participations.length, recordings: m.recordings.length,
    reviews: m.reviews?.forms.length ?? 0 };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={`Réunion · ${fmtDateTime(m.scheduled_at)}`}
        title={m.title}
        description={
          <span className="flex flex-col gap-2">
            <span className="flex flex-wrap items-center gap-2">
              <Badge className={MEETING_STATUS_BADGE[m.status]}>{m.status_label}</Badge>
              <Badge className="bg-info/15 text-info">{m.type_label}</Badge>
              <span className="inline-flex items-center gap-1 text-xs"><Clock className="size-3" aria-hidden="true" />{m.duration_label}</span>
            </span>
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {m.project ? <Link to={`/projects/${m.project.id}`} className="hover:text-primary">{m.project.name}</Link>
                : m.projects.length ? (
                  <span>Revue de {m.projects.length} projet{m.projects.length > 1 ? "s" : ""} :{" "}
                    {m.projects.slice(0, 3).map((p, i) => <span key={p.id}>{i > 0 && ", "}<Link to={`/projects/${p.id}`} className="hover:text-primary">{p.name}</Link></span>)}
                    {m.projects.length > 3 && ` +${m.projects.length - 3}`}
                  </span>
                ) : <span className="italic">Réunion libre (sans projet)</span>}
              {m.organizer && <span>Organisée par <strong className="text-foreground">{m.organizer}</strong></span>}
              {m.location && <span className="inline-flex items-center gap-1"><MapPin className="size-3" aria-hidden="true" />{m.location}</span>}
              {m.meeting_link && <a href={m.meeting_link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-info hover:underline"><Link2 className="size-3" aria-hidden="true" />Lien visio</a>}
            </span>
          </span>
        }
        actions={
          <>
            <Button disabled={action.isPending} onClick={aiProcess}><Sparkles />{action.isPending && action.variables?.path.endsWith("ai-process/") ? "Analyse en cours…" : "Analyser par IA"}</Button>
            <Button variant="outline" disabled={action.isPending} onClick={aiSummary} title="Génère un compte-rendu structuré par IA"><PenLine />Résumé IA</Button>
            {m.downloads.docx && <DownloadButton href={m.downloads.docx} filename="compte-rendu.docx"><FileText />Word</DownloadButton>}
            {m.downloads.pdf && <DownloadButton href={m.downloads.pdf} filename="compte-rendu.pdf"><FileType2 />PDF</DownloadButton>}
            <Button variant="outline" onClick={() => setDialog("send")} title="Envoie le compte-rendu Word par email aux participants"><Send />Envoyer</Button>
            <Button variant="outline" asChild><Link to={`/meetings/${id}/edit`}><Pencil />Modifier</Link></Button>
            <Button variant="outline" className="text-destructive" aria-label="Supprimer la réunion" onClick={() => setDialog("delete")}><Trash2 /></Button>
          </>
        }
      />

      <section aria-label="Indicateurs" className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {([["Participants", m.participants_count], ["Actions", m.action_items.length], ["Pièces jointes", m.attachments_count], ["Sprint", m.sprint?.name ?? "—"]] as const).map(([label, value]) => (
          <Card key={label}><CardContent className="p-4">
            <p className="text-[11px] font-semibold uppercase text-muted-foreground">{label}</p>
            <p className="mt-1 truncate font-serif text-xl font-semibold">{value}</p>
          </CardContent></Card>
        ))}
      </section>

      {m.ai_summary && (
        <Card>
          <CardContent className="flex gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground" aria-hidden="true"><Bot className="size-5" /></span>
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold">Synthèse IA</h2>
              <p className="text-[11px] text-muted-foreground">Fournisseur : {m.ai_used_provider || "—"} · {fmtDateTime(m.ai_extracted_at)}</p>
              <Markdown text={m.ai_summary} className="mt-3" />
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="overflow-hidden">
        <div role="tablist" aria-label="Sections de la réunion" className="flex gap-1 overflow-x-auto border-b bg-muted/40 px-3 pt-3">
          {TABS.map((t) => (
            <button key={t.id} type="button" role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls={`panel-${t.id}`}
              onClick={() => setTab(t.id)}
              className={cn("shrink-0 rounded-t-xl border border-b-0 px-4 py-2 text-sm font-semibold transition-colors",
                tab === t.id ? "bg-card text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
              {t.label}{counts[t.id] != null && ` (${counts[t.id]})`}
            </button>
          ))}
        </div>
        <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="p-4 sm:p-6">
          {tab === "notes" && <NotesTab m={m} />}
          {tab === "decisions" && <DecisionsTab m={m} />}
          {tab === "actions" && <ActionsTab m={m} />}
          {tab === "participants" && <ParticipantsTab m={m} />}
          {tab === "reviews" && <ReviewsTab key={m.reviews?.forms.map((f) => f.id).join(",") ?? "none"} m={m} />}
          {tab === "recordings" && <RecordingsTab m={m} onDeleted={forgetRecording} />}
        </div>
      </Card>

      {/* Hors des onglets (comme l'ancienne fiche) : la capture continue quand on change d'onglet. */}
      <RecorderPanel m={m} activeId={activeRecording} onUploaded={setActiveRecording} onDeleted={forgetRecording} />

      <footer className="flex flex-wrap gap-x-4 gap-y-1 px-1 text-xs text-muted-foreground">
        <span>Créée par {m.created_by || "—"} le {fmtDateTime(m.created_at)}</span>
        {m.updated_by && <span>· Mise à jour par {m.updated_by} le {fmtDateTime(m.updated_at)}</span>}
        {m.series && <span>· Issue de la série <Link to={`/meetings/series/${m.series.id}`} className="text-primary hover:underline">{m.series.name}</Link></span>}
      </footer>

      <Dialog open={dialog === "send"} onOpenChange={(o) => !o && setDialog(null)} title="Envoyer le compte-rendu"
        description="Le compte-rendu Word est envoyé par email aux participants (traitement en arrière-plan).">
        <div className="space-y-4">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-primary" checked={includeExternal} onChange={(e) => setIncludeExternal(e.target.checked)} />
            Inclure les adresses des participants externes
          </label>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setDialog(null)}>Annuler</Button>
            <Button disabled={action.isPending} onClick={sendMinutes}><Send />Envoyer</Button>
          </div>
        </div>
      </Dialog>
      <ConfirmDialog open={dialog === "delete"} onOpenChange={(o) => !o && setDialog(null)} destructive pending={deleting}
        title="Supprimer définitivement cette réunion ?" description="Ordre du jour, actions, participations et enregistrements liés seront perdus."
        confirmLabel="Supprimer" onConfirm={() => void remove()} />
    </div>
  );
}
