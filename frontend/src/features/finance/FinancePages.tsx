import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Download, Percent, PiggyBank, Plus, Sparkles, Trash2, TrendingUp, Wallet } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import type { FormFieldSchema } from "@/components/forms/schema";

type FormSchema = { fields: FormFieldSchema[] };
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/input";
import { useMe } from "@/features/auth/api";
import { ProgressBar, StatCard, WidgetHeader } from "@/features/dashboard/widgets";
import { DownloadButton } from "@/features/meetings/DownloadButton";
import { formatDate, formatMoney, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";

// ─── Cockpit financier (portefeuille) ────────────────────────────────────────

interface PortfolioRow {
  project: { id: number; name: string; status_label: string };
  approved_budget: number; actual_cost: number; forecast_final_cost: number; planned_revenue: number; received_revenue: number;
  real_margin: number; forecast_margin: number; expense_ratio_percent: number; currency: string;
}
interface Portfolio {
  workspace: { id: number; name: string }; rows: PortfolioRow[]; totals: Record<string, number>;
  totals_real_margin: number; totals_forecast_margin: number; totals_consumption_percent: number;
}

export function FinancePortfolioPage() {
  const { data: me } = useMe();
  const ws = me?.workspace?.id;
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ["finance", "portfolio", ws], enabled: Boolean(ws),
    queryFn: ({ signal }) => api<Portfolio>("finance/portfolio/", { signal, params: { workspace: ws } }),
  });
  if (!ws) return <EmptyState title="Aucun workspace" />;
  if (isPending) return <PageSkeleton />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;
  const cur = data.rows[0]?.currency || "XOF";
  const t = data.totals;
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Finance" title="Cockpit financier" description={`Portefeuille de ${data.workspace.name} : budgets, coûts, revenus et marges par projet.`}
        actions={<Button asChild variant="outline"><Link to="/finance/allocation"><Sparkles />Allocation IA</Link></Button>} />
      <section aria-label="Totaux" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard icon={Wallet} value={Math.round(t.approved_budget ?? 0)} unit={cur} label="Budget approuvé" />
        <StatCard icon={PiggyBank} value={Math.round(t.actual_cost ?? 0)} unit={cur} label="Coût réel" hint={`${data.totals_consumption_percent} % consommé`} />
        <StatCard icon={TrendingUp} value={Math.round(t.received_revenue ?? 0)} unit={cur} label="Revenus encaissés" />
        <StatCard icon={Percent} value={Math.round(data.totals_real_margin)} unit={cur} label="Marge réelle" hint={`prév. ${formatNumber(Math.round(data.totals_forecast_margin))}`} />
      </section>
      {data.rows.length ? (
        <div className="overflow-x-auto rounded-[22px] bg-card shadow-card dark:border dark:border-border">
          <table className="w-full min-w-[900px] text-sm">
            <caption className="sr-only">Portefeuille financier</caption>
            <thead className="border-b bg-muted text-left text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>{["Projet", "Budget", "Coût réel", "Coût final prévu", "Revenus prévus", "Encaissé", "Marge réelle", "Consommation"].map((h) => <th key={h} scope="col" className="px-4 py-3 font-semibold">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y">
              {data.rows.map((r) => (
                <tr key={r.project.id} className="hover:bg-muted">
                  <td className="px-4 py-3"><Link to={`/projects/${r.project.id}?tab=budget_previsionnel`} className="font-medium hover:text-brand">{r.project.name}</Link><span className="block text-xs text-muted-foreground">{r.project.status_label}</span></td>
                  {[r.approved_budget, r.actual_cost, r.forecast_final_cost, r.planned_revenue, r.received_revenue].map((v, i) => <td key={i} className="px-4 py-3 tabular">{formatMoney(v, r.currency)}</td>)}
                  <td className={cn("px-4 py-3 font-semibold tabular", r.real_margin < 0 ? "text-destructive" : "text-success")}>{formatMoney(r.real_margin, r.currency)}</td>
                  <td className="w-40 px-4 py-3"><ProgressBar value={r.expense_ratio_percent} label={`Consommation ${r.project.name}`} /><span className="text-xs text-muted-foreground">{r.expense_ratio_percent} %</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <EmptyState title="Aucun projet" description="Aucun projet actif dans ce workspace." />}
    </div>
  );
}

// ─── Allocation IA ───────────────────────────────────────────────────────────

interface Allocation {
  recommendations: { user_id: number; user_label: string; project_id: number; project_name: string; suggested_allocation_percent: number; expected_cost: string; expected_margin: string; rationale: string }[];
  underloaded_users: unknown[]; overloaded_users: unknown[]; ai_summary: string; used_provider: string;
}

const label = (u: unknown) => (typeof u === "object" && u ? String((u as Record<string, unknown>).label ?? (u as Record<string, unknown>).user_label ?? (u as Record<string, unknown>).name ?? "") : String(u));

export function AllocationPage() {
  const { data: me } = useMe();
  const ws = me?.workspace?.id;
  const { data, isPending, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["finance", "allocation", ws], enabled: Boolean(ws), staleTime: 300_000,
    queryFn: ({ signal }) => api<Allocation>("finance/allocation/", { signal, params: { workspace: ws } }),
  });
  if (!ws) return <EmptyState title="Aucun workspace" />;
  if (isPending) return <PageSkeleton />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Finance" title="Allocation des ressources" description={`Recommandations calculées sur les TJM et les charges (${data.used_provider || "heuristique"}).`}
        actions={<Button variant="outline" disabled={isFetching} onClick={() => void refetch()}><Sparkles />Recalculer</Button>} />
      {data.ai_summary && <Card className="p-5 sm:p-6"><WidgetHeader title="Synthèse" /><p className="mt-2 whitespace-pre-wrap text-sm">{data.ai_summary}</p></Card>}
      <div className="grid gap-5 lg:grid-cols-2">
        {([["Sous-chargés", data.underloaded_users], ["Surchargés", data.overloaded_users]] as const).map(([title, users]) => (
          <Card key={title} className="p-5 sm:p-6">
            <WidgetHeader title={title} meta={`${users.length}`} />
            {users.length ? <ul className="mt-2 flex flex-wrap gap-2">{users.map((u, i) => <li key={i} className="rounded-full bg-hover px-3 py-1 text-xs">{label(u)}</li>)}</ul>
              : <p className="mt-2 text-sm text-muted-foreground">Aucun.</p>}
          </Card>
        ))}
      </div>
      <Card className="p-5 sm:p-6">
        <WidgetHeader title="Recommandations" />
        {data.recommendations.length ? (
          <ul className="mt-3 divide-y">
            {data.recommendations.map((r, i) => (
              <li key={i} className="py-3 text-sm">
                <p className="font-medium">{r.user_label} → <Link className="hover:text-brand" to={`/projects/${r.project_id}`}>{r.project_name}</Link> · {r.suggested_allocation_percent} %</p>
                <p className="text-xs text-muted-foreground">Coût attendu {r.expected_cost} · marge {r.expected_margin}</p>
                {r.rationale && <p className="mt-1 text-xs">{r.rationale}</p>}
              </li>
            ))}
          </ul>
        ) : <p className="mt-2 text-sm text-muted-foreground">Aucune recommandation pour le moment.</p>}
      </Card>
    </div>
  );
}

