/**
 * Assistant d'import du classeur « Suivi Pôle Développement » :
 * 1 Fichier · 2 Analyse · 3 Prévisualisation · 4 Mapping · 5 Import · 6 Rapport.
 * L'analyse, le dédoublonnage, l'application et l'annulation sont faits par Django ;
 * l'écran ne fait que présenter les propositions et transmettre les décisions validées.
 */
import { ArrowLeft, ChevronDown, ChevronRight, FileSpreadsheet, FileUp, RefreshCw, Undo2 } from "lucide-react";
import { Fragment, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader, Pagination } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { EmptyLine, Pill, Section, Stat, StatGrid, Table, Td } from "@/features/projet/ui";
import type { Tone } from "@/features/projet/format";
import { formatDate, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ApiError } from "@/services/api";
import {
  useImportAction, useImportRecords, useTrackingImport, useTrackingImports, useUploadTracking,
  type AnalysisRow, type ImportAnalysis, type ImportDecisions, type ImportDetail, type ImportState,
} from "./api";
import { planOf } from "./decisions";
import { ImportMapping } from "./TrackingImportMapping";

const STATE: Record<ImportState, [string, Tone]> = {
  uploaded: ["Déposé", "muted"], analyzed: ["Analysé", "info"], applied: ["Importé", "success"], rolled_back: ["Annulé", "warning"],
};
const STEPS = ["Fichier", "Analyse", "Prévisualisation", "Mapping", "Import", "Rapport"] as const;
const SECTION = { projects: "Projets", tasks: "Tâches / activités" } as const;
const sectionLabel = (kind: string) => (SECTION as Record<string, string>)[kind] ?? kind;
const RECORD_FIELD: Record<string, string> = {
  row: "Ligne", project: "Projet", task: "Tâche", container: "Projet d'accueil", company: "Entreprise", member: "Responsable",
  stakeholder: "Interlocuteur", action_done: "Action menée (historique)", action_done_task: "Action menée (tâche terminée)",
  action_next: "Action à venir", alert: "Alerte / décision",
};
const RECORD_ACTION: Record<string, string> = { created: "Créé", updated: "Mis à jour", linked: "Rattaché", skipped: "Ignoré" };
const RAW: [string, string][] = [
  ["company", "Entreprise"], ["title", "Intitulé"], ["owner", "Porteur"], ["contact", "Interlocuteur"], ["done", "Actions menées"],
  ["next", "Actions à venir"], ["alert", "Alerte / décision"], ["start", "Date de début"], ["end", "Date de fin prévue"],
  ["progress", "Avancement"], ["status", "Statut"],
];

const StatePill = ({ state }: { state: ImportState }) => <Pill tone={STATE[state][1]}>{STATE[state][0]}</Pill>;
const message = (error: unknown) => (error instanceof Error ? error.message : "Une erreur est survenue.");

/** Erreurs de champ renvoyées par Django lors du dépôt (`{"workspace"|"file": message}`). */
function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.status !== 400 || !error.data || typeof error.data !== "object") return {};
  return Object.fromEntries(Object.entries(error.data as Record<string, unknown>).map(([k, v]) => [k, Array.isArray(v) ? v.join(" ") : String(v)]));
}

