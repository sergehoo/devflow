/**
 * Assistant d'import du suivi › étape « Mapping ».
 * Chaque proposition de l'analyse (entreprise, responsable, statut, ligne, action, alerte)
 * peut être créée, rattachée, mise à jour ou ignorée. Les ambiguïtés gardent la valeur du
 * fichier tant que l'utilisateur ne tranche pas ; aucun compte utilisateur n'est créé.
 */
import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState, type Dispatch, type SetStateAction } from "react";
import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/input";
import { Pill, Section, Table, Td } from "@/features/projet/ui";
import { formatDate } from "@/lib/format";
import { useDebouncedValue } from "@/lib/hooks";
import {
  useImportTaskSearch, type AnalysisRow, type ImportAnalysis, type ImportDecisions, type ImportDetail, type RowAction,
} from "./api";
import { ambiguityValue, chosen, withPatch, type Group } from "./decisions";

export interface MappingProps {
  detail: ImportDetail;
  analysis: ImportAnalysis;
  decisions: ImportDecisions;
  setDecisions: Dispatch<SetStateAction<ImportDecisions>>;
  locked: boolean;
}

const ROLE: Record<string, string> = { PORTEUR: "Porteur", INTERLOCUTEUR: "Interlocuteur" };
const FIELD: Record<string, string> = {
  company: "Entreprise", title: "Intitulé", owner: "Porteur", contact: "Interlocuteur", done: "Actions menées", next: "Actions à venir",
  alert: "Alerte / décision", start: "Date de début", end: "Date de fin prévue", progress: "Avancement", status: "Statut",
};
const number = (value: string) => (value ? Number(value) : null);

/** Recherche d'une tâche existante de l'espace de travail (rattachement). */
function TaskPicker({ importId, value, label, onPick }: { importId: number; value: number | null; label: string; onPick: (id: number | null) => void }) {
  const [q, setQ] = useState("");
  const debounced = useDebouncedValue(q);
  const { data, isFetching } = useImportTaskSearch(importId, debounced);
  return (
    <div className="space-y-1.5">
      <Input type="search" aria-label={`Rechercher une tâche pour ${label}`} placeholder="Rechercher une tâche existante…" value={q} onChange={(e) => setQ(e.target.value)} />
      {debounced.trim().length >= 2 && (
        <Select aria-label={`Tâche cible pour ${label}`} value={value ?? ""} onChange={(e) => onPick(number(e.target.value))}>
          <option value="">{isFetching ? "Recherche…" : data?.results.length ? "Choisir une tâche" : "Aucune tâche trouvée"}</option>
          {data?.results.map((t) => <option key={t.id} value={t.id}>{t.title} — {t.project}</option>)}
        </Select>
      )}
      <p className="text-xs text-muted-foreground">{value ? `Tâche cible : n° ${value}` : "Aucune tâche cible choisie."}</p>
    </div>
  );
}

