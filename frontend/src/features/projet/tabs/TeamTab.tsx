import { Layers, Lock, Pencil, UserMinus, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Avatar } from "@/components/ui/misc";
import { formatHours } from "@/lib/format";
import { projectEditPath, useResourceDelete, type TeamTab as Data } from "../api";
import { money, percent } from "../format";
import type { FormSpec } from "../formDialog";
import { ActionBar, EmptyLine, Pill, Section, Stat, StatGrid, Table, Td } from "../ui";

/**
 * Onglet Équipes : membres projet, synthèse par équipe, temps saisi et coûts TJM (`billing.view`).
 * Gestion des affectations : boutons affichés selon `can_manage_members` (Django l'impose aussi).
 */
export function TeamTab({ projectId, workspaceId, data, openForm }: {
  projectId: number; workspaceId?: number; data: Data; openForm: (s: FormSpec) => void;
}) {
  const remove = useResourceDelete(projectId, workspaceId);
  const manage = data.can_manage_members;
  const [confirm, setConfirm] = useState<{ id: number; name: string } | null>(null);
  const memberForm = (id?: number): FormSpec => ({
    name: "project-member", title: id ? "Modifier l'affectation" : "Ajouter un membre au projet", id,
    query: { project: String(projectId) }, hidden: ["project"], submitLabel: id ? "Enregistrer" : "Ajouter",
  });
  const ts = data.timesheet_stats;
  const costs = data.member_costs;
  return (
    <div className="space-y-6">
      <ActionBar title="Actions rapides · Équipes" description={manage ? "Affectez rapidement les ressources au projet." : "Consultez la composition de l'équipe projet."}>
        {manage && <Button size="sm" onClick={() => openForm(memberForm())}><UserPlus />Ajouter un membre</Button>}
        <Button size="sm" variant="outline" asChild><Link to="/teams"><Users />Voir les équipes</Link></Button>
        {manage && <Button size="sm" variant="outline" asChild><Link to={projectEditPath(projectId, workspaceId)}><Layers />Modifier les affectations</Link></Button>}
      </ActionBar>

      <StatGrid>
        <Stat label="Membres" value={data.members.length} />
        <Stat label="Équipes liées" value={data.team_summary.length} />
        <Stat label="Membres principaux" value={data.primary_total} />
        <Stat label="Allocation moyenne" value={percent(data.allocation_average)} hint="Selon les affectations projet" />
      </StatGrid>

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.5fr]">
        <Section title="Synthèse équipes" description="Répartition par structure de travail">
          {data.team_summary.length ? (
            <ul className="space-y-2">
              {data.team_summary.map((t) => (
                <li key={t.team_id ?? "none"} className="flex items-center justify-between gap-3 rounded-xl border bg-muted/30 p-3">
                  <div className="min-w-0">
                    {t.team_id ? <Link to={`/teams/${t.team_id}`} className="font-semibold hover:text-brand">{t.team}</Link> : <span className="font-semibold">Sans équipe</span>}
                    <p className="text-xs text-muted-foreground">Membres affectés</p>
                  </div>
                  <div className="text-right"><p className="font-serif text-2xl font-semibold tabular-nums">{t.members_count}</p><p className="text-xs text-muted-foreground">{t.primary_count} principal(aux)</p></div>
                </li>
              ))}
            </ul>
          ) : <EmptyLine>Aucune équipe liée.</EmptyLine>}
        </Section>

        <Section title="Membres projet" description="Affectations, rôles et allocation" count={data.members.length}>
          {data.members.length ? (
            <Table caption="Membres du projet" minWidth="min-w-[600px]" head={["Membre", "Équipe", "Rôle", "Allocation", "Principal", ...(manage ? [""] : [])]}>
              {data.members.map((m) => (
                <tr key={m.id} className="hover:bg-muted/40">
                  <Td><span className="flex items-center gap-2"><Avatar name={m.name} className="size-7 text-[10px]" /><span className="font-medium">{m.name}</span></span></Td>
                  <Td className="text-muted-foreground">{m.team || "—"}</Td>
                  <Td className="text-muted-foreground">{m.role || "—"}</Td>
                  <Td className="text-right font-medium tabular-nums">{m.allocation_percent} %</Td>
                  <Td><Pill tone={m.is_primary ? "success" : "muted"}>{m.is_primary ? "Oui" : "Non"}</Pill></Td>
                  {manage && (
                    <Td>
                      <div className="flex justify-end gap-1">
                        <Button size="icon" variant="ghost" aria-label={`Modifier l'affectation de ${m.name}`} onClick={() => openForm(memberForm(m.id))}><Pencil /></Button>
                        <Button size="icon" variant="ghost" aria-label={`Retirer ${m.name} du projet`} onClick={() => setConfirm({ id: m.id, name: m.name })}><UserMinus /></Button>
                      </div>
                    </Td>
                  )}
                </tr>
              ))}
            </Table>
          ) : <EmptyLine>Aucun membre affecté.</EmptyLine>}
        </Section>
      </div>

      <Section title="Temps saisi" description="Lecture synthétique des feuilles de temps du projet">
        <StatGrid>
          <Stat label="Entrées" value={ts.total_entries} />
          <Stat label="Heures totales" value={formatHours(ts.total_hours)} />
          <Stat label="Heures approuvées" value={formatHours(ts.approved_hours)} />
          <Stat label="Heures soumises" value={formatHours(ts.submitted_hours)} />
        </StatGrid>
      </Section>

      {data.member_costs_restricted && (
        <p className="flex items-center gap-2 rounded-xl border border-dashed bg-muted/30 p-3 text-xs text-muted-foreground">
          <Lock className="size-3.5 shrink-0" aria-hidden="true" />
          Les coûts TJM par membre sont réservés aux rôles habilités à consulter la facturation.
        </p>
      )}

      {costs && (
        <Section title="Coût de l'équipe (TJM)" description={`TJM coût / vente × allocation · ${costs.summary.project_working_days} jour(s) ouvré(s) sur la durée du projet, 22 jours par mois`}>
          <StatGrid className="mb-4">
            <Stat label="Coût / jour" value={money(costs.summary.daily_cost_total, costs.currency)} />
            <Stat label="Coût / mois" value={money(costs.summary.monthly_cost_total, costs.currency)} />
            <Stat label="Coût projet" value={money(costs.summary.project_cost_total, costs.currency)} />
            <Stat label="Marge projet" value={money(costs.summary.project_margin_total, costs.currency)} hint={`Vente ${money(costs.summary.project_sale_total, costs.currency)}`} />
          </StatGrid>
          {costs.rows.length ? (
            <Table caption="Coût TJM par membre" minWidth="min-w-[760px]" head={["Membre", "Allocation", "TJM coût", "TJM vente", "Coût / jour alloué", "Coût / mois", "Coût projet", "Vente projet"]}>
              {costs.rows.map((r) => (
                <tr key={r.member_id} className="hover:bg-muted/40">
                  <Td className="font-medium">{r.name}</Td>
                  <Td className="text-right tabular-nums">{percent(r.allocation_percent)}</Td>
                  <Td className="text-right tabular-nums">{money(r.daily_cost, costs.currency)}</Td>
                  <Td className="text-right tabular-nums">{money(r.daily_sale, costs.currency)}</Td>
                  <Td className="text-right tabular-nums">{money(r.allocated_daily_cost, costs.currency)}</Td>
                  <Td className="text-right tabular-nums">{money(r.allocated_monthly_cost, costs.currency)}</Td>
                  <Td className="text-right font-medium tabular-nums">{money(r.allocated_project_cost, costs.currency)}</Td>
                  <Td className="text-right tabular-nums">{money(r.allocated_project_sale, costs.currency)}</Td>
                </tr>
              ))}
            </Table>
          ) : <EmptyLine>Aucun membre : le coût de l'équipe est calculé à partir des affectations.</EmptyLine>}
        </Section>
      )}

      <ConfirmDialog open={!!confirm} onOpenChange={(o) => !o && setConfirm(null)} pending={remove.isPending} destructive
        title={`Retirer ${confirm?.name ?? ""} du projet ?`} description="L'affectation au projet est supprimée ; le compte et l'historique sont conservés."
        confirmLabel="Retirer"
        onConfirm={() => confirm && remove.mutate({ resource: "project-member", id: confirm.id }, {
          onSuccess: (r) => { (r.messages?.length ? r.messages : ["Membre retiré du projet."]).forEach((m) => toast.success(m)); setConfirm(null); },
          onError: (e) => { toast.error(e.message); setConfirm(null); },
        })} />
    </div>
  );
}
