import {
  ArrowLeft, Check, CheckCheck, ChevronRight, ExternalLink, Lightbulb, Loader2, Pencil, RefreshCw, Rocket, TriangleAlert, Users, X,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Select } from "@/components/ui/input";
import { Badge } from "@/components/ui/misc";
import { formatDate, formatDateTime, formatHours } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  useGenerationStatus, useItemAction, useProposal, useProposalAction, type ProposalDetail, type ProposalItem,
} from "./api";
import { ITEM_STATUSES, ITEM_VISIBLE_FIELDS, KIND_TABS } from "./constants";
import { ItemEditDialog } from "./ItemEditDialog";
import { ProgressBar, Stat, StatusBadge } from "./shared";

type ItemHandlers = {
  editable: boolean;
  busyId: number | null;
  onAction: (item: ProposalItem, action: "validate" | "reject") => void;
  onEdit: (item: ProposalItem) => void;
};

function Chip({ children }: { children: ReactNode }) {
  return <span className="inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground">{children}</span>;
}

function period(i: ProposalItem) {
  if (!i.start_date && !i.end_date) return null;
  return `${formatDate(i.start_date)} → ${formatDate(i.end_date)}`;
}

function ItemMeta({ item }: { item: ProposalItem }) {
  const chips: ReactNode[] = [];
  if (item.kind === "TASK") {
    if (item.recommended_profile) chips.push(`Profil ${item.recommended_profile}`);
    chips.push(item.recommended_assignee ? item.recommended_assignee.name : "Non assigné");
    chips.push(formatHours(item.estimate_hours));
    if (item.priority) chips.push(`Priorité ${item.priority}`);
    if (item.complexity) chips.push(`Complexité ${item.complexity}`);
    if (item.sprint_ref) chips.push(`Sprint ${item.sprint_ref}`);
    if (item.milestone_ref) chips.push(`Jalon ${item.milestone_ref}`);
    if (item.depends_on_refs.length) chips.push(`Dépend de ${item.depends_on_refs.join(", ")}`);
  } else if (item.kind === "SPRINT") {
    const p = period(item);
    if (p) chips.push(p);
    if (item.velocity_target) chips.push(`Vélocité ${item.velocity_target}`);
  } else if (item.kind === "MILESTONE") {
    chips.push(`Échéance ${formatDate(item.end_date)}`);
  } else if (item.kind === "ROADMAP_ITEM") {
    const p = period(item);
    if (p) chips.push(p);
  } else if (item.kind === "ASSIGNMENT") {
    if (item.recommended_assignee) chips.push(item.recommended_assignee.name);
  } else if (item.kind === "BACKLOG" && item.priority) {
    chips.push(`Priorité ${item.priority}`);
  }
  if (!chips.length && !item.acceptance_criteria.length) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {chips.map((c, i) => <Chip key={i}>{c}</Chip>)}
      {item.acceptance_criteria.slice(0, 2).map((c) => <Chip key={c}>✓ {c.length > 60 ? `${c.slice(0, 60)}…` : c}</Chip>)}
      {item.acceptance_criteria.length > 2 && <Chip>+{item.acceptance_criteria.length - 2} critère(s)</Chip>}
    </div>
  );
}