// ---------------------------------------------------------------------------
// Étape 1 — dépôt du classeur et imports précédents
// ---------------------------------------------------------------------------
export function TrackingImportsPage() {
  const navigate = useNavigate();
  const { data, isPending, isError, error, refetch } = useTrackingImports();
  const upload = useUploadTracking();
  const [workspace, setWorkspace] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const errors = fieldErrors(upload.error);
  const workspaceId = Number(workspace || data?.workspaces[0]?.id || 0);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!file || !workspaceId) return;
    upload.mutate({ workspace: workspaceId, file }, {
      onSuccess: (detail) => {
        toast.success("Classeur analysé : vérifiez les propositions avant l'import.");
        navigate(`/imports/tracking/${detail.id}`);
      },
    });
  };

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Pilotage · import" title="Importer le suivi Excel"
        description="Déposez le classeur « Suivi Pôle Développement » : DevFlow détecte les blocs Projets et Tâches, puis vous validez chaque correspondance avant l'import."
        actions={<Button variant="outline" asChild><Link to="/pilotage/suivi"><ArrowLeft />Suivi Pôle Développement</Link></Button>} />

      {isPending ? <PageSkeleton /> : isError ? <ErrorState message={error.message} onRetry={() => void refetch()} /> : (
        <>
          <Section title="1 · Déposer le classeur" description="Format .xlsx. Rien n'est créé à cette étape : le fichier est seulement analysé.">
            <form onSubmit={submit} className="grid gap-4 sm:grid-cols-[1fr_2fr_auto] sm:items-end">
              <Field id="tracking-workspace" label="Espace de travail" error={errors.workspace}>
                <Select id="tracking-workspace" value={String(workspaceId || "")} onChange={(e) => setWorkspace(e.target.value)}>
                  {data.workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </Select>
              </Field>
              <Field id="tracking-file" label="Classeur de suivi (.xlsx)" error={errors.file}>
                <Input id="tracking-file" type="file" required
                  accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </Field>
              <Button type="submit" disabled={!file || !workspaceId || upload.isPending}>
                <FileUp />{upload.isPending ? "Analyse…" : "Analyser le classeur"}
              </Button>
            </form>
            {upload.isError && Object.keys(errors).length === 0 && <p role="alert" className="mt-3 text-sm text-destructive">{message(upload.error)}</p>}
          </Section>

          <Section title="Imports précédents" count={data.results.length}>
            {data.results.length === 0 ? <EmptyLine>Aucun classeur de suivi importé pour le moment.</EmptyLine> : (
              <ul className="divide-y">
                {data.results.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
                    <FileSpreadsheet className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Link to={`/imports/tracking/${r.id}`} className="break-all font-medium hover:text-brand">{r.file_name || `Import n° ${r.id}`}</Link>
                        <StatePill state={r.state} />
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {[r.workspace.name, r.uploaded_by, formatDateTime(r.created_at),
                          r.stats.projects != null ? `${r.stats.projects} projet(s), ${r.stats.tasks ?? 0} activité(s)` : null].filter(Boolean).join(" · ")}
                      </p>
                    </div>
                    <Button variant="outline" size="sm" asChild><Link to={`/imports/tracking/${r.id}`}>Ouvrir</Link></Button>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Étapes 2 à 6 — assistant
// ---------------------------------------------------------------------------
function AnalysisStep({ analysis }: { analysis: ImportAnalysis }) {
  const { stats } = analysis;
  return (
    <div className="space-y-6">
      <StatGrid className="md:grid-cols-5">
        <Stat label="Projets" value={stats.projects} />
        <Stat label="Activités" value={stats.tasks} />
        <Stat label="Actions menées" value={stats.actions_done} />
        <Stat label="Actions à venir" value={stats.actions_next} />
        <Stat label="Alertes / décisions" value={stats.alerts} />
        <Stat label="Entreprises" value={stats.companies} />
        <Stat label="Responsables" value={stats.people} hint={stats.unresolved_people ? `${stats.unresolved_people} non résolu(s)` : "tous rapprochés"} />
        <Stat label="Ambiguïtés" value={stats.ambiguities} hint="valeurs du fichier conservées" />
        <Stat label="Avertissements" value={stats.warnings} />
      </StatGrid>

      <Section title="Blocs détectés" count={analysis.sections.length} description="Les deux sections du classeur sont repérées automatiquement à partir de leurs en-têtes.">
        {analysis.sections.length === 0 ? <EmptyLine>Aucun bloc reconnu dans ce classeur.</EmptyLine> : (
          <Table caption="Blocs détectés dans le classeur" head={["Bloc", "Feuille", "Titre", "En-tête", "Lignes de données", "Nombre"]}>
            {analysis.sections.map((s) => (
              <tr key={`${s.kind}-${s.header_row}`}>
                <Td className="font-medium">{sectionLabel(s.kind)}</Td>
                <Td>{s.sheet}</Td>
                <Td className="break-words">{s.title || "—"}</Td>
                <Td className="tabular-nums">ligne {s.header_row}</Td>
                <Td className="tabular-nums">{s.first_row ? `${s.first_row} à ${s.last_row}` : "—"}</Td>
                <Td className="tabular-nums">{s.rows}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Section>

      <Section title="Avertissements" count={analysis.warnings.length} description="Points relevés à la lecture du fichier. Aucune valeur n'a été corrigée d'office.">
        {analysis.warnings.length === 0 ? <EmptyLine>Aucun avertissement.</EmptyLine> : (
          <ul className="max-h-80 space-y-1.5 overflow-y-auto text-sm">
            {analysis.warnings.map((w, i) => (
              <li key={`${w.row}-${w.code}-${i}`} className="flex gap-2">
                <span className="shrink-0 tabular-nums text-muted-foreground">Ligne {w.line}</span>
                <span className="min-w-0 break-words">{w.message}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function PreviewRow({ row }: { row: AnalysisRow }) {
  const [open, setOpen] = useState(false);
  return (
    <Fragment>
      <tr>
        <Td className="w-9">
          <Button type="button" variant="ghost" size="icon" className="size-7" aria-expanded={open}
            aria-label={`${open ? "Masquer" : "Afficher"} le texte d'origine de la ligne ${row.row}`} onClick={() => setOpen(!open)}>
            {open ? <ChevronDown /> : <ChevronRight />}
          </Button>
        </Td>
        <Td className="tabular-nums">{row.row}</Td>
        <Td className="break-words">{row.companies.join(", ") || "—"}</Td>
        <Td className="max-w-[18rem] break-words font-medium">{row.title || "(sans intitulé)"}</Td>
        <Td className="break-words">{row.owners.join(", ") || "—"}</Td>
        <Td className="break-words">{row.contacts.join(", ") || "—"}</Td>
        <Td className="whitespace-nowrap">{row.start ? formatDate(row.start) : "—"}</Td>
        <Td className="whitespace-nowrap">{row.end ? formatDate(row.end) : "—"}</Td>
        <Td className="whitespace-nowrap tabular-nums">{row.progress == null ? (row.progress_raw || "—") : `${row.progress} %`}</Td>
        <Td>{row.status_raw || "—"}</Td>
        <Td className="whitespace-nowrap tabular-nums">{row.done.length} / {row.next.length} / {row.alerts.length}</Td>
      </tr>
      {open && (
        <tr className="bg-muted/40">
          <Td colSpan={11} className="px-4 py-4">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Texte d'origine (conservé avec l'import)</h4>
            <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              {RAW.filter(([key]) => row.raw[key]).map(([key, label]) => (
                <div key={key} className="min-w-0">
                  <dt className="text-xs text-muted-foreground">{label}</dt>
                  <dd className="whitespace-pre-wrap break-words">{row.raw[key]}</dd>
                </div>
              ))}
            </dl>
            {row.warnings.length > 0 && (
              <ul className="mt-3 space-y-1 text-xs text-warning">{row.warnings.map((w, i) => <li key={`${w.code}-${i}`}>{w.message}</li>)}</ul>
            )}
          </Td>
        </tr>
      )}
    </Fragment>
  );
}

function PreviewStep({ analysis }: { analysis: ImportAnalysis }) {
  return (
    <div className="space-y-6">
      {(["projects", "tasks"] as const).map((kind) => {
        const rows = analysis.rows.filter((r) => r.section === kind);
        return (
          <Section key={kind} title={SECTION[kind]} count={rows.length}
            description="Lecture du fichier, sans modification. Dépliez une ligne pour le texte d'origine.">
            {rows.length === 0 ? <EmptyLine>Aucune ligne dans ce bloc.</EmptyLine> : (
              <Table caption={`Prévisualisation du bloc ${SECTION[kind]}`} minWidth="min-w-[1080px]"
                head={["", "Ligne", "Entreprise", kind === "projects" ? "Projet" : "Tâche / activité", "Porteur", "Interlocuteur", "Début", "Fin prévue", "Avancement", "Statut", "Menées / à venir / alertes"]}>
                {rows.map((row) => <PreviewRow key={row.id} row={row} />)}
              </Table>
            )}
          </Section>
        );
      })}
    </div>
  );
}

const PLAN_ACTIONS: [keyof ReturnType<typeof planOf>["projects"], string][] = [
  ["create", "Créer"], ["link", "Rattacher"], ["update", "Mettre à jour"], ["skip", "Ignorer"],
];

function ApplyStep({ detail, analysis, decisions, locked, onApplied }: {
  detail: ImportDetail; analysis: ImportAnalysis; decisions: ImportDecisions; locked: boolean; onApplied: () => void;
}) {
  const apply = useImportAction(detail.id, "apply");
  const [confirm, setConfirm] = useState(false);
  const plan = planOf(analysis, decisions);
  const lines: [string, ReturnType<typeof planOf>["projects"]][] = [
    ["Projets", plan.projects], ["Activités", plan.tasks], ["Actions à venir", plan.items], ["Alertes / décisions", plan.alerts],
  ];
  return (
    <div className="space-y-6">
      <Section title="Ce que l'import va faire" description="Récapitulatif des décisions de l'étape Mapping. Un réimport du même fichier ne crée pas de doublons.">
        <Table caption="Récapitulatif de l'import" head={["Élément", ...PLAN_ACTIONS.map(([, label]) => label)]}>
          {lines.map(([label, counts]) => (
            <tr key={label}>
              <Td className="font-medium">{label}</Td>
              {PLAN_ACTIONS.map(([key]) => <Td key={key} className="tabular-nums">{counts[key]}</Td>)}
            </tr>
          ))}
        </Table>
        <ul className="mt-4 space-y-1.5 text-sm">
          <li>
            {plan.unresolved.length === 0 ? "Tous les porteurs sont rapprochés d'un utilisateur DevFlow."
              : `${plan.unresolved.length} porteur(s) non résolu(s), conservés par leur nom sans création de compte : ${plan.unresolved.join(", ")}.`}
          </li>
          <li>
            {plan.ambiguitiesKept === 0 ? "Aucune donnée ambiguë laissée en l'état."
              : `${plan.ambiguitiesKept} donnée(s) ambiguë(s) conservée(s) telle(s) que dans le fichier.`}
          </li>
          <li>{decisions.done_as_tasks ? "Les actions menées sont ajoutées à l'historique et créées comme tâches terminées." : "Les actions menées sont ajoutées à l'historique du projet."}</li>
        </ul>
      </Section>

      {locked ? (
        <p className="rounded-2xl bg-muted px-4 py-3 text-sm text-muted-foreground">
          Import appliqué le {detail.applied_at ? formatDateTime(detail.applied_at) : "—"}{detail.applied_by ? ` par ${detail.applied_by.name}` : ""}. Consultez le rapport.
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => setConfirm(true)} disabled={apply.isPending}>
            <FileUp />{apply.isPending ? "Import en cours…" : "Lancer l'import"}
          </Button>
          <p className="text-xs text-muted-foreground">Chaque élément créé est tracé (ligne source, texte d'origine) et l'import peut être annulé.</p>
        </div>
      )}
      {apply.isError && <p role="alert" className="text-sm text-destructive">{message(apply.error)}</p>}

      <ConfirmDialog open={confirm} onOpenChange={setConfirm} title="Lancer l'import ?" confirmLabel="Importer" pending={apply.isPending}
        description={`Les décisions validées seront appliquées dans l'espace « ${detail.workspace.name} ». Vous pourrez annuler l'import depuis le rapport.`}
        onConfirm={() => apply.mutate(decisions, {
          onSuccess: () => { setConfirm(false); toast.success("Import terminé."); onApplied(); },
          onError: (e) => { setConfirm(false); toast.error(message(e)); },
        })} />
    </div>
  );
}

function ReportStep({ detail }: { detail: ImportDetail }) {
  const rollback = useImportAction(detail.id, "rollback");
  const [confirm, setConfirm] = useState(false);
  const [page, setPage] = useState(1);
  const { report } = detail;
  const records = useImportRecords(detail.id, page, !!report);
  if (!report) return <EmptyLine>Le rapport sera disponible une fois l'import lancé.</EmptyLine>;
  const actions = [...new Set(Object.values(report.counts).flatMap((c) => Object.keys(c)))];
  const rolledBack = detail.state === "rolled_back";

  return (
    <div className="space-y-6">
      <div className={cn("rounded-2xl px-4 py-3 text-sm", rolledBack ? "bg-warning/10" : "bg-success/10")}>
        {rolledBack ? (
          <p>
            Import annulé le {detail.rolled_back_at ? formatDateTime(detail.rolled_back_at) : "—"}{detail.rolled_back_by ? ` par ${detail.rolled_back_by.name}` : ""}.
            {detail.rollback && ` ${detail.rollback.archived ?? 0} élément(s) archivé(s), ${detail.rollback.removed ?? 0} retiré(s), ${detail.rollback.restored ?? 0} restauré(s).`}
          </p>
        ) : (
          <p>
            Import appliqué le {detail.applied_at ? formatDateTime(detail.applied_at) : "—"}{detail.applied_by ? ` par ${detail.applied_by.name}` : ""} ·
            {" "}{report.records} opération(s) tracée(s).
          </p>
        )}
      </div>

      <Section title="Résultat" description="Nombre d'éléments par type et par action.">
        <Table caption="Résultat de l'import" head={["Élément", ...actions.map((a) => RECORD_ACTION[a] ?? a)]}>
          {Object.entries(report.counts).map(([field, counts]) => (
            <tr key={field}>
              <Td className="font-medium">{RECORD_FIELD[field] ?? field}</Td>
              {actions.map((a) => <Td key={a} className="tabular-nums">{counts[a] ?? 0}</Td>)}
            </tr>
          ))}
        </Table>
        <ul className="mt-4 space-y-1.5 text-sm">
          <li>
            {report.unresolved_members.length === 0 ? "Tous les porteurs sont rapprochés d'un utilisateur DevFlow."
              : `Porteurs non résolus (aucun compte créé) : ${report.unresolved_members.join(", ")}.`}
          </li>
          <li>{report.warnings} avertissement(s) relevé(s) à l'analyse.</li>
        </ul>
        {report.ambiguities_kept.length > 0 && (
          <div className="mt-4">
            <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Données ambiguës conservées telles quelles · {report.ambiguities_kept.length}</h4>
            <ul className="list-disc space-y-1 pl-5 text-sm">{report.ambiguities_kept.map((m, i) => <li key={i} className="break-words">{m}</li>)}</ul>
          </div>
        )}
      </Section>

      <Section title="Journal d'audit" count={records.data?.count} description="Provenance de chaque élément : bloc, ligne source et texte d'origine.">
        {records.isPending ? <Skeleton className="h-40" /> : records.isError ? <ErrorState message={records.error.message} onRetry={() => void records.refetch()} />
          : records.data.results.length === 0 ? <EmptyLine>Aucune opération enregistrée.</EmptyLine> : (
            <div className="space-y-3">
              <Table caption="Journal d'audit de l'import" minWidth="min-w-[760px]" head={["Bloc", "Ligne", "Élément", "Texte d'origine", "Action", "Cible"]}>
                {records.data.results.map((r) => (
                  <tr key={r.id} className={cn(r.rolled_back && "text-muted-foreground")}>
                    <Td>{sectionLabel(r.section)}</Td>
                    <Td className="tabular-nums">{r.row}</Td>
                    <Td>{RECORD_FIELD[r.field] ?? r.field}</Td>
                    <Td className="max-w-[24rem] whitespace-pre-wrap break-words">{r.text || "—"}</Td>
                    <Td>{r.action_label}{r.rolled_back && <Pill tone="warning" className="ml-2">Annulé</Pill>}</Td>
                    <Td className="whitespace-nowrap">{r.target_id ? `${r.target_model} n° ${r.target_id}` : "—"}</Td>
                  </tr>
                ))}
              </Table>
              <Pagination page={page} count={records.data.count} pageSize={100} onPage={setPage} />
            </div>
          )}
      </Section>

      <div className="flex flex-wrap items-center gap-3">
        <Button asChild><Link to="/pilotage/suivi">Ouvrir le suivi</Link></Button>
        {!rolledBack && (
          <Button variant="outline" onClick={() => setConfirm(true)} disabled={rollback.isPending}><Undo2 />Annuler l'import</Button>
        )}
      </div>

      <ConfirmDialog open={confirm} onOpenChange={setConfirm} destructive title="Annuler cet import ?" confirmLabel="Annuler l'import" pending={rollback.isPending}
        description="Les éléments créés par cet import sont archivés ou retirés et les valeurs mises à jour sont restaurées. Le journal d'audit est conservé."
        onConfirm={() => rollback.mutate(undefined, {
          onSuccess: () => { setConfirm(false); toast.success("Import annulé."); },
          onError: (e) => { setConfirm(false); toast.error(message(e)); },
        })} />
    </div>
  );
}

function Wizard({ detail }: { detail: ImportDetail }) {
  const { analysis } = detail;
  const [step, setStep] = useState(() => (detail.report ? 5 : 1));
  const [decisions, setDecisions] = useState<ImportDecisions>(() => detail.decisions ?? {});
  const analyze = useImportAction(detail.id, "analyze");
  const locked = detail.state === "applied";
  const reanalyze = () => analyze.mutate(undefined, {
    onSuccess: () => toast.success("Analyse relancée : les propositions ont été recalculées."),
    onError: (e) => toast.error(message(e)),
  });

  return (
    <div className="space-y-6">
      <nav aria-label="Étapes de l'import">
        <ol className="flex flex-wrap gap-2">
          {STEPS.map((label, i) => (
            <li key={label}>
              <button type="button" aria-current={step === i ? "step" : undefined} disabled={i > 0 && !analysis} onClick={() => setStep(i)}
                className={cn("flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors disabled:opacity-50",
                  step === i ? "border-primary bg-primary text-primary-foreground" : "bg-card hover:bg-muted")}>
                <span className="tabular-nums">{i + 1}</span>{label}
              </button>
            </li>
          ))}
        </ol>
      </nav>

      {step === 0 || !analysis ? (
        <Section title="Fichier" description="Provenance conservée avec chaque élément importé."
          actions={!locked && <Button variant="outline" size="sm" onClick={reanalyze} disabled={analyze.isPending}><RefreshCw />{analyze.isPending ? "Analyse…" : "Relancer l'analyse"}</Button>}>
          <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            {([
              ["Fichier", detail.file_name || `Import n° ${detail.id}`], ["Espace de travail", detail.workspace.name],
              ["Déposé par", detail.uploaded_by || "—"], ["Déposé le", formatDateTime(detail.created_at)],
              ["Analysé le", analysis ? formatDateTime(analysis.analyzed_at) : "Pas encore analysé"],
            ] as const).map(([label, value]) => (
              <div key={label} className="min-w-0">
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="break-words font-medium">{value}</dd>
              </div>
            ))}
          </dl>
          {!locked && <p className="mt-4 text-xs text-muted-foreground">Relancer l'analyse recalcule les propositions et efface les choix déjà faits dans l'assistant.</p>}
        </Section>
      ) : step === 1 ? <AnalysisStep analysis={analysis} />
        : step === 2 ? <PreviewStep analysis={analysis} />
        : step === 3 ? <ImportMapping detail={detail} analysis={analysis} decisions={decisions} setDecisions={setDecisions} locked={locked} />
        : step === 4 ? <ApplyStep detail={detail} analysis={analysis} decisions={decisions} locked={locked} onApplied={() => setStep(5)} />
        : <ReportStep detail={detail} />}

      <div className="flex justify-between gap-3">
        <Button variant="outline" disabled={step === 0} onClick={() => setStep(step - 1)}><ArrowLeft />Précédent</Button>
        {step < STEPS.length - 1 && <Button variant="outline" disabled={!analysis} onClick={() => setStep(step + 1)}>Suivant<ChevronRight /></Button>}
      </div>
    </div>
  );
}

export function TrackingImportWizardPage() {
  const id = Number(useParams().id);
  const { data, isPending, isError, error, refetch } = useTrackingImport(id);
  if (isPending) return <PageSkeleton />;
  if (isError) {
    return error instanceof ApiError && error.status === 404
      ? <EmptyState title="Import introuvable" description="Cet import n'existe pas ou n'est pas accessible." action={<Button size="sm" asChild><Link to="/imports/tracking">Retour aux imports</Link></Button>} />
      : <ErrorState message={error.message} onRetry={() => void refetch()} />;
  }
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Pilotage · import" title={data.file_name || `Import n° ${data.id}`}
        description={<span className="flex flex-wrap items-center gap-2"><StatePill state={data.state} />{data.workspace.name} · déposé le {formatDateTime(data.created_at)}</span>}
        actions={<Button variant="outline" asChild><Link to="/imports/tracking"><ArrowLeft />Imports du suivi</Link></Button>} />
      {/* Une nouvelle analyse ou un changement d'état repart des propositions du serveur. */}
      <Wizard key={`${data.state}-${data.analysis?.analyzed_at ?? ""}`} detail={data} />
    </div>
  );
}
