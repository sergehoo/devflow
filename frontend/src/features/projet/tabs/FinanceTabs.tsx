/** Onglets financiers (servis par Django uniquement si `can_view_financials`). */
import { Banknote, Bot, Calculator, Eye, FilePlus2, List, Pencil, Plus, Receipt, RefreshCw, Sparkles, Wand2 } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { formatDate, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  projectEditPath, useAIForecast, useProjectBudgetAction,
  type BillingTab as BillingData, type EstimateTab as EstimateData, type ExpensesTab as ExpensesData, type ForecastTab as ForecastData,
} from "../api";
import { approvalTone, expenseTone, invoiceTone, money, percent, revenueTone } from "../format";
import type { FormSpec } from "../formDialog";
import { ActionBar, EmptyLine, ExcelButton, Pill, ProgressBar, Section, Stat, StatGrid, Table, Td } from "../ui";

type OpenForm = (s: FormSpec) => void;
const budgetForm = (projectId: number, budgetId: number | null): FormSpec => ({
  name: "project-budget", title: budgetId ? "Modifier le budget" : "Créer le budget", id: budgetId ?? undefined,
  query: { project: String(projectId) },
});

// ─── Budget estimatif ───────────────────────────────────────────────────────
export function EstimateTab({ projectId, data, openForm }: { projectId: number; data: EstimateData; openForm: OpenForm }) {
  const c = data.currency;
  const action = useProjectBudgetAction(projectId);
  const run = (name: Parameters<typeof action.mutate>[0]) =>
    action.mutate(name, {
      onSuccess: (r) => (r.messages?.length ? r.messages : ["Budget mis à jour."]).forEach((m) => toast.success(m)),
      onError: (e) => toast.error(e.message),
    });
  return (
    <div className="space-y-6">
      <ActionBar title="Budget estimatif" description="Structurez le chiffrage et mettez à jour les lignes d'estimation.">
        <Button size="sm" onClick={() => openForm(budgetForm(projectId, data.budget_id))}><Calculator />{data.budget_id ? "Modifier le budget" : "Créer le budget"}</Button>
        <Button size="sm" variant="outline" onClick={() => openForm({ name: "estimate-line", title: "Ligne d'estimation", query: { project: String(projectId) }, submitLabel: "Ajouter" })}><Plus />Ligne d'estimation</Button>
        <Button size="sm" variant="ghost" disabled={action.isPending} onClick={() => run("project-generate-estimates")}><Wand2 />Estimer depuis les tâches</Button>
        <Button size="sm" variant="ghost" disabled={action.isPending} onClick={() => run("project-recalculate-budget")}><Calculator />Recalculer</Button>
        <Button size="sm" variant="ghost" disabled={action.isPending} onClick={() => run("project-refresh-financials")}><RefreshCw />Rafraîchir</Button>
        <ExcelButton projectId={projectId} label="Exporter le chiffrage" />
        {data.budget_id && <Button size="sm" variant="ghost" asChild><Link to={`/m/project-budget/${data.budget_id}`}><Eye />Tout voir</Link></Button>}
      </ActionBar>

      <StatGrid className="xl:grid-cols-5">
        <Stat label="Coût MO estimé" value={money(data.cards.labor_cost, c)} />
        <Stat label="Logiciels" value={money(data.cards.software_cost, c)} />
        <Stat label="Infrastructure" value={money(data.cards.infra_cost, c)} />
        <Stat label="Sous-traitance" value={money(data.cards.subcontract_cost, c)} />
        <Stat label="Total estimé" value={money(data.cards.total_estimated, c)} className="col-span-2 md:col-span-1" />
      </StatGrid>

      <Section title="Lignes détaillées d'estimation" description="Base de chiffrage et export client" count={data.lines.length}
        actions={<ExcelButton projectId={projectId} label="Exporter pour facturation" variant="default" />}>
        <StatGrid className="mb-4">
          <Stat label="Majoration projet" value={percent(data.markup_percent, 2)} />
          <Stat label="Vente projetée" value={money(data.total_estimated_sale, c)} />
          <Stat label="Revenu attendu" value={money(data.planned_revenue, c)} />
          <Stat label="Marge estimée" value={money(data.total_estimated_margin, c)} />
        </StatGrid>
        {data.lines.length ? (
          <Table caption="Lignes d'estimation" minWidth="min-w-[860px]"
            head={["Libellé", "Catégorie", "Étape", "Source", "Quantité", "Coût unitaire", "Coût total", "Vente totale", "Marge"]}>
            {data.lines.map((l) => (
              <tr key={l.id} className="hover:bg-muted/40">
                <Td className="font-medium">{l.label}</Td>
                <Td className="text-muted-foreground">{l.category || "—"}</Td>
                <Td className="text-muted-foreground">{l.budget_stage_label || "—"}</Td>
                <Td className="text-muted-foreground">{l.source_type_label || "—"}</Td>
                <Td className="text-right tabular-nums">{Number(l.quantity)}</Td>
                <Td className="text-right tabular-nums">{money(l.cost_unit_amount, c)}</Td>
                <Td className="text-right font-medium tabular-nums">{money(l.cost_amount, c)}</Td>
                <Td className="text-right font-semibold tabular-nums">{money(l.sale_amount, c)}</Td>
                <Td className="text-right font-semibold tabular-nums text-success">{money(l.margin_amount, c)}</Td>
              </tr>
            ))}
          </Table>
        ) : <EmptyLine>Aucune ligne d'estimation.</EmptyLine>}
      </Section>

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Coût baseline" value={money(data.baseline_cost, c)} />
        <Stat label="Forecast" value={money(data.forecast_cost, c)} />
        <Stat label="Reste à faire (RAF)" value={money(data.raf_cost, c)} />
      </div>
    </div>
  );
}

// ─── Prévision budgétaire IA (ProjectBudgetForecastView) ────────────────────
function AIForecastPanel({ projectId, currency }: { projectId: number; currency: string }) {
  const forecast = useAIForecast(projectId);
  const f = forecast.data;
  const overrun = f?.overrun_risk_percent ?? 0;
  const overrunTone = overrun >= 70 ? "danger" : overrun >= 40 ? "warning" : "success";
  return (
    <Section title="Prévision budgétaire IA" description="Projection des coûts à venir (TJM, allocation, RAF, engagements), enrichie par l'IA."
      actions={
        <Button size="sm" disabled={forecast.isPending} onClick={() => forecast.mutate(undefined, { onError: (e) => toast.error(e.message) })}>
          <Sparkles className={cn(forecast.isPending && "animate-pulse")} />{forecast.isPending ? "Calcul en cours…" : f ? "Recalculer" : "Lancer la prévision"}
        </Button>
      }>
      {!f ? (
        <p className="text-sm text-muted-foreground">
          {forecast.isError ? forecast.error.message : "Lancez la prévision pour obtenir le coût attendu, la fourchette, la marge et le risque de dépassement."}
        </p>
      ) : (
        <div className="space-y-4">
          <StatGrid>
            <Stat label="Coût attendu" value={money(f.base_cost, currency)} hint="Projection centrale" />
            <Stat label="Fourchette" value={<span className="text-lg">{money(f.optimistic_cost, currency)} – {money(f.pessimistic_cost, currency)}</span>} hint="Optimiste / pessimiste" />
            <Stat label="Marge attendue" value={<span className={Number(f.expected_margin) >= 0 ? "text-success" : "text-destructive"}>{money(f.expected_margin, currency)}</span>} hint={percent(f.expected_margin_percent, 1)} />
            <Stat label="Risque de dépassement" value={<span className={overrunTone === "danger" ? "text-destructive" : overrunTone === "warning" ? "text-warning" : "text-success"}>{overrun} %</span>}
              hint={overrun >= 70 ? "Risque élevé" : overrun >= 40 ? "Risque modéré" : "Risque faible"} />
          </StatGrid>
          <div className="rounded-xl border bg-muted/30 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="flex items-center gap-2 font-semibold"><Bot className="size-4 text-brand" aria-hidden="true" />Synthèse IA</p>
              <Pill tone={f.confidence === "high" ? "success" : f.confidence === "low" ? "danger" : "warning"}>Confiance {f.confidence === "high" ? "élevée" : f.confidence === "low" ? "faible" : "moyenne"}</Pill>
            </div>
            <p className="mt-2 text-sm text-muted-foreground">
              {f.ai_summary || "Le moteur IA n'a pas généré de synthèse : les valeurs ci-dessus sont calculées par les heuristiques DevFlow."}
            </p>
            {f.ai_recommendations.length > 0 && (
              <><p className="mt-3 text-sm font-semibold">Recommandations</p>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-muted-foreground">{f.ai_recommendations.map((r) => <li key={r}>{r}</li>)}</ul></>
            )}
            {f.drivers.length > 0 && (
              <><p className="mt-3 text-sm font-semibold">Facteurs principaux</p>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-muted-foreground">{f.drivers.map((d) => <li key={d}>{d}</li>)}</ul></>
            )}
            <p className="mt-3 text-xs text-muted-foreground">Moteur : <span className="font-mono">{f.used_provider}</span> · horizon {formatDate(f.horizon_end)}</p>
          </div>
        </div>
      )}
    </Section>
  );
}

// ─── Budget prévisionnel ────────────────────────────────────────────────────
export function ForecastTab({ projectId, workspaceId, data, openForm }: { projectId: number; workspaceId?: number; data: ForecastData; openForm: OpenForm }) {
  const c = data.currency;
  return (
    <div className="space-y-6">
      <ActionBar title="Actions rapides · Budget prévisionnel" description="Pilotez la rentabilité et les prévisions de revenus.">
        <Button size="sm" onClick={() => openForm({ name: "project-revenue", title: "Revenu prévisionnel", query: { project: String(projectId) }, submitLabel: "Ajouter" })}><Banknote />Ajouter un revenu prévisionnel</Button>
        <Button size="sm" variant="outline" onClick={() => openForm(budgetForm(projectId, data.budget_id))}><RefreshCw />Réviser le budget</Button>
        <Button size="sm" variant="outline" asChild><Link to={projectEditPath(projectId, workspaceId)}><Pencil />Mettre à jour le projet</Link></Button>
      </ActionBar>

      <StatGrid>
        <Stat label="Budget approuvé" value={money(data.approved_budget, c)} />
        <Stat label="Revenus attendus" value={money(data.planned_revenue, c)} />
        <Stat label="Dépenses validées" value={money(data.actual_cost, c)} />
        <Stat label="Marge prévisionnelle" value={money(data.forecast_margin, c)} />
      </StatGrid>
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Taux de marge cible" value={percent(data.target_margin_percent)} />
        <Stat label="Taux de marge estimé" value={percent(data.profit_margin_percent)} />
        <Stat label="Consommation du budget" value={percent(data.expense_ratio_percent)} />
      </div>
      <StatGrid>
        <Stat label="Facturé" value={money(data.invoiced_revenue, c)} />
        <Stat label="Encaissé" value={money(data.received_revenue, c)} />
        <Stat label="Reste à facturer" value={money(data.remaining_to_invoice, c)} />
        <Stat label="Reste à encaisser" value={money(data.remaining_to_collect, c)} />
      </StatGrid>

      <AIForecastPanel projectId={projectId} currency={c} />

      <Section title="Prévisions de revenus" description="Encaissements attendus par source" count={data.revenues.length}>
        {data.revenues.length ? (
          <Table caption="Prévisions de revenus" head={["Libellé", "Type", "Montant", "Facturé", "Encaissé", "Date prévue", "Statut"]}>
            {data.revenues.map((r) => (
              <tr key={r.id} className="hover:bg-muted/40">
                <Td className="font-medium">{r.title}</Td>
                <Td className="text-muted-foreground">{r.revenue_type_label || "—"}</Td>
                <Td className="text-right font-medium tabular-nums">{money(r.amount, r.currency)}</Td>
                <Td className="text-right tabular-nums">{money(r.invoiced_amount, r.currency)}</Td>
                <Td className="text-right tabular-nums">{money(r.received_amount, r.currency)}</Td>
                <Td className="text-muted-foreground">{formatDate(r.expected_date)}</Td>
                <Td><Pill tone={r.is_received ? "success" : "warning"}>{r.is_received ? "Reçu" : "En attente"}</Pill></Td>
              </tr>
            ))}
          </Table>
        ) : <EmptyLine>Aucune prévision de revenu.</EmptyLine>}
      </Section>
    </div>
  );
}

// ─── Dépenses ───────────────────────────────────────────────────────────────
export function ExpensesTab({ projectId, data, openForm }: { projectId: number; data: ExpensesData; openForm: OpenForm }) {
  const c = data.currency;
  const s = data.stats;
  return (
    <div className="space-y-6">
      <ActionBar title="Actions rapides · Dépenses" description="Enregistrez et contrôlez les charges du projet.">
        <Button size="sm" onClick={() => openForm({ name: "project-expense", title: "Nouvelle dépense", query: { project: String(projectId) }, submitLabel: "Créer" })}><Receipt />Nouvelle dépense</Button>
        <Button size="sm" variant="outline" asChild><Link to={`/m/project-expense?project=${projectId}`}><List />Voir toutes les dépenses</Link></Button>
        <ExcelButton projectId={projectId} label="Exporter" />
      </ActionBar>

      <StatGrid>
        <Stat label="Estimatif" value={money(s.estimated_expenses, c)} />
        <Stat label="Engagé" value={money(s.committed_expenses, c)} />
        <Stat label="Constaté" value={money(s.accrued_expenses, c)} />
        <Stat label="Réel payé" value={money(s.paid_expenses, c)} />
      </StatGrid>
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Coût RH" value={money(s.labor_cost, c)} />
        <Stat label="Coût direct" value={money(s.direct_cost, c)} />
        <Stat label="Autres coûts" value={money(s.other_cost, c)} />
      </div>

      <Section title="Liste des dépenses" description="Charges engagées sur le projet (validation N1 / N2 depuis la fiche de la dépense)" count={data.expenses.length}
        actions={<ExcelButton projectId={projectId} variant="default" />}>
        {data.expenses.length ? (
          <Table caption="Dépenses du projet" minWidth="min-w-[820px]" head={["Date", "Libellé", "État", "Validation", "Montant", "Actions"]}>
            {data.expenses.map((e) => (
              <tr key={e.id} className="hover:bg-muted/40">
                <Td className="whitespace-nowrap"><span className="font-medium">{formatDate(e.expense_date)}</span>
                  {e.created_at && <span className="block text-xs text-muted-foreground">{formatDateTime(e.created_at)}</span>}</Td>
                <Td className="min-w-56">
                  <span className="font-semibold">{e.title}</span>
                  {e.description && <span className="mt-0.5 block text-xs text-muted-foreground">{e.description}</span>}
                  <span className="mt-1 flex flex-wrap gap-1">
                    {e.reference && <Pill>Réf. {e.reference}</Pill>}
                    {e.is_direct_cost && <Pill tone="info">Coût direct</Pill>}
                    {e.is_labor_cost && <Pill tone="warning">RH</Pill>}
                  </span>
                </Td>
                <Td><Pill tone={expenseTone(e.status)}>{e.status_label}</Pill></Td>
                <Td><Pill tone={approvalTone(e.approval_state)}>{e.approval_state_label || "—"}</Pill></Td>
                <Td className="whitespace-nowrap text-right font-serif text-lg font-medium tabular-nums">{money(e.amount, e.currency)}</Td>
                <Td>
                  <div className="flex justify-end gap-1.5">
                    <Button size="sm" variant="outline" asChild><Link to={`/m/project-expense/${e.id}`} aria-label={`Voir la dépense ${e.title}`}><Eye />Voir</Link></Button>
                    {e.can_be_edited && (
                      <Button size="sm" variant="outline" aria-label={`Modifier la dépense ${e.title}`}
                        onClick={() => openForm({ name: "project-expense", title: "Modifier la dépense", id: e.id, query: { project: String(projectId) } })}><Pencil />Modifier</Button>
                    )}
                  </div>
                </Td>
              </tr>
            ))}
          </Table>
        ) : <EmptyLine>Aucune dépense : ajoutez-en une avec « Nouvelle dépense ».</EmptyLine>}
      </Section>
    </div>
  );
}

// ─── Facturation client ─────────────────────────────────────────────────────
export function BillingTab({ projectId, data, openForm }: { projectId: number; data: BillingData; openForm: OpenForm }) {
  const navigate = useNavigate();
  const c = data.currency;
  const inv = data.invoice_summary;
  const generate = () => openForm({
    name: "invoice-generate", title: "Générer une facture", endpoint: `projects/${projectId}/detail-tabs/invoice-generate/`,
    submitLabel: "Générer le brouillon",
    onDone: (r) => navigate(`/m/invoice/${r.id}`),
  });
  return (
    <div className="space-y-6">
      <ActionBar title="Actions rapides · Facturation client" description="Générez des factures depuis les estimations, les heures ou les jalons et suivez les encaissements.">
        {/* Génération = écriture : RBAC `invoice.create` (Django refuse sinon, 403). */}
        {data.can_generate_invoice && <Button size="sm" onClick={generate}><Sparkles />Générer une facture</Button>}
        {data.can_generate_invoice && <Button size="sm" variant="outline" asChild><Link to={`/m/invoice/new?project=${projectId}`}><FilePlus2 />Facture manuelle</Link></Button>}
        <Button size="sm" variant="outline" asChild><Link to={`/m/invoice?project=${projectId}`}><List />Voir toutes les factures</Link></Button>
        <Button size="sm" variant="ghost" onClick={() => openForm({ name: "project-revenue", title: "Prévision de revenu", query: { project: String(projectId) }, submitLabel: "Ajouter" })}><Banknote />Ajouter une prévision de revenu</Button>
      </ActionBar>

      <Section title="Factures émises" description={`${inv.count_total} facture(s) · ${inv.count_overdue} en retard · ${inv.count_draft} brouillon(s)`}
        actions={<><Pill tone="primary">TTC : {money(inv.total_ttc, c)}</Pill><Pill tone="success">Encaissé : {money(inv.total_paid, c)}</Pill><Pill tone="warning">Reste : {money(inv.total_due, c)}</Pill></>}>
        {data.invoices.length ? (
          <>
            <Table caption="Factures du projet" minWidth="min-w-[760px]" head={["Numéro", "Client", "Émise", "Échéance", "TTC", "Encaissé", "Statut"]}>
              {data.invoices.map((i) => (
                <tr key={i.id} className="hover:bg-muted/40">
                  <Td><Link to={`/m/invoice/${i.id}`} className="font-semibold hover:text-brand">{i.number || "(brouillon)"}</Link>
                    <span className="block text-[11px] text-muted-foreground">{i.billing_mode_label}</span></Td>
                  <Td className="text-muted-foreground">{i.client || "—"}</Td>
                  <Td className="text-xs text-muted-foreground">{formatDate(i.issue_date)}</Td>
                  <Td className="text-xs text-muted-foreground">{formatDate(i.due_date)}</Td>
                  <Td className="text-right font-medium tabular-nums">{money(i.total_ttc, i.currency || c)}</Td>
                  <Td className="text-right tabular-nums">{money(i.paid_amount, i.currency || c)}</Td>
                  <Td><Pill tone={invoiceTone(i.status)}>{i.status_label}</Pill></Td>
                </tr>
              ))}
            </Table>
            {data.invoices_total > data.invoices.length && (
              <p className="mt-3 text-right text-xs"><Link className="font-semibold text-brand hover:underline" to={`/m/invoice?project=${projectId}`}>Voir les {data.invoices_total} factures →</Link></p>
            )}
          </>
        ) : (
          <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed p-8 text-center">
            <p className="font-semibold">Aucune facture émise pour ce projet</p>
            {data.can_generate_invoice ? (
              <>
                <p className="max-w-md text-xs text-muted-foreground">Générez un brouillon depuis les estimations, les heures saisies ou les jalons.</p>
                <Button size="sm" onClick={generate}><Sparkles />Générer maintenant</Button>
              </>
            ) : <p className="max-w-md text-xs text-muted-foreground">La génération de factures est réservée aux rôles habilités à facturer.</p>}
          </div>
        )}
      </Section>

      <StatGrid className="xl:grid-cols-5">
        <Stat label="Revenu prévu" value={money(data.billing.planned_revenue, c)} />
        <Stat label="Déjà facturé" value={money(data.billing.invoiced_revenue, c)} />
        <Stat label="Déjà encaissé" value={money(data.billing.received_revenue, c)} />
        <Stat label="Reste à facturer" value={money(data.billing.remaining_to_invoice, c)} />
        <Stat label="Reste à encaisser" value={money(data.billing.remaining_to_collect, c)} className="col-span-2 md:col-span-1" />
      </StatGrid>

      <div className="grid gap-4 xl:grid-cols-2">
        {([
          ["Taux de facturation", "Part du revenu prévu déjà facturée.", data.billing.invoicing_rate_percent, ["Prévu", data.billing.planned_revenue], ["Facturé", data.billing.invoiced_revenue], "bg-primary"],
          ["Taux d'encaissement", "Part des montants facturés effectivement encaissée.", data.billing.collection_rate_percent, ["Facturé", data.billing.invoiced_revenue], ["Encaissé", data.billing.received_revenue], "bg-success"],
        ] as const).map(([title, desc, rate, a, b, bar]) => (
          <Card key={title}><CardContent className="space-y-4">
            <div className="flex items-start justify-between gap-2"><div><h3 className="font-semibold">{title}</h3><p className="text-xs text-muted-foreground">{desc}</p></div><Pill tone="primary">{rate} %</Pill></div>
            <ProgressBar value={rate} label={title} className="h-3" barClassName={bar} />
            <dl className="grid grid-cols-2 gap-3">
              {[a, b].map(([k, v]) => <div key={k} className="rounded-xl border bg-muted/30 p-3"><dt className="text-xs text-muted-foreground">{k}</dt><dd className="font-semibold tabular-nums">{money(v, c)}</dd></div>)}
            </dl>
          </CardContent></Card>
        ))}
      </div>

      <Section title="Lignes de facturation client" description="Prévisions de revenus, états de facturation et encaissements par ligne." count={data.revenues.length}>
        {data.revenues.length ? (
          <Table caption="Lignes de facturation client" minWidth="min-w-[960px]"
            head={["Libellé", "Type", "Montant", "Facturé", "Encaissé", "Reste à facturer", "Reste à encaisser", "Date prévue", "Statut"]}>
            {data.revenues.map((r) => (
              <tr key={r.id} className="hover:bg-muted/40">
                <Td className="min-w-48"><span className="font-semibold">{r.title}</span>{r.notes && <span className="block text-xs text-muted-foreground">{r.notes}</span>}</Td>
                <Td className="whitespace-nowrap text-muted-foreground">{r.revenue_type_label || "—"}</Td>
                <Td className="whitespace-nowrap text-right font-medium tabular-nums">{money(r.amount, r.currency)}</Td>
                <Td className="whitespace-nowrap text-right tabular-nums">{money(r.invoiced_amount, r.currency)}</Td>
                <Td className="whitespace-nowrap text-right tabular-nums">{money(r.received_amount, r.currency)}</Td>
                <Td className="whitespace-nowrap text-right tabular-nums">{money(r.remaining_to_invoice, r.currency)}</Td>
                <Td className="whitespace-nowrap text-right tabular-nums">{money(r.remaining_to_collect, r.currency)}</Td>
                <Td className="whitespace-nowrap text-muted-foreground">{formatDate(r.expected_date)}</Td>
                <Td><Pill tone={revenueTone(r.status)}>{r.status_label || "Prévu"}</Pill></Td>
              </tr>
            ))}
          </Table>
        ) : <EmptyLine>Aucune ligne de facturation client : ajoutez une prévision de revenu.</EmptyLine>}
      </Section>
    </div>
  );
}
