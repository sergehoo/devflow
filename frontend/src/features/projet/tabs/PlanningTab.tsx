import { Flag, ListPlus, MapIcon, Milestone, Rocket, Route } from "lucide-react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/format";
import type { Dependencies, PlanningTab as Data } from "../api";
import { severityTone } from "../format";
import type { FormSpec } from "../formDialog";
import { ActionBar, EmptyLine, Pill, ProgressBar, Section, Table, Td } from "../ui";

export function DependencyList({ deps }: { deps: Dependencies }) {
  if (!deps.items.length) return <EmptyLine>Aucune dépendance enregistrée.</EmptyLine>;
  return (
    <ul className="space-y-2">
      {deps.items.map((d) => (
        <li key={d.id} className="flex flex-col gap-1 rounded-xl border bg-muted/30 p-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0 text-sm">
            <Link to={`/tasks/${d.from_task.id}`} className="font-medium hover:text-brand">{d.from_task.title}</Link>
            <p className="text-muted-foreground">{d.type_label} → <Link to={`/tasks/${d.to_task.id}`} className="hover:text-brand">{d.to_task.title}</Link></p>
          </div>
          <Pill tone={d.type === "BLOCKS" ? "warning" : "muted"}>{d.type_label}</Pill>
        </li>
      ))}
      {deps.count > deps.items.length && <li className="text-xs text-muted-foreground">+ {deps.count - deps.items.length} autre(s) dépendance(s)</li>}
    </ul>
  );
}

