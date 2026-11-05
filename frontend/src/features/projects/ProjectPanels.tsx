import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Calculator, FileDown, Plus, RefreshCw, Wand2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { LegacyForm } from "@/components/forms/LegacyForm";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Badge, Skeleton } from "@/components/ui/misc";
import { formatDate, formatMoney } from "@/lib/format";
import { legacyUrl } from "@/lib/utils";
import { ApiError, api, actionBody } from "@/services/api";

type Money = string;
interface BudgetPanel {
  budget_id: number | null;
  overview: Record<"approved_budget" | "estimated_cost" | "actual_cost" | "committed_cost" | "raf_cost" | "forecast_final_cost"
    | "planned_revenue" | "invoiced_revenue" | "received_revenue" | "gross_margin" | "forecast_margin" | "real_margin", Money>
    & { profit_margin_percent: number; forecast_consumption_percent: number; currency: string };
}

const BUDGET_ROWS: [keyof BudgetPanel["overview"], string][] = [
  ["approved_budget", "Budget validé"], ["estimated_cost", "Coût estimé"], ["actual_cost", "Coût réel"],
  ["committed_cost", "Engagé"], ["raf_cost", "Reste à faire"], ["forecast_final_cost", "Coût final prévu"],
  ["planned_revenue", "Revenu prévu"], ["invoiced_revenue", "Facturé"], ["received_revenue", "Encaissé"],
  ["gross_margin", "Marge brute"], ["forecast_margin", "Marge prévisionnelle"], ["real_margin", "Marge réelle"],
];

type FormDialog = { name: string; title: string; id?: number } | null;

/** Onglet budget : synthèse ProjectBudgetService + formulaires et actions des vues budget Django. */
export function BudgetPanel({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<FormDialog>(null);
  const key = ["projects", projectId, "budget-panel"];
  const panel = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => api<BudgetPanel>(`projects/${projectId}/budget-panel/`, { signal }),
    retry: (n, e) => !(e instanceof ApiError && e.status === 403) && n < 2,
  });
  const action = useMutation({
    mutationFn: (name: string) => api<{ messages?: string[] }>(`actions/${name}/${projectId}/`, { method: "POST", body: actionBody() }),
    onSuccess: (r) => { (r.messages ?? ["Budget mis à jour."]).forEach((m) => toast.success(m)); void qc.invalidateQueries({ queryKey: ["projects", projectId] }); },
    onError: (e) => toast.error(e.message),
  });
  if (panel.isError && panel.error instanceof ApiError && panel.error.status === 403) return null; // pas de droit financier
  const o = panel.data?.overview;

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle>Budget</CardTitle>
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setForm(panel.data?.budget_id ? { name: "project-budget", title: "Modifier le budget", id: panel.data.budget_id } : { name: "project-budget", title: "Définir le budget" })}>
            <Plus />{panel.data?.budget_id ? "Modifier le budget" : "Définir le budget"}</Button>
          <Button size="sm" variant="outline" onClick={() => setForm({ name: "estimate-line", title: "Ligne d'estimation" })}><Plus />Estimation</Button>
          <Button size="sm" variant="outline" onClick={() => setForm({ name: "project-revenue", title: "Revenu" })}><Plus />Revenu</Button>
          <Button size="sm" variant="outline" asChild><Link to={`/m/project-expense/new?project=${projectId}`}><Plus />Dépense</Link></Button>
          <Button size="sm" variant="ghost" disabled={action.isPending} onClick={() => action.mutate("project-generate-estimates")}><Wand2 />Estimer depuis les tâches</Button>
          <Button size="sm" variant="ghost" disabled={action.isPending} onClick={() => action.mutate("project-recalculate-budget")}><Calculator />Recalculer</Button>
          <Button size="sm" variant="ghost" disabled={action.isPending} onClick={() => action.mutate("project-refresh-financials")}><RefreshCw />Rafraîchir</Button>
          <Button size="sm" variant="ghost" asChild><a href={legacyUrl(`/projects/${projectId}/budget/export-excel/`)}><FileDown />Excel</a></Button>
        </div>
      </CardHeader>
      <CardContent>
        {panel.isPending ? <Skeleton className="h-32" /> : !o ? <p className="text-sm text-muted-foreground">Budget indisponible.</p> : (
          <>
            <dl className="grid gap-3 sm:grid-cols-3 xl:grid-cols-4">
              {BUDGET_ROWS.map(([k, label]) => (
                <div key={k} className="rounded-xl border p-3"><dt className="text-xs text-muted-foreground">{label}</dt>
                  <dd className="mt-0.5 font-semibold tabular-nums">{formatMoney(o[k], o.currency || "XOF")}</dd></div>
              ))}
            </dl>
            <p className="mt-3 text-xs text-muted-foreground">Consommation prévisionnelle {o.forecast_consumption_percent} % · rentabilité {o.profit_margin_percent} %</p>
          </>
        )}
      </CardContent>
      <Dialog open={!!form} onOpenChange={(v) => !v && setForm(null)} title={form?.title ?? ""}>
        {form && <LegacyForm compact name={form.name} id={form.id} query={{ project: String(projectId) }} hidden={["project"]} submitLabel="Enregistrer"
          onCancel={() => setForm(null)}
          onSuccess={({ messages }) => { (messages.length ? messages : ["Enregistré."]).forEach((m) => toast.success(m)); setForm(null); void qc.invalidateQueries({ queryKey: ["projects", projectId] }); }} />}
      </Dialog>
    </Card>
  );
}