function ItemRow({ item, h, compact, extra }: { item: ProposalItem; h: ItemHandlers; compact?: boolean; extra?: ReactNode }) {
  const title = item.title || item.local_ref || "Élément";
  const canAct = h.editable && item.item_status !== "APPLIED";
  const busy = h.busyId === item.id;
  return (
    <li className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-start">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={item.item_status} label={item.item_status_label} />
          {item.local_ref && <span className="font-mono text-xs text-muted-foreground">{item.local_ref}</span>}
          <span className="break-words font-medium">{item.title || "Sans titre"}</span>
        </div>
        {!compact && item.description && <p className="mt-1 line-clamp-2 whitespace-pre-line break-words text-sm text-muted-foreground">{item.description}</p>}
        <ItemMeta item={item} />
        {extra && <p className="mt-1 text-xs text-muted-foreground">{extra}</p>}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-1">
        {item.applied?.link && (
          <Button size="sm" variant="outline" asChild>
            <Link to={item.applied.link} aria-label={`Ouvrir l'élément créé : ${title}`}>Ouvrir<ExternalLink /></Link>
          </Button>
        )}
        {canAct && (
          <>
            <Button size="icon" variant="ghost" aria-label={`Valider ${title}`} disabled={busy || item.item_status === "VALIDATED"}
              onClick={() => h.onAction(item, "validate")}><Check className="text-success" /></Button>
            {ITEM_VISIBLE_FIELDS[item.kind] && (
              <Button size="icon" variant="ghost" aria-label={`Modifier ${title}`} onClick={() => h.onEdit(item)}><Pencil /></Button>
            )}
            <Button size="icon" variant="ghost" aria-label={`Rejeter ${title}`} disabled={busy || item.item_status === "REJECTED"}
              onClick={() => h.onAction(item, "reject")}><X className="text-destructive" /></Button>
          </>
        )}
      </div>
    </li>
  );
}

function ItemList({ items, h, compact, empty }: { items: ProposalItem[]; h: ItemHandlers; compact?: boolean; empty: string }) {
  if (!items.length) return <p className="px-4 py-8 text-center text-sm text-muted-foreground">{empty}</p>;
  return <ul className="divide-y">{items.map((i) => <ItemRow key={i.id} item={i} h={h} compact={compact} />)}</ul>;
}

