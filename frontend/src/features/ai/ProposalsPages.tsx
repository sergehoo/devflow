import { ArrowLeft, Bot, ChevronRight, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { formatDateTime } from "@/lib/format";
import { useProjectProposals, useProposalList, useTriggerProposal, type ProposalRow } from "./api";
import { GenerationTracker } from "./GenerationTracker";
import { AIStatusNotice, StatusBadge } from "./shared";

function ProposalRows({ rows, showProject }: { rows: ProposalRow[]; showProject?: boolean }) {
  return (
    <ul className="divide-y rounded-[22px] border border-transparent bg-card shadow-card dark:border-border">
      {rows.map((p) => (
        <li key={p.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={p.status} label={p.status_label} />
              {showProject ? (
                <Link to={`/projects/${p.project.id}`} className="truncate font-medium hover:text-brand">{p.project.name}</Link>
              ) : <span className="font-medium">Proposition n° {p.id}</span>}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {[`${p.items_count} élément(s)`, p.used_provider || null, p.triggered_by ? `par ${p.triggered_by}` : null,
                formatDateTime(p.created_at)].filter(Boolean).join(" · ")}
            </p>
          </div>
          <Button variant="outline" size="sm" asChild>
            <Link to={`/ai-proposals/${p.id}`} aria-label={`Ouvrir la proposition n° ${p.id}`}>Ouvrir<ChevronRight /></Link>
          </Button>
        </li>
      ))}
    </ul>
  );
}

/** Historique des propositions IA d'un projet + déclenchement d'une nouvelle génération. */
export function ProjectProposalsPage() {
  const projectId = Number(useParams().id);
  const { data, isPending, isError, error, refetch } = useProjectProposals(projectId);
  const trigger = useTriggerProposal(projectId);
  const [tracking, setTracking] = useState(false);

  if (isPending) return <PageSkeleton />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;

  const running = data.proposals[0]?.running ?? false;
  const launch = () => trigger.mutate(undefined, {
    onSuccess: () => { setTracking(true); toast.success("Génération lancée : la proposition apparaîtra dès qu'elle sera prête."); },
    onError: (e) => toast.error(e.message),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Propositions IA"
        title={`${data.project.name} — historique IA`}
        description="Roadmap, jalons, sprints, backlog et tâches proposés par l'IA, à valider avant application au projet."
        actions={<>
          <Button variant="outline" asChild><Link to={`/projects/${projectId}`}><ArrowLeft />Retour au projet</Link></Button>
          <Button variant="outline" asChild><Link to={`/projects/${projectId}/copilot`}><Bot />Copilote IA</Link></Button>
          <Button onClick={launch} disabled={!data.can_trigger || trigger.isPending || running}>
            <Wand2 />{trigger.isPending ? "Lancement…" : "Générer une nouvelle proposition"}
          </Button>
        </>}
      />
      {!data.can_trigger && (
        <p role="note" className="rounded-2xl border px-4 py-3 text-sm text-muted-foreground">
          La génération IA est réservée aux responsables du projet, aux chefs de projet et aux propriétaires du workspace.
        </p>
      )}
      <AIStatusNotice ai={data.ai} fallback="IA désactivée : la proposition sera construite par l'assistant heuristique (phases standard)." />
      <GenerationTracker projectId={projectId} active={tracking || running} onDismiss={() => setTracking(false)} />
      {data.proposals.length === 0 ? (
        <EmptyState title="Aucune proposition pour ce projet"
          description="Lancez une génération : l'IA propose la structure complète du projet, que vous validez élément par élément." />
      ) : <ProposalRows rows={data.proposals} />}
    </div>
  );
}

/** Liste globale des propositions IA du workspace (filtre statut / projet). */
export function ProposalListPage() {
  const [search, setSearch] = useSearchParams();
  const params = Object.fromEntries(search);
  const { data, isPending, isError, error, refetch } = useProposalList(params);
  const page = Number(search.get("page") ?? 1);
  const set = (key: string, value: string) => setSearch((s) => {
    if (value) s.set(key, value); else s.delete(key);
    if (key !== "page") s.delete("page");
    return s;
  });

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="IA · structuration"
        title="Propositions IA"
        description={data ? `${data.count} proposition(s) de structuration générées par l'IA` : undefined}
        actions={<>
          <Button variant="outline" asChild><Link to="/imports">Imports documentaires</Link></Button>
          <Button asChild><Link to="/projects/genesis"><Sparkles />Créer un projet avec l'IA</Link></Button>
        </>}
      />
      <div className="flex flex-wrap items-center gap-3">
        <Select aria-label="Statut" className="w-full sm:w-64" value={search.get("status") ?? ""} onChange={(e) => set("status", e.target.value)}>
          <option value="">Tous les statuts</option>
          {data?.status_choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </Select>
        {search.get("project") && <Button variant="link" className="h-auto p-0" onClick={() => set("project", "")}>Tous les projets</Button>}
      </div>
      {isPending ? <Skeleton className="h-72" /> : isError ? <ErrorState message={error.message} onRetry={() => void refetch()} />
        : data.results.length === 0 ? (
          <EmptyState title="Aucune proposition" description="Les propositions apparaissent ici après une génération depuis un projet, Genesis ou un import documentaire." />
        ) : (
          <>
            <ProposalRows rows={data.results} showProject />
            {data.num_pages > 1 && (
              <nav aria-label="Pagination" className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
                <span>Page {data.page} / {data.num_pages}</span>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => set("page", String(page - 1))}>Précédent</Button>
                  <Button variant="outline" size="sm" disabled={page >= data.num_pages} onClick={() => set("page", String(page + 1))}>Suivant</Button>
                </div>
              </nav>
            )}
          </>
        )}
    </div>
  );
}