interface SpaceTask { id: number; title: string; status_label: string; priority_label: string; assignee: string }
interface Kpi { value: unknown; label: string; unit?: string }
interface Space {
  kind: "scrum" | "kanban" | "waterfall" | "";
  methodology: { name: string; code: string } | null;
  kpis: Record<string, Kpi>;
  dashboard: { name: string; pinned: boolean; result: Kpi }[];
  active_sprint?: { id: number; name: string; status_label: string; start_date: string; end_date: string; goal: string; tasks: SpaceTask[] } | null;
  backlog?: { id: number; title: string; status_label: string }[];
  columns?: { code: string; name: string; wip_limit: number | null; count: number; over_wip: boolean; tasks: SpaceTask[] }[];
  phases?: { id: number; name: string; status_label: string; start_date: string | null; end_date: string | null; owner: string }[];
  milestones?: { id: number; name: string; due_date: string | null }[];
}

const KIND_LABEL = { scrum: "Scrum", kanban: "Kanban", waterfall: "Cycle en V / Waterfall" } as const;
const kpiValue = (k: Kpi) => (typeof k.value === "object" ? "—" : `${String(k.value ?? "—")}${k.unit ? ` ${k.unit}` : ""}`);

function TaskLine({ t }: { t: SpaceTask }) {
  return <li className="flex justify-between gap-2"><Link className="truncate hover:text-primary" to={`/tasks/${t.id}`}>{t.title}</Link><span className="shrink-0 text-xs text-muted-foreground">{t.assignee || t.status_label}</span></li>;
}