/** Arborescence : phases → jalons → sprints (avec leurs tâches) → tâches non planifiées → backlog. */
function Tree({ items, h }: { items: ProposalItem[]; h: ItemHandlers }) {
  const of = (kind: string) => items.filter((i) => i.kind === kind);
  const tasks = of("TASK");
  const sprints = of("SPRINT");
  const milestones = of("MILESTONE");
  const sprintRefs = new Set(sprints.map((s) => s.local_ref).filter(Boolean));
  const orphans = tasks.filter((t) => !t.sprint_ref || !sprintRefs.has(t.sprint_ref));
  const hours = (list: ProposalItem[]) => list.reduce((sum, t) => sum + t.estimate_hours, 0);
  /** Section repliable (ouverte d'office si elle est courte). */
  const section = (title: string, count: number, children: ReactNode, open = count <= 6) => (
    <details open={open} className="group/section">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        <ChevronRight className="size-4 transition-transform group-open/section:rotate-90" aria-hidden="true" />
        {title}<span className="font-normal normal-case">({count})</span>
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
  if (!items.length) return <p className="py-8 text-center text-sm text-muted-foreground">Aucun élément à afficher.</p>;
  return (
    <div className="space-y-6">
      {of("ROADMAP_ITEM").length > 0 && section("Phases de la roadmap", of("ROADMAP_ITEM").length,
        <div className="rounded-2xl border"><ItemList items={of("ROADMAP_ITEM")} h={h} compact empty="" /></div>)}
      {milestones.length > 0 && section("Jalons", milestones.length, (
        <ul className="divide-y rounded-2xl border">
          {milestones.map((m) => {
            const linked = tasks.filter((t) => m.local_ref && t.milestone_ref === m.local_ref).length;
            return <ItemRow key={m.id} item={m} h={h} compact extra={linked > 0 ? `${linked} tâche(s) rattachée(s)` : undefined} />;
          })}
        </ul>
      ))}
      {(sprints.length > 0 || orphans.length > 0) && section("Sprints et tâches", tasks.length, (
        <div className="space-y-3">
          {sprints.map((s, idx) => {
            const own = tasks.filter((t) => t.sprint_ref && t.sprint_ref === s.local_ref);
            return (
              <details key={s.id} open={idx === 0} className="group/sprint rounded-2xl border">
                <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-4 py-3">
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground transition-transform group-open/sprint:rotate-90" aria-hidden="true" />
                  <span className="font-semibold">{s.title || s.local_ref}</span>
                  <StatusBadge status={s.item_status} label={s.item_status_label} />
                  <span className="text-xs text-muted-foreground">
                    {[period(s), `${own.length} tâche(s)`, formatHours(hours(own))].filter(Boolean).join(" · ")}
                  </span>
                </summary>
                <ul className="divide-y border-t bg-muted/20">
                  <ItemRow item={s} h={h} compact />
                  {own.map((t) => <ItemRow key={t.id} item={t} h={h} compact />)}
                </ul>
              </details>
            );
          })}
          {orphans.length > 0 && (
            <details open={!sprints.length} className="group/orphans rounded-2xl border">
              <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-4 py-3 font-semibold">
                <ChevronRight className="size-4 shrink-0 text-muted-foreground transition-transform group-open/orphans:rotate-90" aria-hidden="true" />
                Tâches hors sprint <span className="text-xs font-normal text-muted-foreground">· {orphans.length} tâche(s) · {formatHours(hours(orphans))}</span>
              </summary>
              <ul className="divide-y border-t bg-muted/20">{orphans.map((t) => <ItemRow key={t.id} item={t} h={h} compact />)}</ul>
            </details>
          )}
        </div>
      ), true)}
      {of("BACKLOG").length > 0 && section("Backlog", of("BACKLOG").length,
        <div className="rounded-2xl border"><ItemList items={of("BACKLOG")} h={h} compact empty="" /></div>)}
    </div>
  );
}

function AppliedSummary({ p }: { p: ProposalDetail }) {
  const created = KIND_TABS.filter((k) => p.counts.applied_by_kind[k.kind]);
  if (!created.length) return null;
  return (
    <Card className="border-success/30">
      <CardHeader><CardTitle>Éléments créés dans le projet</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          {created.map((k) => `${p.counts.applied_by_kind[k.kind]} ${k.plural}`).join(", ")}
          {p.applied_at ? ` — appliquée le ${formatDateTime(p.applied_at)}` : ""}. Chaque élément créé est accessible via « Ouvrir ».
        </p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" asChild><Link to={`/projects/${p.project.id}`}>Ouvrir le projet</Link></Button>
          <Button size="sm" variant="outline" asChild><Link to={`/tasks?project=${p.project.id}`}>Tâches du projet</Link></Button>
          <Button size="sm" variant="outline" asChild><Link to={`/m/sprint?project=${p.project.id}`}>Sprints du projet</Link></Button>
        </div>
      </CardContent>
    </Card>
  );
}

const TABS = [{ key: "tree", label: "Arborescence" }, ...KIND_TABS.map((k) => ({ key: k.kind, label: k.tab })), { key: "logs", label: "Historique" }];

/** Aperçu complet d'une proposition IA : revue, édition, validation / rejet, application, régénération. */
export function ProposalDetailPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const tab = search.get("tab") ?? "tree";
  const { data: p, isPending, isError, error, refetch } = useProposal(id);
  const generation = useGenerationStatus(p?.project.id, !!p?.running);
  const action = useProposalAction(id);
  const itemAction = useItemAction(id);
  const [confirm, setConfirm] = useState<"apply" | "reject" | "regenerate" | null>(null);
  const [useAi, setUseAi] = useState(true);
  const [editing, setEditing] = useState<ProposalItem | null>(null);
  const [statusFilter, setStatusFilter] = useState("");

  const refs = useMemo(() => {
    const opts = (kind: string) => (p?.items ?? []).filter((i) => i.kind === kind && i.local_ref)
      .map((i) => ({ value: i.local_ref, label: `${i.local_ref} — ${i.title}` }));
    return { sprint: opts("SPRINT"), milestone: opts("MILESTONE") };
  }, [p?.items]);

  if (isPending) return <PageSkeleton />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;

  const h: ItemHandlers = {
    editable: p.editable,
    busyId: itemAction.isPending ? (itemAction.variables?.itemId ?? null) : null,
    onAction: (item, kind) => itemAction.mutate({ itemId: item.id, action: kind }, {
      onSuccess: () => toast.success(kind === "validate" ? "Élément validé." : "Élément rejeté."),
      onError: (e) => toast.error(e.message),
    }),
    onEdit: setEditing,
  };

  const run = (kind: "validate-all" | "apply" | "reject" | "regenerate") => action.mutate(
    { action: kind, data: kind === "regenerate" && useAi ? { use_ai: "on" } : undefined },
    {
      onSuccess: (r) => {
        if (kind === "apply") {
          const parts = KIND_TABS.filter((k) => r.applied_by_kind?.[k.kind]).map((k) => `${r.applied_by_kind?.[k.kind]} ${k.plural}`);
          toast.success(parts.length ? `Proposition appliquée : ${parts.join(", ")}.` : "Proposition appliquée.");
        } else (r.messages?.length ? r.messages : ["Action effectuée."]).forEach((m) => toast.success(m));
        if (kind === "regenerate" && r.id) navigate(`/ai-proposals/${r.id}`);
      },
      onError: (e) => toast.error(e.message),
      onSettled: () => setConfirm(null),
    },
  );

  const filtered = statusFilter ? p.items.filter((i) => i.item_status === statusFilter) : p.items;
  const applicable = p.items.filter((i) => i.item_status === "VALIDATED" || i.item_status === "EDITED").length;
  const taskCount = p.counts.by_kind.TASK ?? 0;
  const totalHours = p.items.filter((i) => i.kind === "TASK").reduce((sum, i) => sum + i.estimate_hours, 0);
  const maxLoad = Math.max(1, ...p.coherence.load_rows.map((r) => r.hours));
  const gen = generation.data && generation.data.proposal_id === p.id ? generation.data : null;
  const setTab = (key: string) => setSearch((s) => { s.set("tab", key); return s; }, { replace: true });

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Proposition de structure IA"
        title={p.project.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge status={p.status} label={p.status_label} />
            {p.used_provider && <Badge>{p.used_provider}</Badge>}
            {p.tokens_used > 0 && <span className="text-xs">{p.tokens_used} jetons</span>}
            <span className="text-xs">Générée le {formatDateTime(p.created_at)}{p.triggered_by ? ` par ${p.triggered_by}` : ""}</span>
          </span>
        }
        actions={<>
          <Button variant="outline" asChild><Link to={`/projects/${p.project.id}/ai-proposals`}><ArrowLeft />Historique</Link></Button>
          <Button variant="outline" disabled={!p.can_validate_all || action.isPending} onClick={() => run("validate-all")}><CheckCheck />Tout valider</Button>
          <Button disabled={!p.can_apply || action.isPending} onClick={() => setConfirm("apply")}><Rocket />Appliquer au projet</Button>
          <Button variant="outline" disabled={!p.can_regenerate || p.running || action.isPending} onClick={() => setConfirm("regenerate")}><RefreshCw />Régénérer</Button>
          <Button variant="ghost" className="text-destructive" disabled={!p.can_reject || action.isPending} onClick={() => setConfirm("reject")}><X />Rejeter</Button>
        </>}
      />

      {p.running && (
        <section aria-live="polite" className="space-y-2 rounded-[22px] border border-transparent bg-card shadow-card dark:border-border p-4">
          <p className="flex items-center gap-2 text-sm font-semibold"><Loader2 className="size-4 animate-spin text-brand" aria-hidden="true" />Génération en cours</p>
          <p className="text-xs text-muted-foreground">{gen?.step_label || "L'IA construit la structure du projet."} La page se met à jour automatiquement.</p>
          <ProgressBar value={gen?.progress ?? 5} label="Progression de la génération" />
        </section>
      )}
      {p.status === "FAILED" && (
        <section role="alert" className="rounded-2xl border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <p className="flex items-center gap-2 font-semibold text-destructive"><TriangleAlert className="size-4" aria-hidden="true" />Échec de la génération</p>
          {p.error_message && <p className="mt-1 whitespace-pre-line text-muted-foreground">{p.error_message}</p>}
          <p className="mt-2 text-muted-foreground">Vous pouvez relancer avec « Régénérer ».</p>
        </section>
      )}
      {p.status !== "FAILED" && p.used_provider === "heuristic" && p.error_message && (
        <p role="status" className="rounded-2xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm">
          L'IA n'a pas renvoyé de résultat exploitable : proposition générée par l'assistant de secours.
        </p>
      )}
      {p.status === "APPLIED" && <AppliedSummary p={p} />}
      {!p.can_edit && p.status !== "APPLIED" && p.status !== "REJECTED" && (
        <p role="note" className="rounded-2xl border px-4 py-3 text-sm text-muted-foreground">
          Consultation seule : la validation, la modification et l'application de la proposition sont réservées aux responsables du projet,
          aux chefs de projet et aux propriétaires du workspace.
        </p>
      )}
      {p.can_apply && applicable === 0 && p.items.length > 0 && (
        <p role="note" className="rounded-2xl border px-4 py-3 text-sm text-muted-foreground">
          Seuls les éléments validés ou modifiés sont appliqués : validez des éléments (ou « Tout valider ») avant d'appliquer.
        </p>
      )}

      <section aria-label="Cohérence" className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Stat label="Tâches proposées" value={taskCount} hint={`${p.counts.total} élément(s) au total · ${p.counts.validated} validé(s)`} />
        <Stat label="Charge totale" value={formatHours(totalHours)} hint={`dont ${formatHours(p.coherence.total_hours)} affectées`} accent="text-warning" />
        <Stat label="Tâches non assignées" value={p.coherence.unassigned_tasks} hint="à attribuer manuellement"
          accent={p.coherence.unassigned_tasks ? "text-destructive" : "text-success"} />
        <Stat label="Dépendances cassées" value={p.coherence.broken_dependencies.length} hint="références manquantes"
          accent={p.coherence.broken_dependencies.length ? "text-destructive" : "text-success"} />
      </section>

      {(p.summary || p.risks_summary || p.recommendations.length > 0) && (
        <div className="grid gap-4 lg:grid-cols-2">
          {p.summary && (
            <Card className="lg:col-span-2"><CardHeader><CardTitle>Synthèse</CardTitle></CardHeader>
              <CardContent><p className="whitespace-pre-line text-sm text-muted-foreground">{p.summary}</p></CardContent></Card>
          )}
          {p.risks_summary && (
            <Card><CardHeader><CardTitle className="flex items-center gap-2"><TriangleAlert className="size-4 text-warning" aria-hidden="true" />Risques détectés</CardTitle></CardHeader>
              <CardContent><p className="whitespace-pre-line text-sm text-muted-foreground">{p.risks_summary}</p></CardContent></Card>
          )}
          {p.recommendations.length > 0 && (
            <Card><CardHeader><CardTitle className="flex items-center gap-2"><Lightbulb className="size-4 text-brand" aria-hidden="true" />Recommandations IA</CardTitle></CardHeader>
              <CardContent><ul className="space-y-2 text-sm text-muted-foreground">
                {p.recommendations.map((r) => <li key={r} className="flex gap-2"><Check className="mt-0.5 size-4 shrink-0 text-success" aria-hidden="true" /><span>{r}</span></li>)}
              </ul></CardContent></Card>
          )}
        </div>
      )}

      {(p.coherence.load_rows.length > 0 || p.coherence.broken_dependencies.length > 0) && (
        <div className="grid gap-4 lg:grid-cols-2">
          {p.coherence.load_rows.length > 0 && (
            <Card><CardHeader><CardTitle className="flex items-center gap-2"><Users className="size-4 text-info" aria-hidden="true" />Charge par membre</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {p.coherence.load_rows.map((r) => (
                  <div key={r.user_id}>
                    <div className="mb-1 flex justify-between gap-2 text-xs"><span className="truncate">{r.label}</span><span className="tabular-nums text-muted-foreground">{formatHours(r.hours)}</span></div>
                    <ProgressBar value={(r.hours / maxLoad) * 100} label={`Charge de ${r.label}`} />
                  </div>
                ))}
              </CardContent></Card>
          )}
          {p.coherence.broken_dependencies.length > 0 && (
            <Card><CardHeader><CardTitle>Dépendances cassées</CardTitle></CardHeader>
              <CardContent><ul className="space-y-1 text-sm">
                {p.coherence.broken_dependencies.map((d) => (
                  <li key={`${d.task}-${d.missing}`}><span className="font-mono">{d.task}</span> dépend de <span className="font-mono text-destructive">{d.missing}</span> (introuvable)</li>
                ))}
              </ul></CardContent></Card>
          )}
        </div>
      )}

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b p-3">
          <div role="tablist" aria-label="Éléments de la proposition" className="flex max-w-full gap-1 overflow-x-auto">
            {TABS.map((t) => {
              const count = t.key === "tree" ? null : t.key === "logs" ? p.logs.length : (p.counts.by_kind[t.key] ?? 0);
              return (
                <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
                  className={cn("shrink-0 rounded-lg px-3 py-1.5 text-sm font-semibold transition-colors",
                    tab === t.key ? "bg-primary/10 text-brand" : "text-muted-foreground hover:bg-hover hover:text-foreground")}>
                  {t.label}{count !== null && <span className="ml-1 text-xs font-normal">({count})</span>}
                </button>
              );
            })}
          </div>
          {tab !== "logs" && (
            <Select aria-label="Filtrer par statut" className="h-9 w-full sm:w-48" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">Tous les statuts</option>
              {ITEM_STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </Select>
          )}
        </div>
        <div role="tabpanel" className={tab === "tree" ? "p-3 sm:p-4" : undefined}>
          {tab === "tree" ? <Tree items={filtered} h={h} />
            : tab === "logs" ? (
              p.logs.length ? (
                <ul className="divide-y">
                  {p.logs.map((log) => (
                    <li key={log.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
                      <span className="text-xs tabular-nums text-muted-foreground">{formatDateTime(log.created_at)}</span>
                      <Badge>{log.action_label}</Badge>
                      <span className="min-w-0 break-words">{log.message}</span>
                      {log.actor && <span className="text-xs text-muted-foreground">— {log.actor}</span>}
                    </li>
                  ))}
                </ul>
              ) : <EmptyState title="Aucune action enregistrée" />
            ) : <ItemList items={filtered.filter((i) => i.kind === tab)} h={h} empty="Aucun élément de ce type." />}
        </div>
      </Card>

      {editing && <ItemEditDialog proposalId={p.id} item={editing} refs={refs} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={confirm === "apply"} onOpenChange={(o) => !o && setConfirm(null)} pending={action.isPending}
        title="Appliquer cette proposition au projet ?" confirmLabel="Appliquer"
        description={`Les ${applicable} élément(s) validé(s) ou modifié(s) seront créés dans le projet (roadmap, jalons, sprints, backlog, tâches, dépendances, affectations). Les éléments rejetés ou non validés sont ignorés.`}
        onConfirm={() => run("apply")} />
      <ConfirmDialog open={confirm === "reject"} onOpenChange={(o) => !o && setConfirm(null)} pending={action.isPending} destructive
        title="Rejeter toute la proposition ?" description="Tous les éléments seront rejetés. La proposition reste consultable dans l'historique."
        confirmLabel="Rejeter" onConfirm={() => run("reject")} />
      <Dialog open={confirm === "regenerate"} onOpenChange={(o) => !o && setConfirm(null)} title="Régénérer une proposition"
        description={`Une nouvelle proposition sera créée pour ${p.project.name}. La précédente reste disponible dans l'historique.`}>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="size-4 accent-primary" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />
          Utiliser l'IA (sinon génération heuristique)
        </label>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="outline" onClick={() => setConfirm(null)}>Annuler</Button>
          <Button disabled={action.isPending} onClick={() => run("regenerate")}><RefreshCw />{action.isPending ? "Génération…" : "Régénérer"}</Button>
        </div>
      </Dialog>
    </div>
  );
}
