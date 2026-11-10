import { Activity, AlertTriangle, ExternalLink, ShieldAlert, Sparkles } from "lucide-react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useAIRiskAnalysis, type EvolutionTab as Data } from "../api";
import { severityTone } from "../format";
import type { FormSpec } from "../formDialog";
import { ActionBar, EmptyLine, Pill, Section, Stat, StatGrid } from "../ui";

/** Analyse de risques IA (ProjectRiskAnalysisView) : signaux + score de risque persistés. */
function RiskAnalysisPanel({ projectId }: { projectId: number }) {
  const analysis = useAIRiskAnalysis(projectId);
  const r = analysis.data;
  return (
    <Section title="Analyse de risques IA" description="Signaux budgétaires, planning et charge ; les alertes sont enregistrées comme insights IA."
      actions={
        <Button size="sm" disabled={analysis.isPending}
          onClick={() => analysis.mutate(undefined, { onSuccess: () => toast.success("Analyse de risques terminée."), onError: (e) => toast.error(e.message) })}>
          <ShieldAlert className={cn(analysis.isPending && "animate-pulse")} />{analysis.isPending ? "Analyse en cours…" : r ? "Relancer l'analyse" : "Lancer l'analyse"}
        </Button>
      }>
      {!r ? <p className="text-sm text-muted-foreground">Lancez l'analyse pour recalculer le score de risque du projet.</p> : (
        <div className="space-y-3">
          <p className="text-sm">Score de risque : <span className="font-serif text-xl font-semibold tabular-nums">{r.risk_score}</span>{r.ai_risk_label && <Pill tone="warning" className="ml-2">{r.ai_risk_label}</Pill>}</p>
          {r.signals.length ? (
            <ul className="space-y-2">
              {r.signals.map((s) => (
                <li key={s.code} className="rounded-xl border bg-muted/30 p-3">
                  <div className="flex items-start justify-between gap-2"><p className="font-semibold">{s.title}</p><Pill tone={severityTone(s.severity)}>{s.severity} · {s.score}</Pill></div>
                  <p className="mt-1 text-sm text-muted-foreground">{s.description}</p>
                </li>
              ))}
            </ul>
          ) : <EmptyLine>Aucun signal de risque détecté.</EmptyLine>}
        </div>
      )}
    </Section>
  );
}

