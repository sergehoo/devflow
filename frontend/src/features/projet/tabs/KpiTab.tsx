import { formatNumber } from "@/lib/format";
import type { KpiTab as Data } from "../api";
import { money, percent } from "../format";
import { EmptyLine, Section, Stat, StatGrid, Table, Td } from "../ui";

/** Onglet KPI & ROI. Montants (coûts / revenus) servis par Django aux seuls droits financiers. */
export function KpiTab({ data, currency, canViewFinancials: fin }: { data: Data; currency: string; canViewFinancials: boolean }) {
  return (
    <div className="space-y-6">
      <StatGrid>
        <Stat label="KPI" value={data.kpi_summary.count} />
        <Stat label="Modules KPI" value={data.kpi_summary.modules_count} />
        <Stat label="ROI modules" value={data.roi_summary.count} />
        <Stat label="ROI global" value={percent(data.roi_summary.global_roi_percent, 1)}
          hint={fin ? `Coût ${money(data.roi_summary.total_cost, currency)} · revenu ${money(data.roi_summary.total_revenue, currency)}` : undefined} />
      </StatGrid>

      <div className="grid gap-6 xl:grid-cols-2">
        <Section title="KPI projet" description="Indicateurs métier et produit" count={data.kpis.length}>
          {data.kpis.length ? (
            <Table caption="KPI du projet" minWidth="min-w-[420px]" head={["Nom", "Module", "Valeur", "Unité"]}>
              {data.kpis.map((k) => (
                <tr key={k.id} className="hover:bg-muted/40">
                  <Td className="font-medium">{k.name}</Td>
                  <Td className="text-muted-foreground">{k.module_name || "—"}</Td>
                  <Td className="text-right tabular-nums">{k.value !== null ? formatNumber(k.value) : k.value_text || "—"}</Td>
                  <Td className="text-muted-foreground">{k.unit || "—"}</Td>
                </tr>
              ))}
            </Table>
          ) : <EmptyLine>Aucun KPI.</EmptyLine>}
        </Section>

        <Section title="ROI par module" description="Rentabilité projetée par composant" count={data.module_rois.length}>
          {data.module_rois.length ? (
            <Table caption="ROI par module" minWidth="min-w-[420px]" head={fin ? ["Module", "Coût", "Revenu", "ROI"] : ["Module", "ROI"]}>
              {data.module_rois.map((r) => (
                <tr key={r.id} className="hover:bg-muted/40">
                  <Td className="font-medium">{r.module_name}</Td>
                  {fin && <Td className="text-right tabular-nums">{money(r.estimated_cost, currency)}</Td>}
                  {fin && <Td className="text-right tabular-nums">{money(r.estimated_revenue, currency)}</Td>}
                  <Td className="text-right font-semibold tabular-nums text-success">{percent(r.roi_percent, 1)}</Td>
                </tr>
              ))}
            </Table>
          ) : <EmptyLine>Aucun ROI module.</EmptyLine>}
        </Section>
      </div>

      {data.sprint_finance && data.feature_finance && (
        <div className="grid gap-6 xl:grid-cols-2">
          <Section title="Finance des sprints" description="Vue synthétique par sprint">
            <div className="grid grid-cols-2 gap-3">
              <Stat label="Snapshots" value={data.sprint_finance.count} />
              <Stat label="Coût total" value={money(data.sprint_finance.total_estimated_cost, currency)} />
            </div>
          </Section>
          <Section title="Finance des features" description="Vue synthétique par backlog / feature">
            <div className="grid grid-cols-2 gap-3">
              <Stat label="Snapshots" value={data.feature_finance.count} />
              <Stat label="ROI global" value={percent(data.feature_finance.global_roi_percent, 1)} />
            </div>
          </Section>
        </div>
      )}
    </div>
  );
}