/** Espace méthodologie (mêmes données que les espaces Scrum/Kanban/Waterfall Django). */
export function MethodologySpace({ projectId }: { projectId: number }) {
  const space = useQuery({ queryKey: ["projects", projectId, "space"], queryFn: ({ signal }) => api<Space>(`projects/${projectId}/space/`, { signal }) });
  const s = space.data;
  if (space.isPending) return <Skeleton className="h-40" />;
  if (!s || (!s.kind && !s.dashboard?.length)) return null;
  const dashboard = s.dashboard ?? [];
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between"><CardTitle>{s.kind ? `Espace ${KIND_LABEL[s.kind]}` : "Tableau de bord méthodologie"}</CardTitle>{s.methodology && <Badge>{s.methodology.name}</Badge>}</CardHeader>
      <CardContent className="space-y-5 text-sm">
        {dashboard.length > 0 && (
          <dl className="grid gap-3 sm:grid-cols-3 xl:grid-cols-4">
            {dashboard.filter((k) => typeof k.result.value !== "object").map((k) => (
              <div key={k.name} className={k.pinned ? "rounded-xl border border-primary/40 p-3" : "rounded-xl border p-3"}>
                <dt className="text-xs text-muted-foreground">{k.name}</dt><dd className="mt-0.5 font-semibold tabular-nums">{kpiValue(k.result)}</dd></div>
            ))}
          </dl>
        )}
        {!dashboard.length && <dl className="grid gap-3 sm:grid-cols-3">
          {Object.entries(s.kpis ?? {}).filter(([, k]) => typeof k.value !== "object").map(([code, k]) => (
            <div key={code} className="rounded-xl border p-3"><dt className="text-xs text-muted-foreground">{k.label && k.label !== "—" ? k.label : code.replace(/_/g, " ")}</dt><dd className="mt-0.5 font-semibold tabular-nums">{kpiValue(k)}</dd></div>
          ))}
        </dl>}
        {s.kind === "scrum" && (
          <div className="grid gap-5 lg:grid-cols-2">
            <div><p className="font-semibold">{s.active_sprint ? `${s.active_sprint.name} · ${s.active_sprint.status_label}` : "Aucun sprint actif"}</p>
              {s.active_sprint && <p className="text-xs text-muted-foreground">{formatDate(s.active_sprint.start_date)} → {formatDate(s.active_sprint.end_date)}{s.active_sprint.goal ? ` · ${s.active_sprint.goal}` : ""}</p>}
              <ul className="mt-2 space-y-1">{s.active_sprint?.tasks.map((t) => <TaskLine key={t.id} t={t} />)}</ul></div>
            <div><p className="font-semibold">Backlog ({s.backlog?.length ?? 0})</p>
              <ul className="mt-2 space-y-1">{s.backlog?.map((b) => <li key={b.id} className="flex justify-between gap-2"><Link className="truncate hover:text-primary" to={`/m/backlog-item/${b.id}`}>{b.title}</Link><span className="text-xs text-muted-foreground">{b.status_label}</span></li>)}</ul>
              <Button size="sm" variant="ghost" className="mt-2" asChild><Link to={`/m/backlog-item/new?project=${projectId}`}><Plus />Élément de backlog</Link></Button></div>
          </div>
        )}
        {s.kind === "kanban" && (
          <div className="flex gap-3 overflow-x-auto pb-1">
            {s.columns?.map((c) => (
              <div key={c.code} className="w-56 shrink-0 rounded-xl border bg-muted/30 p-2.5">
                <p className="flex justify-between text-xs font-semibold uppercase tracking-wide"><span>{c.name}</span>
                  <span className={c.over_wip ? "text-destructive" : "text-muted-foreground"}>{c.count}{c.wip_limit != null ? ` / ${c.wip_limit}` : ""}</span></p>
                <ul className="mt-2 space-y-1">{c.tasks.map((t) => <TaskLine key={t.id} t={t} />)}</ul>
              </div>
            ))}
          </div>
        )}
        {s.kind === "waterfall" && (
          <div className="grid gap-5 lg:grid-cols-2">
            <div><p className="font-semibold">Phases</p>
              <ol className="mt-2 space-y-1">{s.phases?.map((p) => <li key={p.id} className="flex justify-between gap-2"><span>{p.name}</span><span className="text-xs text-muted-foreground">{p.status_label} · {formatDate(p.start_date)} → {formatDate(p.end_date)}</span></li>)}</ol></div>
            <div><p className="font-semibold">Jalons</p>
              <ul className="mt-2 space-y-1">{s.milestones?.map((m) => <li key={m.id} className="flex justify-between gap-2"><Link className="hover:text-primary" to={`/m/milestone/${m.id}`}>{m.name}</Link><span className="text-xs text-muted-foreground">{formatDate(m.due_date)}</span></li>)}</ul></div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