/** Onglet Évolution : activité, pull requests, risques, insights IA. */
export function EvolutionTab({ projectId, data, openForm, canViewFinancials }: {
  projectId: number; data: Data; openForm: (s: FormSpec) => void; canViewFinancials: boolean;
}) {
  const q = { project: String(projectId) };
  const create = (name: string, title: string) => openForm({ name, title, query: q, hidden: ["project"], submitLabel: "Créer" });
  return (
    <div className="space-y-6">
      <ActionBar title="Actions rapides · Évolution" description="Pilotez les signaux d'évolution, incidents et collaboration.">
        <Button size="sm" onClick={() => create("activity-log", "Nouvelle activité")}><Activity />Ajouter une activité</Button>
        <Button size="sm" variant="outline" onClick={() => create("risk", "Nouveau risque")}><AlertTriangle />Nouveau risque</Button>
        <Button size="sm" variant="outline" onClick={() => create("ai-insight", "Nouvel insight IA")}><Sparkles />Nouvel insight IA</Button>
      </ActionBar>

      <StatGrid>
        <Stat label="Activités" value={data.summary.activities_count} />
        <Stat label="Pull requests" value={data.summary.pull_requests_count} />
        <Stat label="Risques" value={data.summary.risks_count} />
        <Stat label="Insights actifs" value={data.summary.insights_count} />
      </StatGrid>

      {/* Vue Django réservée aux droits financiers : bouton masqué sinon (Django reste l'autorité). */}
      {canViewFinancials && <RiskAnalysisPanel projectId={projectId} />}

      <Section title="Historique d'activité" description="Traçabilité et événements récents (30 derniers)">
        {data.activities.length ? (
          <ol className="space-y-4">
            {data.activities.map((log) => (
              <li key={log.id} className="flex gap-3 border-b pb-3 last:border-b-0">
                <span aria-hidden="true" className="mt-1.5 size-2.5 shrink-0 rounded-full bg-primary ring-4 ring-primary/15" />
                <div className="min-w-0">
                  <Link to={`/m/activity-log/${log.id}`} className="font-medium hover:text-brand">{log.title}</Link>
                  {log.description && <p className="text-sm text-muted-foreground">{log.description}</p>}
                  <p className="text-xs text-muted-foreground">{formatDateTime(log.created_at)}{log.actor ? ` · ${log.actor}` : ""}</p>
                </div>
              </li>
            ))}
          </ol>
        ) : <EmptyLine>Aucune activité disponible.</EmptyLine>}
      </Section>

      <div className="grid gap-6 xl:grid-cols-2">
        <Section title="Pull requests" description="Suivi de la collaboration technique" count={data.pull_requests.length}>
          {data.pull_requests.length ? (
            <ul className="space-y-2">
              {data.pull_requests.map((pr) => (
                <li key={pr.id} className="flex items-start justify-between gap-3 rounded-xl border bg-muted/30 p-3">
                  <div className="min-w-0">
                    <Link to={`/m/pull-request/${pr.id}`} className="font-semibold hover:text-brand">{pr.title}</Link>
                    <p className="truncate text-sm text-muted-foreground">{pr.repository || "Dépôt"}{pr.branch_name ? ` · ${pr.branch_name}` : ""}</p>
                    {pr.author && <p className="text-xs text-muted-foreground">Auteur : {pr.author}</p>}
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    <Pill>{pr.status_label || "—"}</Pill>
                    {pr.url && /^https?:\/\//.test(pr.url) && (
                      <a href={pr.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-brand hover:underline"><ExternalLink className="size-3" />Ouvrir</a>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          ) : <EmptyLine>Aucune pull request.</EmptyLine>}
        </Section>

        <Section title="Risques" description="Menaces identifiées sur la livraison" count={data.risks.length}>
          {data.risks.length ? (
            <ul className="space-y-2">
              {data.risks.map((r) => (
                <li key={r.id} className="rounded-xl border bg-muted/30 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <Link to={`/m/risk/${r.id}`} className="font-semibold hover:text-brand">{r.title}</Link>
                    <Pill tone={severityTone(r.severity)}>{r.severity_label || "—"}</Pill>
                  </div>
                  <p className="text-sm text-muted-foreground">{r.status_label || "—"}{r.owner ? ` · Responsable : ${r.owner}` : ""}</p>
                </li>
              ))}
            </ul>
          ) : <EmptyLine>Aucun risque enregistré.</EmptyLine>}
        </Section>
      </div>

      <Section title="Insights IA" description="Alertes, recommandations et signaux détectés" count={data.insights.length}>
        {data.insights.length ? (
          <ul className="space-y-2">
            {data.insights.map((i) => (
              <li key={i.id} className={cn("flex flex-col gap-2 rounded-xl border bg-muted/30 p-3 md:flex-row md:items-start md:justify-between", i.is_dismissed && "opacity-60")}>
                <div className="min-w-0">
                  <Link to={`/m/ai-insight/${i.id}`} className="font-semibold hover:text-brand">{i.title}</Link>
                  <p className="text-sm text-muted-foreground">{i.summary}</p>
                  {i.task_id ? <p className="text-xs text-muted-foreground">Tâche liée : <Link to={`/tasks/${i.task_id}`} className="hover:text-brand">{i.task}</Link></p>
                    : i.sprint ? <p className="text-xs text-muted-foreground">Sprint lié : {i.sprint}</p> : null}
                </div>
                <div className="flex shrink-0 flex-wrap gap-1.5">
                  <Pill>{i.insight_type_label}</Pill>
                  <Pill tone={severityTone(i.severity)}>{i.severity_label}</Pill>
                  {i.is_dismissed && <Pill>Ignoré</Pill>}
                </div>
              </li>
            ))}
          </ul>
        ) : <EmptyLine>Aucun insight IA.</EmptyLine>}
      </Section>
    </div>
  );
}
