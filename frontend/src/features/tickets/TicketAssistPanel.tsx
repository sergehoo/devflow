import { Copy, FileText, MessageSquareText, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { WidgetHeader } from "@/features/dashboard/widgets";
import { formatDateTime } from "@/lib/format";
import {
  useTicketAction, useTicketAssist, useTicketDuplicates,
  type ReplySuggestion, type SummarySuggestion, type TicketDetail, type TriageSuggestion,
} from "./api";

function Origin({ source, provider }: { source: "ai" | "rules"; provider: string }) {
  return (
    <span className="text-[11px] text-muted-foreground">
      {source === "ai" ? `Proposé par l'IA (${provider})` : "Règles DevFlow (IA indisponible ou non configurée)"}
    </span>
  );
}

/**
 * Assistant IA de la fiche ticket : qualification, résumé, proposition de réponse et doublons.
 * Tout est une suggestion : l'agent applique (action « qualifier » existante) ou reprend le texte
 * dans sa réponse, qu'il relit et envoie lui-même. Rien n'est envoyé automatiquement au client.
 */
export function TicketAssistPanel({ t, onUseReply }: { t: TicketDetail; onUseReply: (text: string) => void }) {
  const triage = useTicketAssist<TriageSuggestion>(t.id, "triage");
  const summary = useTicketAssist<SummarySuggestion>(t.id, "summary");
  const reply = useTicketAssist<ReplySuggestion>(t.id, "reply");
  const [lookDuplicates, setLookDuplicates] = useState(false);
  const duplicates = useTicketDuplicates(t.id, lookDuplicates);
  const qualify = useTicketAction(t.id);
  const fail = (e: Error) => toast.error(e.message);

  const suggestion = triage.data;
  const changes = suggestion ? (["category", "severity", "priority"] as const).filter((f) => suggestion[f].changed) : [];
  const apply = () => suggestion && qualify.mutate(
    { action: "qualify", body: Object.fromEntries(changes.map((f) => [f, suggestion[f].value])) },
    { onSuccess: () => { toast.success("Qualification appliquée."); triage.reset(); }, onError: fail },
  );

  return (
    <Card className="p-5 sm:p-6" aria-label="Assistant IA">
      <WidgetHeader title="Assistant IA" meta="Suggestions à valider" />
      <p className="mt-1 text-xs text-muted-foreground">Rien n'est appliqué ni envoyé au client sans votre validation.</p>

      <div className="mt-4 grid gap-2">
        <Button variant="outline" size="sm" disabled={triage.isPending} onClick={() => triage.mutate(undefined, { onError: fail })}>
          <Wand2 />{triage.isPending ? "Analyse…" : "Suggérer la qualification"}
        </Button>
        <Button variant="outline" size="sm" disabled={summary.isPending} onClick={() => summary.mutate(undefined, { onError: fail })}>
          <FileText />{summary.isPending ? "Résumé…" : "Résumer le ticket"}
        </Button>
        <Button variant="outline" size="sm" disabled={reply.isPending} onClick={() => reply.mutate(undefined, { onError: fail })}>
          <MessageSquareText />{reply.isPending ? "Rédaction…" : "Proposer une réponse"}
        </Button>
        <Button variant="outline" size="sm" onClick={() => setLookDuplicates(true)} disabled={duplicates.isFetching}>
          <Copy />Rechercher des doublons
        </Button>
      </div>

      {suggestion && (
        <section aria-label="Qualification suggérée" className="mt-4 rounded-2xl bg-muted p-3 text-sm">
          <p className="font-semibold">Qualification suggérée</p>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            {([["Catégorie", suggestion.category], ["Gravité", suggestion.severity], ["Priorité", suggestion.priority]] as const).map(([label, f]) => (
              <div key={label} className="contents">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className={f.changed ? "font-semibold text-brand" : ""}>{f.label}{f.changed ? "" : " (inchangée)"}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-2 text-xs text-muted-foreground">{suggestion.rationale}</p>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <Origin source={suggestion.source} provider={suggestion.provider} />
            {changes.length > 0 && (t.rights.manage
              ? <Button size="sm" disabled={qualify.isPending} onClick={apply}><Sparkles />Appliquer</Button>
              : <span className="text-xs text-muted-foreground">À valider par un gestionnaire.</span>)}
          </div>
        </section>
      )}

      {summary.data && (
        <section aria-label="Résumé du ticket" className="mt-4 rounded-2xl bg-muted p-3 text-sm">
          <p className="font-semibold">Résumé</p>
          <p className="mt-1 whitespace-pre-wrap">{summary.data.summary}</p>
          <div className="mt-2"><Origin source={summary.data.source} provider={summary.data.provider} /></div>
        </section>
      )}

      {reply.data && (
        <section aria-label="Proposition de réponse" className="mt-4 rounded-2xl bg-muted p-3 text-sm">
          <p className="font-semibold">Proposition de réponse</p>
          <p className="mt-1 whitespace-pre-wrap">{reply.data.reply}</p>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <Origin source={reply.data.source} provider={reply.data.provider} />
            {t.rights.reply && (
              <Button size="sm" variant="outline" onClick={() => { onUseReply(reply.data.reply); toast.success("Proposition reprise dans la réponse : relisez-la avant d'envoyer."); }}>
                Reprendre dans la réponse
              </Button>
            )}
          </div>
        </section>
      )}

      {lookDuplicates && duplicates.data && (
        <section aria-label="Doublons potentiels" className="mt-4 text-sm">
          <p className="font-semibold">Doublons potentiels</p>
          {duplicates.data.results.length === 0 ? <p className="mt-1 text-muted-foreground">Aucun ticket proche sur les 90 derniers jours.</p> : (
            <ul className="mt-2 space-y-2">
              {duplicates.data.results.map((d) => (
                <li key={d.id} className="rounded-2xl bg-muted p-3">
                  <Link to={`/tickets/${d.id}`} className="font-medium hover:text-brand">{d.reference} · {d.title}</Link>
                  <span className="block text-xs text-muted-foreground">
                    {d.status_label} · {d.application} · {formatDateTime(d.created_at)} · similarité {Math.round(d.score * 100)} %
                  </span>
                  {d.reasons.length > 0 && <span className="block text-xs text-muted-foreground">{d.reasons.join(" · ")}</span>}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </Card>
  );
}