/** Onglet Planification : jalons, sprints, releases, roadmap visuelle, backlog, dépendances, alertes IA. */
export function PlanningTab({ projectId, data, openForm }: { projectId: number; data: Data; openForm: (s: FormSpec) => void }) {
  const q = { project: String(projectId) };
  const create = (name: string, title: string) => openForm({ name, title, query: q, hidden: ["project"], submitLabel: "Créer" });
  return (
    <div className="space-y-6">
      <ActionBar title="Actions rapides · Planification" description="Créez, organisez et pilotez la feuille de route du projet.">
        <Button size="sm" variant="outline" onClick={() => create("roadmap", "Nouvelle roadmap")}><MapIcon />Nouvelle roadmap</Button>
        <Button size="sm" variant="outline" onClick={() => create("roadmap-item", "Élément de roadmap")}><Route />Élément roadmap</Button>
        <Button size="sm" onClick={() => create("sprint", "Nouveau sprint")}><Flag />Sprint</Button>
        <Button size="sm" variant="outline" onClick={() => create("milestone", "Nouveau jalon")}><Milestone />Jalon</Button>
        <Button size="sm" variant="outline" onClick={() => create("release", "Nouvelle release")}><Rocket />Release</Button>
        <Button size="sm" variant="outline" onClick={() => create("backlog-item", "Élément de backlog")}><ListPlus />Backlog</Button>
      </ActionBar>

      <div className="grid gap-6 xl:grid-cols-3">
        <Section title="Jalons" description="Étapes critiques du projet" count={data.stats.milestones_count}>
          {data.milestones.length ? (
            <ul className="space-y-3">
              {data.milestones.map((m) => (
                <li key={m.id} className="rounded-xl border bg-muted/30 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <Link to={`/m/milestone/${m.id}`} className="block truncate font-semibold hover:text-brand">{m.name}</Link>
                      <p className="text-sm text-muted-foreground">Échéance : {formatDate(m.due_date)}</p>
                      {m.owner && <p className="text-xs text-muted-foreground">Responsable : {m.owner}</p>}
                    </div>
                    <Pill>{m.status_label}</Pill>
                  </div>
                  <div className="mt-2 flex items-center justify-between text-xs"><span className="text-muted-foreground">Progression</span><span className="font-medium">{m.progress_percent} %</span></div>
                  <ProgressBar value={m.progress_percent} label={`Progression du jalon ${m.name}`} className="mt-1" />
                </li>
              ))}
            </ul>
          ) : <EmptyLine>Aucun jalon.</EmptyLine>}
        </Section>

        <Section title="Sprints" description="Cadence de production" count={data.stats.sprints_count}>
          {data.sprints.length ? (
            <ul className="space-y-3">
              {data.sprints.map((s) => (
                <li key={s.id} className="rounded-xl border bg-muted/30 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <Link to={`/m/sprint/${s.id}`} className="block truncate font-semibold hover:text-brand">{s.name}</Link>
                      <p className="text-sm text-muted-foreground">{formatDate(s.start_date)} → {formatDate(s.end_date)}</p>
                    </div>
                    <Pill tone={s.status === "ACTIVE" ? "primary" : "muted"}>{s.status_label}</Pill>
                  </div>
                  <dl className="mt-2 grid grid-cols-3 gap-2 text-center">
                    {([["Tâches", s.tasks_count], ["Backlog", s.backlog_count], ["Métriques", s.metrics_count]] as const).map(([k, v]) => (
                      <div key={k} className="rounded-lg bg-card p-1.5"><dt className="text-[10px] uppercase tracking-wide text-muted-foreground">{k}</dt><dd className="font-semibold tabular-nums">{v}</dd></div>
                    ))}
                  </dl>
                </li>
              ))}
            </ul>
          ) : <EmptyLine>Aucun sprint.</EmptyLine>}
        </Section>

        <Section title="Releases" description="Versions livrées" count={data.stats.releases_count}>
          {data.releases.length ? (
            <ul className="space-y-3">
              {data.releases.map((r) => (
                <li key={r.id} className="flex items-start justify-between gap-2 rounded-xl border bg-muted/30 p-3">
                  <div className="min-w-0">
                    <Link to={`/m/release/${r.id}`} className="block truncate font-semibold hover:text-brand">{r.name}</Link>
                    <p className="text-sm text-muted-foreground">Date : {formatDate(r.release_date)}</p>
                    {r.tag && <p className="text-xs text-muted-foreground">Tag : {r.tag}</p>}
                  </div>
                  <Pill tone={r.status === "RELEASED" ? "success" : "muted"}>{r.status_label}</Pill>
                </li>
              ))}
            </ul>
          ) : <EmptyLine>Aucune release.</EmptyLine>}
        </Section>
      </div>

      <Section title="Roadmap visuelle" description="Vue chronologique des grands éléments de livraison" count={data.stats.roadmap_items_count}>
        {data.roadmap_items.length ? (
          <ul className="space-y-3">
            {data.roadmap_items.map((i) => (
              <li key={i.id} className="flex flex-col gap-3 rounded-xl border bg-muted/30 p-3 xl:flex-row xl:items-center xl:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    {/* Couleur saisie par l'utilisateur (donnée), pas une couleur du thème. */}
                    <span aria-hidden="true" className="size-3 shrink-0 rounded-full bg-primary" style={i.color ? { backgroundColor: i.color } : undefined} />
                    <Link to={`/m/roadmap-item/${i.id}`} className="truncate font-semibold hover:text-brand">{i.title}</Link>
                    <Pill tone={i.status === "DONE" ? "success" : i.status === "AT_RISK" ? "danger" : i.status === "IN_PROGRESS" ? "primary" : "muted"}>{i.status_label}</Pill>
                    {i.roadmap && <Pill tone="primary">{i.roadmap}</Pill>}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {formatDate(i.start_date)} → {formatDate(i.end_date)} · {i.duration_days} jour(s){i.milestone ? ` · Jalon : ${i.milestone}` : ""}
                  </p>
                </div>
                <div className="w-full xl:max-w-md">
                  <div role="img" aria-label={`Avancement estimé ${i.bar_percent} %`} className="h-3 overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${i.bar_percent}%`, ...(i.color ? { backgroundColor: i.color } : {}) }} />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ) : <EmptyLine>Aucun élément de roadmap.</EmptyLine>}
      </Section>

      <Section title="Backlog" description="Éléments de planification et de cadrage" count={data.stats.backlog_count}
        actions={<Button size="sm" variant="ghost" asChild><Link to={`/m/backlog-item?project=${projectId}`}>Voir tout</Link></Button>}>
        {data.backlog.length ? (
          <Table caption="Backlog du projet" head={["Titre", "Type", "Sprint", "Story points", "Rapporteur"]}>
            {data.backlog.map((b) => (
              <tr key={b.id} className="hover:bg-muted/40">
                <Td><Link to={`/m/backlog-item/${b.id}`} className="font-medium hover:text-brand">{b.title}</Link></Td>
                <Td className="text-muted-foreground">{b.item_type_label}</Td>
                <Td className="text-muted-foreground">{b.sprint || "—"}</Td>
                <Td className="tabular-nums">{b.story_points}</Td>
                <Td className="text-muted-foreground">{b.reporter || "—"}</Td>
              </tr>
            ))}
          </Table>
        ) : <EmptyLine>Aucun élément de backlog.</EmptyLine>}
      </Section>

      <div className="grid gap-6 xl:grid-cols-2">
        <Section title="Dépendances" description="Liens critiques entre tâches" count={data.dependencies.count}>
          <DependencyList deps={data.dependencies} />
        </Section>
        <Section title="Alertes IA planning" description="Signaux faibles détectés (livraison, risque, charge, alertes)">
          {data.ai_alerts.length ? (
            <ul className="space-y-3">
              {data.ai_alerts.map((a) => (
                <li key={a.id} className="rounded-xl border bg-muted/30 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <Link to={`/m/ai-insight/${a.id}`} className="font-semibold hover:text-brand">{a.title}</Link>
                    <Pill tone={severityTone(a.severity)}>{a.severity_label}</Pill>
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">{a.summary}</p>
                  {a.recommendation && <p className="mt-2 rounded-lg bg-card p-2 text-xs text-muted-foreground"><span className="font-semibold text-foreground">Recommandation : </span>{a.recommendation}</p>}
                </li>
              ))}
            </ul>
          ) : <EmptyLine>Aucune alerte IA active.</EmptyLine>}
        </Section>
      </div>
    </div>
  );
}