// ─── Éditeur de facture ──────────────────────────────────────────────────────

interface Line { id: number; line_type: string; line_type_display: string; label: string; description: string; quantity: string; unit_price: string; total_amount: string; position: number }
interface Totals { subtotal_ht: string; discount_amount: string; tax_rate: string; tax_amount: string; total_ttc: string; paid_amount: string; remaining_due: string; currency: string; status: string; status_display: string }
interface Payments { payments: { id: number; amount: number; received_at: string; method: string; reference: string; status: string }[]; can_edit: boolean; form: FormSchema }

export function InvoiceEditorPage() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const key = ["finance", "invoice", id];
  const lines = useQuery({ queryKey: [...key, "lines"], queryFn: ({ signal }) => api<{ lines: Line[]; totals: Totals }>(`invoices/${id}/lines/`, { signal }) });
  const pay = useQuery({ queryKey: [...key, "payments"], queryFn: ({ signal }) => api<Payments>(`invoices/${id}/payments/`, { signal }) });
  const [payOpen, setPayOpen] = useState(false);
  const [draft, setDraft] = useState({ label: "", quantity: "1", unit_price: "0" });
  const refresh = () => void qc.invalidateQueries({ queryKey: key });
  const call = useMutation({
    mutationFn: ({ path, method, body }: { path: string; method: string; body?: Record<string, unknown> }) => api(path, { method, body }),
    onSuccess: refresh, onError: (e) => toast.error(e.message),
  });
  if (lines.isPending) return <PageSkeleton />;
  if (lines.isError) return <ErrorState message={lines.error.message} onRetry={() => void lines.refetch()} />;
  const t = lines.data.totals;
  const editable = Boolean(pay.data?.can_edit) && t.status === "DRAFT";
  const rows = [...lines.data.lines].sort((a, b) => a.position - b.position);
  const move = (index: number, delta: number) => {
    const order = rows.map((r) => r.id);
    const [x] = order.splice(index, 1);
    order.splice(index + delta, 0, x!);
    call.mutate({ path: `invoices/${id}/lines/reorder/`, method: "POST", body: { order } });
  };
  const add = (e: FormEvent) => {
    e.preventDefault();
    call.mutate({ path: `invoices/${id}/lines/`, method: "POST", body: { ...draft, line_type: "CUSTOM" } }, { onSuccess: () => setDraft({ label: "", quantity: "1", unit_price: "0" }) });
  };
  const cell = (l: Line, field: "label" | "quantity" | "unit_price") => editable ? (
    <Input aria-label={`${field} de ${l.label}`} defaultValue={l[field]} className="h-9"
      onBlur={(e) => e.target.value !== l[field] && call.mutate({ path: `invoice-lines/${l.id}/`, method: "PATCH", body: { [field]: e.target.value } })} />
  ) : <span>{l[field]}</span>;
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Facturation" title={`Facture — ${t.status_display}`} description={editable ? "Brouillon : lignes, remise et TVA modifiables." : "Seules les factures en brouillon sont modifiables."}
        actions={(
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline"><Link to={`/m/invoice/${id}`}>Fiche et actions</Link></Button>
            <DownloadButton href={`/billing/invoices/${id}/pdf/`} filename={`facture-${id}.pdf`}><Download />PDF</DownloadButton>
            <DownloadButton href={`/billing/invoices/${id}/docx/`} filename={`facture-${id}.docx`}><Download />Word</DownloadButton>
          </div>
        )} />
      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <caption className="sr-only">Lignes de facture</caption>
          <thead className="border-b bg-muted text-left text-[11px] uppercase tracking-wider text-muted-foreground">
            <tr><th className="px-4 py-3">Libellé</th><th className="w-24 px-4 py-3">Qté</th><th className="w-36 px-4 py-3">PU</th><th className="w-36 px-4 py-3 text-right">Total</th><th className="w-28 px-2 py-3"><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((l, i) => (
              <tr key={l.id}>
                <td className="px-4 py-2">{cell(l, "label")}<span className="text-xs text-muted-foreground">{l.line_type_display}</span></td>
                <td className="px-4 py-2">{cell(l, "quantity")}</td>
                <td className="px-4 py-2">{cell(l, "unit_price")}</td>
                <td className="px-4 py-2 text-right font-semibold tabular">{formatMoney(l.total_amount, t.currency)}</td>
                <td className="px-2 py-2">
                  {editable && <div className="flex justify-end gap-1">
                    <Button size="icon" variant="ghost" className="size-8" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Monter ${l.label}`}><ArrowUp /></Button>
                    <Button size="icon" variant="ghost" className="size-8" disabled={i === rows.length - 1} onClick={() => move(i, 1)} aria-label={`Descendre ${l.label}`}><ArrowDown /></Button>
                    <Button size="icon" variant="ghost" className="size-8 text-destructive" onClick={() => call.mutate({ path: `invoice-lines/${l.id}/`, method: "DELETE" })} aria-label={`Supprimer ${l.label}`}><Trash2 /></Button>
                  </div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {editable && (
          <form onSubmit={add} className="grid gap-2 border-t p-4 sm:grid-cols-[1fr_100px_140px_auto]">
            <Input aria-label="Nouvelle ligne : libellé" required placeholder="Nouvelle ligne…" value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })} />
            <Input aria-label="Quantité" type="number" step="0.01" value={draft.quantity} onChange={(e) => setDraft({ ...draft, quantity: e.target.value })} />
            <Input aria-label="Prix unitaire" type="number" step="0.01" value={draft.unit_price} onChange={(e) => setDraft({ ...draft, unit_price: e.target.value })} />
            <Button type="submit" disabled={call.isPending}><Plus />Ajouter</Button>
          </form>
        )}
      </Card>
      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="p-5 sm:p-6">
          <WidgetHeader title="Totaux" />
          <dl className="mt-3 grid grid-cols-[1fr_auto] gap-y-2 text-sm">
            <dt className="text-muted-foreground">Sous-total HT</dt><dd className="tabular">{formatMoney(t.subtotal_ht, t.currency)}</dd>
            <dt className="text-muted-foreground">Remise</dt>
            <dd>{editable ? <Input aria-label="Remise" className="h-8 w-32" type="number" defaultValue={t.discount_amount} onBlur={(e) => call.mutate({ path: `invoices/${id}/totals/`, method: "PATCH", body: { discount_amount: e.target.value } })} /> : formatMoney(t.discount_amount, t.currency)}</dd>
            <dt className="text-muted-foreground">TVA (%)</dt>
            <dd>{editable ? <Input aria-label="Taux de TVA" className="h-8 w-32" type="number" defaultValue={t.tax_rate} onBlur={(e) => call.mutate({ path: `invoices/${id}/totals/`, method: "PATCH", body: { tax_rate: e.target.value } })} /> : `${t.tax_rate} %`}</dd>
            <dt className="text-muted-foreground">TVA</dt><dd className="tabular">{formatMoney(t.tax_amount, t.currency)}</dd>
            <dt className="font-semibold">Total TTC</dt><dd className="font-semibold tabular">{formatMoney(t.total_ttc, t.currency)}</dd>
            <dt className="text-muted-foreground">Payé</dt><dd className="tabular">{formatMoney(t.paid_amount, t.currency)}</dd>
            <dt className="font-semibold">Reste dû</dt><dd className="font-semibold tabular">{formatMoney(t.remaining_due, t.currency)}</dd>
          </dl>
        </Card>
        <Card className="p-5 sm:p-6">
          <WidgetHeader title="Paiements" action={pay.data?.can_edit && t.status !== "DRAFT" && t.status !== "CANCELLED" ? <Button size="sm" onClick={() => setPayOpen(true)}><Plus />Paiement</Button> : undefined} />
          {pay.data?.payments.length ? (
            <ul className="mt-3 divide-y text-sm">
              {pay.data.payments.map((p) => <li key={p.id} className="flex justify-between gap-2 py-2"><span>{formatDate(p.received_at)} · {p.method}{p.reference ? ` · ${p.reference}` : ""}</span><span className="font-semibold tabular">{formatMoney(p.amount, t.currency)}</span></li>)}
            </ul>
          ) : <p className="mt-2 text-sm text-muted-foreground">Aucun paiement enregistré.</p>}
        </Card>
      </div>
      <Dialog open={payOpen} onOpenChange={setPayOpen} title="Enregistrer un paiement">
        {pay.data && <PaymentForm invoiceId={id} schema={pay.data.form} onDone={() => { setPayOpen(false); refresh(); }} />}
      </Dialog>
    </div>
  );
}

function PaymentForm({ invoiceId, schema, onDone }: { invoiceId: number; schema: FormSchema; onDone: () => void }) {
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(schema.fields.map((f) => [f.name, f.value == null ? "" : String(f.value)])));
  const [pending, setPending] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setPending(true);
    const fd = new FormData();
    Object.entries(values).forEach(([k, v]) => fd.append(k, v));
    try { await api(`invoices/${invoiceId}/payments/`, { method: "POST", body: fd }); toast.success("Paiement enregistré."); onDone(); }
    catch (err) { toast.error((err as Error).message); }
    finally { setPending(false); }
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      {schema.fields.filter((f) => f.type !== "hidden").map((f) => (
        <label key={f.name} className="block text-sm">
          <span className="mb-1 block text-xs font-semibold text-muted-foreground">{f.label}{f.required ? " *" : ""}</span>
          {f.type === "select" ? (
            <Select value={values[f.name]} required={f.required} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}>
              {(f.choices ?? []).map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </Select>
          ) : (
            <Input type={f.type === "number" ? "number" : f.type === "date" ? "date" : "text"} step="0.01" required={f.required}
              value={values[f.name]} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
          )}
        </label>
      ))}
      <div className="flex justify-end gap-2"><Button type="button" variant="outline" onClick={onDone}>Annuler</Button><Button type="submit" disabled={pending}>Enregistrer</Button></div>
    </form>
  );
}