function RowItems({ row, importId, detail, decisions, patch }: {
  row: AnalysisRow; importId: number; detail: ImportDetail; decisions: ImportDecisions; patch: (group: Group, key: string, value: object) => void;
}) {
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <div className="min-w-0">
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Actions à venir · {row.next.length}</h4>
        {row.next.length === 0 ? <p className="text-sm text-muted-foreground">Aucune action à venir sur cette ligne.</p> : (
          <ul className="space-y-3">
            {row.next.map((item) => {
              const choice = chosen(decisions, "items", item.id, item.default);
              return (
                <li key={item.id} className="space-y-1.5 rounded-xl border p-3">
                  <p className="break-words text-sm">{item.text}{item.due && <span className="ml-1.5 text-xs text-muted-foreground">échéance {formatDate(item.due)}</span>}</p>
                  <Select aria-label={`Action pour « ${item.text} »`} value={choice.action} onChange={(e) => patch("items", item.id, { action: e.target.value })}>
                    <option value="create">Créer comme tâche</option>
                    <option value="link">Rattacher à une tâche existante</option>
                    <option value="skip">Ignorer</option>
                  </Select>
                  {choice.action === "link" && (
                    <TaskPicker importId={importId} label={item.text} value={choice.target_id} onPick={(id) => patch("items", item.id, { target_id: id })} />
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <div className="min-w-0">
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Alertes / décisions · {row.alerts.length}</h4>
        {row.alerts.length === 0 ? <p className="text-sm text-muted-foreground">Aucune alerte sur cette ligne.</p> : (
          <ul className="space-y-3">
            {row.alerts.map((alert) => {
              const choice = chosen(decisions, "alerts", alert.id, alert.default);
              return (
                <li key={alert.id} className="space-y-1.5 rounded-xl border p-3">
                  <p className="break-words text-sm">{alert.text}</p>
                  <div className="grid gap-2 sm:grid-cols-3">
                    <Select aria-label={`Action pour l'alerte « ${alert.text} »`} value={choice.action} onChange={(e) => patch("alerts", alert.id, { action: e.target.value })}>
                      <option value="create">Créer</option>
                      {alert.match && <option value="link">Rattacher à l'existant</option>}
                      <option value="skip">Ignorer</option>
                    </Select>
                    <Select aria-label={`Type de l'alerte « ${alert.text} »`} value={choice.kind} disabled={choice.action !== "create"}
                      onChange={(e) => patch("alerts", alert.id, { kind: e.target.value })}>
                      {detail.options.alert_kinds.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                    </Select>
                    <Select aria-label={`Niveau de l'alerte « ${alert.text} »`} value={choice.severity} disabled={choice.action !== "create" || choice.kind === "DECISION"}
                      onChange={(e) => patch("alerts", alert.id, { severity: e.target.value })}>
                      {detail.options.severities.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                    </Select>
                  </div>
                  <p className="text-xs text-muted-foreground">Classement proposé par règles, à valider.</p>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

export function ImportMapping({ detail, analysis, decisions, setDecisions, locked }: MappingProps) {
  const [open, setOpen] = useState<string | null>(null);
  const { options } = detail;
  const patch = (group: Group, key: string, value: object) => setDecisions((d) => withPatch(d, group, key, value));
  const container = { ...analysis.container.default, ...decisions.container };
  const setContainer = (value: Partial<NonNullable<ImportDecisions["container"]>>) =>
    setDecisions((d) => ({ ...d, container: { ...analysis.container.default, ...d.container, ...value } }));
  const companyLabels = options.labels.filter((l) => l.kind === "COMPANY" || analysis.companies.some((c) => c.match?.id === l.id));
  const hasTasks = analysis.rows.some((r) => r.section === "tasks");

  return (
    <fieldset disabled={locked} className="min-w-0 space-y-6">
      <legend className="sr-only">Correspondances de l'import</legend>
      {locked && <p className="rounded-2xl bg-muted px-4 py-3 text-sm text-muted-foreground">Import appliqué : les correspondances sont figées. Annulez l'import pour les modifier.</p>}

      <Section title="Responsables" count={analysis.people.length}
        description="Rapprochement avec les comptes DevFlow existants. Aucun compte n'est créé : un nom non résolu est conservé tel quel et signalé.">
        <Table caption="Responsables du fichier" head={["Nom dans le fichier", "Rôle", "Lignes", "Utilisateur DevFlow"]}>
          {analysis.people.map((p) => {
            const userId = chosen(decisions, "people", p.key, p.default).user_id;
            const others = options.users.filter((u) => !p.candidates.some((c) => c.id === u.id));
            return (
              <tr key={p.key}>
                <Td className="font-medium">
                  {p.name}
                  {userId == null && p.roles.includes("PORTEUR") && <Pill tone="warning" className="ml-2">Non résolu</Pill>}
                </Td>
                <Td>{p.roles.map((r) => ROLE[r] ?? r).join(", ")}</Td>
                <Td className="tabular-nums">{p.rows.length}</Td>
                <Td>
                  <Select aria-label={`Utilisateur DevFlow pour ${p.name}`} value={userId ?? ""} onChange={(e) => patch("people", p.key, { user_id: number(e.target.value) })}>
                    <option value="">Non résolu (nom conservé)</option>
                    {p.candidates.length > 0 && (
                      <optgroup label="Correspondances possibles">{p.candidates.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</optgroup>
                    )}
                    <optgroup label="Membres de l'espace">{others.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</optgroup>
                  </Select>
                </Td>
              </tr>
            );
          })}
        </Table>
      </Section>

      <Section title="Entreprises" count={analysis.companies.length} description="Chaque entreprise devient une étiquette « entreprise » de l'espace de travail, sans doublon.">
        <Table caption="Entreprises du fichier" head={["Entreprise", "Lignes", "Décision"]}>
          {analysis.companies.map((c) => {
            const choice = chosen(decisions, "companies", c.key, c.default);
            return (
              <tr key={c.key}>
                <Td className="font-medium">{c.name}{c.ambiguous && <Pill tone="warning" className="ml-2">Plusieurs entreprises ?</Pill>}</Td>
                <Td className="tabular-nums">{c.rows.length}</Td>
                <Td>
                  <Select aria-label={`Décision pour l'entreprise ${c.name}`} value={choice.action === "link" && choice.label_id ? String(choice.label_id) : "create"}
                    onChange={(e) => patch("companies", c.key, e.target.value === "create" ? { action: "create", label_id: null } : { action: "link", label_id: Number(e.target.value) })}>
                    <option value="create">Créer « {c.name} »</option>
                    {companyLabels.map((l) => <option key={l.id} value={l.id}>Rattacher à « {l.name} »</option>)}
                  </Select>
                </Td>
              </tr>
            );
          })}
        </Table>
      </Section>

      <Section title="Statuts" count={analysis.statuses.length} description="Correspondance entre les statuts du fichier et ceux de DevFlow.">
        <Table caption="Statuts du fichier" head={["Statut dans le fichier", "Lignes", "Statut projet", "Statut tâche"]}>
          {analysis.statuses.map((s) => {
            const choice = chosen(decisions, "statuses", s.key, s.default);
            return (
              <tr key={s.key}>
                <Td className="font-medium">{s.raw || "(vide)"}{!s.known && <Pill tone="warning" className="ml-2">Inconnu</Pill>}</Td>
                <Td className="tabular-nums">{s.rows}</Td>
                <Td>
                  <Select aria-label={`Statut projet pour ${s.raw || "vide"}`} value={choice.project ?? ""} onChange={(e) => patch("statuses", s.key, { project: e.target.value || null })}>
                    <option value="">Statut par défaut</option>
                    {options.project_statuses.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </Select>
                </Td>
                <Td>
                  <Select aria-label={`Statut tâche pour ${s.raw || "vide"}`} value={choice.task ?? ""} onChange={(e) => patch("statuses", s.key, { task: e.target.value || null })}>
                    <option value="">Statut par défaut</option>
                    {options.task_statuses.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </Select>
                </Td>
              </tr>
            );
          })}
        </Table>
      </Section>

      {analysis.ambiguities.length > 0 && (
        <Section title="Données ambiguës" count={analysis.ambiguities.length}
          description="La valeur du fichier est conservée telle quelle tant que vous ne choisissez pas une autre option.">
          <ul className="space-y-3">
            {analysis.ambiguities.map((a) => {
              const suggestion = a.suggestion == null ? null : a.options.find((o) => o.value === a.suggestion);
              return (
                <li key={a.id} className="grid gap-2 rounded-xl border p-3 sm:grid-cols-[1fr_16rem] sm:items-center">
                  <div className="min-w-0 text-sm">
                    <p className="break-words">{a.message}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      Ligne {a.line} · {FIELD[a.field] ?? a.field}{suggestion ? ` · suggestion non appliquée : ${suggestion.label}` : ""}
                    </p>
                  </div>
                  <Select aria-label={`Choix pour : ${a.message}`} value={JSON.stringify(ambiguityValue(decisions, a))}
                    onChange={(e) => setDecisions((d) => ({ ...d, ambiguities: { ...d.ambiguities, [a.id]: JSON.parse(e.target.value) as string | number | null } }))}>
                    {a.options.map((o) => <option key={JSON.stringify(o.value)} value={JSON.stringify(o.value)}>{o.label}</option>)}
                  </Select>
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      {hasTasks && (
        <Section title="Projet d'accueil des activités" description="Les lignes du bloc « Tâches » sont créées comme tâches de ce projet (sauf choix contraire par ligne).">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label htmlFor="container-mode">Projet</Label>
              <Select id="container-mode" value={container.mode} onChange={(e) => setContainer({ mode: e.target.value as "existing" | "create" })}>
                <option value="existing">Utiliser un projet existant</option>
                <option value="create">Créer le projet</option>
              </Select>
            </div>
            {container.mode === "existing" ? (
              <div>
                <Label htmlFor="container-project">Projet existant</Label>
                <Select id="container-project" value={container.project_id ?? ""} onChange={(e) => setContainer({ project_id: number(e.target.value) })}>
                  <option value="">Choisir un projet</option>
                  {options.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </Select>
              </div>
            ) : (
              <div>
                <Label htmlFor="container-name">Nom du projet</Label>
                <Input id="container-name" value={container.name ?? ""} maxLength={160} onChange={(e) => setContainer({ name: e.target.value })} />
              </div>
            )}
          </div>
        </Section>
      )}

      <Section title="Lignes du fichier" count={analysis.rows.length}
        description="Pour chaque ligne : créer, rattacher à l'existant sans le modifier, mettre à jour l'existant ou ignorer. Dépliez une ligne pour ses actions et alertes.">
        <Table caption="Décisions par ligne" minWidth="min-w-[860px]" head={["", "Ligne", "Intitulé", "Existant dans DevFlow", "Décision", "Cible"]}>
          {analysis.rows.map((row) => {
            const choice = chosen(decisions, "rows", row.id, row.default);
            const isProject = row.section === "projects";
            const expanded = open === row.id;
            const title = row.title || "(sans intitulé)";
            return (
              <Fragment key={row.id}>
                <tr>
                  <Td className="w-9">
                    <Button type="button" variant="ghost" size="icon" className="size-7" aria-expanded={expanded}
                      aria-label={`${expanded ? "Masquer" : "Afficher"} les actions et alertes de la ligne ${row.row}`} onClick={() => setOpen(expanded ? null : row.id)}>
                      {expanded ? <ChevronDown /> : <ChevronRight />}
                    </Button>
                  </Td>
                  <Td className="whitespace-nowrap tabular-nums">{row.row} · {isProject ? "Projet" : "Activité"}</Td>
                  <Td className="max-w-[20rem] break-words font-medium">{title}</Td>
                  <Td>{row.match ? <>{row.match.name}{row.match.archived && <Pill tone="warning" className="ml-2">Archivé</Pill>}</> : <span className="text-muted-foreground">Aucun</span>}</Td>
                  <Td>
                    <Select aria-label={`Décision pour la ligne ${row.row}`} value={choice.action} disabled={!row.title}
                      onChange={(e) => patch("rows", row.id, { action: e.target.value as RowAction })}>
                      <option value="create">Créer</option>
                      <option value="link">Rattacher</option>
                      <option value="update">Mettre à jour</option>
                      <option value="skip">Ignorer</option>
                    </Select>
                  </Td>
                  <Td className="min-w-52">
                    {choice.action === "skip" ? <span className="text-muted-foreground">—</span>
                      : choice.action === "create" ? (isProject ? <span className="text-muted-foreground">Nouveau projet</span> : (
                        <Select aria-label={`Projet de la ligne ${row.row}`} value={choice.project_id ?? ""} onChange={(e) => patch("rows", row.id, { project_id: number(e.target.value) })}>
                          <option value="">Projet d'accueil</option>
                          {options.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                        </Select>
                      )) : isProject ? (
                        <Select aria-label={`Projet cible de la ligne ${row.row}`} value={choice.target_id ?? ""} onChange={(e) => patch("rows", row.id, { target_id: number(e.target.value) })}>
                          <option value="">Choisir un projet</option>
                          {row.match?.archived && <option value={row.match.id}>{row.match.name} (archivé)</option>}
                          {options.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                        </Select>
                      ) : <TaskPicker importId={detail.id} label={title} value={choice.target_id} onPick={(id) => patch("rows", row.id, { target_id: id })} />}
                  </Td>
                </tr>
                {expanded && (
                  <tr className="bg-muted/40">
                    <Td colSpan={6} className="px-4 py-4">
                      {choice.action === "skip"
                        ? <p className="text-sm text-muted-foreground">Ligne ignorée : ses actions et alertes ne seront pas importées.</p>
                        : <RowItems row={row} importId={detail.id} detail={detail} decisions={decisions} patch={patch} />}
                    </Td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </Table>
      </Section>

      <label className="flex items-start gap-3 rounded-2xl border bg-card p-4 text-sm">
        <input type="checkbox" className="mt-0.5 size-4 accent-primary" checked={!!decisions.done_as_tasks}
          onChange={(e) => setDecisions((d) => ({ ...d, done_as_tasks: e.target.checked }))} />
        <span>
          <span className="font-medium">Créer aussi les actions menées comme tâches terminées</span>
          <span className="mt-0.5 block text-xs text-muted-foreground">Par défaut, les actions menées alimentent uniquement l'historique du projet.</span>
        </span>
      </label>
    </fieldset>
  );
}
