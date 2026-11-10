import { ArrowLeft, ExternalLink, FileText, FileUp, Loader2, Search, Sparkles, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { LegacyForm } from "@/components/forms/LegacyForm";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { Badge, Skeleton } from "@/components/ui/misc";
import { useMe } from "@/features/auth/api";
import { useDebouncedValue } from "@/lib/hooks";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useAnalyzeImport, useImport, useImports, type AnalyzeResult, type ImportDetail } from "./api";
import { COUNT_LABELS } from "./constants";
import { AIStatusNotice, Stat, StatusBadge } from "./shared";

const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg"]);

/** Dépôt d'un document : formulaire Django existant (ProjectDocumentImportCreateView via le pont). */
function UploadDialog({ projectId, onClose }: { projectId: string | null; onClose: () => void }) {
  const navigate = useNavigate();
  const { data: me } = useMe();
  const query: Record<string, string> = projectId ? { project: projectId } : me?.workspace ? { workspace: String(me.workspace.id) } : {};
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title="Importer un document projet"
      description="PDF ou Word (.docx) pour l'analyse IA. Rattachez-le à un projet existant, ou laissez vide pour créer un nouveau projet à partir du document.">
      <LegacyForm name="project-import" query={query} compact hidden={["status"]} submitLabel="Importer le document"
        onCancel={onClose}
        onSuccess={(r) => {
          toast.success("Document importé : lancez l'analyse IA pour en extraire la structure du projet.");
          navigate(`/imports/${r.id}`);
        }} />
    </Dialog>
  );
}

/** Liste des imports documentaires (recherche, filtres, statistiques) + dépôt. */
export function ImportsPage() {
  const [search, setSearch] = useSearchParams();
  const [q, setQ] = useState(search.get("q") ?? "");
  const debounced = useDebouncedValue(q);
  const params = { ...Object.fromEntries([...search].filter(([k]) => k !== "new")), q: debounced };
  const { data, isPending, isError, error, refetch } = useImports(params);
  const uploading = search.get("new") === "1";
  const set = (key: string, value: string) => setSearch((s) => {
    if (value) s.set(key, value); else s.delete(key);
    if (key !== "page") s.delete("page");
    return s;
  });
  const page = Number(search.get("page") ?? 1);
  const stats = data?.stats ?? {};
  /** Filtre workspace (comme la liste historique) dès que l'utilisateur en a plusieurs. */
  const workspaces = data?.workspaces ?? [];
  const multiWorkspace = workspaces.length > 1 || !!search.get("workspace");

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Projets · documents" title="Imports documentaires"
        description="Déposez un cahier des charges : l'IA en extrait la structure du projet (jalons, sprints, tâches) à valider avant création."
        actions={<>
          <Button variant="outline" asChild><Link to="/ai-proposals">Propositions IA</Link></Button>
          <Button onClick={() => set("new", "1")}><FileUp />Importer un document</Button>
        </>} />

      <section aria-label="Statistiques" className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Total" value={stats.total ?? "…"} />
        <Stat label="Uploadés" value={stats.uploaded ?? "…"} accent="text-warning" />
        <Stat label="En traitement" value={stats.processing ?? "…"} accent="text-info" />
        <Stat label="Terminés" value={stats.completed ?? "…"} accent="text-success" />
        <Stat label="Échecs" value={stats.failed ?? "…"} accent="text-destructive" />
      </section>

      <div className={cn("grid gap-3 sm:grid-cols-2", multiWorkspace ? "lg:grid-cols-[2fr_1fr_1fr_1fr]" : "lg:grid-cols-[2fr_1fr_1fr]")}>
        <div className="relative sm:col-span-2 lg:col-span-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden="true" />
          <Input type="search" className="pl-9" placeholder="Fichier, projet, contenu extrait…" aria-label="Rechercher un import"
            value={q} onChange={(e) => { setQ(e.target.value); set("page", ""); }} />
        </div>
        {multiWorkspace && (
          <Select aria-label="Workspace" value={search.get("workspace") ?? ""}
            onChange={(e) => setSearch((s) => {
              if (e.target.value) s.set("workspace", e.target.value); else s.delete("workspace");
              s.delete("project");
              s.delete("page");
              return s;
            })}>
            <option value="">Workspace : actif{data?.workspace ? ` (${data.workspace.name})` : ""}</option>
            {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </Select>
        )}
        <Select aria-label="Projet" value={search.get("project") ?? ""} onChange={(e) => set("project", e.target.value)}>
          <option value="">Projet : tous</option>
          {data?.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </Select>
        <Select aria-label="Statut" value={search.get("status") ?? ""} onChange={(e) => set("status", e.target.value)}>
          <option value="">Statut : tous</option>
          {data?.status_choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </Select>
      </div>

      {isPending ? <Skeleton className="h-72" /> : isError ? <ErrorState message={error.message} onRetry={() => void refetch()} />
        : data.results.length === 0 ? (
          <EmptyState title="Aucun document" description={q || search.get("status") || search.get("project") ? "Aucun import ne correspond aux filtres." : "Importez un premier document projet."}
            action={<Button size="sm" onClick={() => set("new", "1")}><FileUp />Importer un document</Button>} />
        ) : (
          <>
            <ul className="divide-y rounded-[22px] border border-transparent bg-card shadow-card dark:border-border">
              {data.results.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
                  <FileText className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link to={`/imports/${r.id}`} className="break-all font-medium hover:text-brand">{r.file_name || `Import n° ${r.id}`}</Link>
                      {r.file_ext && <Badge className="uppercase">{r.file_ext}</Badge>}
                      <StatusBadge status={r.status} label={r.status_label} />
                    </div>
                    {r.excerpt && (
                      <p className={cn("mt-1 line-clamp-2 break-words text-xs", r.has_error ? "text-destructive" : "text-muted-foreground")}>{r.excerpt}</p>
                    )}
                    <p className="mt-1 text-xs text-muted-foreground">
                      {r.project ? <Link to={`/projects/${r.project.id}`} className="hover:text-brand">{r.project.name}</Link> : "Sans projet"}
                      {` · ${[r.workspace ? `Workspace ${r.workspace}` : null, r.uploaded_by, formatDateTime(r.created_at)].filter(Boolean).join(" · ")}`}
                    </p>
                  </div>
                  <Button variant="outline" size="sm" asChild><Link to={`/imports/${r.id}`}>Ouvrir</Link></Button>
                </li>
              ))}
            </ul>
            {data.num_pages > 1 && (
              <nav aria-label="Pagination" className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
                <span>{data.count} document(s) · page {data.page} / {data.num_pages}</span>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => set("page", String(page - 1))}>Précédent</Button>
                  <Button variant="outline" size="sm" disabled={page >= data.num_pages} onClick={() => set("page", String(page + 1))}>Suivant</Button>
                </div>
              </nav>
            )}
          </>
        )}
      {uploading && <UploadDialog projectId={search.get("project")} onClose={() => set("new", "")} />}
    </div>
  );
}

function AnalyzeDialog({ doc, onClose, onDone }: { doc: ImportDetail; onClose: () => void; onDone: (r: AnalyzeResult) => void }) {
  const analyze = useAnalyzeImport(doc.id);
  const stem = doc.file_name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
  const [name, setName] = useState(stem);
  const [useAi, setUseAi] = useState(true);
  const [autoApply, setAutoApply] = useState(false);
  const run = () => analyze.mutate(
    { name: doc.project ? undefined : name.trim(), use_ai: useAi, auto_apply: !doc.project && autoApply },
    { onSuccess: (r) => { toast.success("Analyse terminée."); onDone(r); }, onError: (e) => toast.error(e.message) },
  );
  return (
    <Dialog open onOpenChange={(o) => !o && !analyze.isPending && onClose()} title="Analyser le document avec l'IA"
      description={doc.project
        ? `Une proposition de structure sera générée pour le projet « ${doc.project.name} » à partir du contenu du document.`
        : "Un nouveau projet sera créé à partir du document, avec sa structure proposée par l'IA."}>
      <div className="space-y-4">
        {!doc.project && (
          <Field id="analyze-name" label="Nom du projet à créer">
            <Input id="analyze-name" maxLength={160} value={name} onChange={(e) => setName(e.target.value)} disabled={analyze.isPending} />
          </Field>
        )}
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="size-4 accent-primary" checked={useAi} disabled={analyze.isPending} onChange={(e) => setUseAi(e.target.checked)} />
          Utiliser l'IA (sinon génération heuristique)
        </label>
        {!doc.project && (
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-0.5 size-4 accent-primary" checked={autoApply} disabled={analyze.isPending} onChange={(e) => setAutoApply(e.target.checked)} />
            <span>Appliquer automatiquement la structure<span className="block text-xs text-muted-foreground">Sinon, la proposition s'ouvre pour revue et validation avant création.</span></span>
          </label>
        )}
        {analyze.isPending && (
          <p aria-live="polite" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin text-brand" aria-hidden="true" />Extraction du texte puis structuration du projet…
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={analyze.isPending}>Annuler</Button>
          <Button onClick={run} disabled={analyze.isPending || (!doc.project && !name.trim())}><Sparkles />Lancer l'analyse</Button>
        </div>
      </div>
    </Dialog>
  );
}

function Preview({ doc }: { doc: ImportDetail }) {
  if (!doc.file_url) return <EmptyState title="Aucun fichier disponible" />;
  if (doc.file_ext === "pdf") {
    return <iframe title={`Aperçu de ${doc.file_name}`} src={doc.file_url} className="h-[70vh] w-full rounded-xl border bg-muted" />;
  }
  if (IMAGE_EXT.has(doc.file_ext)) return <img src={doc.file_url} alt={doc.file_name} className="mx-auto max-h-[70vh] rounded-xl object-contain" />;
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
      Aperçu non disponible pour ce format.
      <Button size="sm" variant="outline" asChild><a href={doc.file_url} target="_blank" rel="noopener noreferrer"><ExternalLink />Ouvrir le fichier</a></Button>
    </div>
  );
}

/** Fiche d'un document importé : aperçu, analyse IA, texte extrait, résultat structuré. */
export function ImportDetailPage() {
  const id = Number(useParams().id);
  const { data: doc, isPending, isError, error, refetch } = useImport(id);
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState<AnalyzeResult | null>(null);

  if (isPending) return <PageSkeleton />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;

  const counts = result ? Object.entries(result.counts).filter(([k, v]) => COUNT_LABELS[k] && typeof v === "number" && v > 0) : [];
  const info: [string, string][] = [
    ["Nom du fichier", doc.file_name || "—"], ["Type", doc.file_ext ? doc.file_ext.toUpperCase() : "—"],
    ["Workspace", doc.workspace || "—"], ["Déposé par", doc.uploaded_by || "—"],
    ["Déposé le", formatDateTime(doc.created_at)], ["Mis à jour le", formatDateTime(doc.updated_at)],
  ];
  const payload = doc.ai_payload ?? null;
  const summary = typeof payload?.summary === "string" ? payload.summary : "";

  return (
    <div className="space-y-6">
      {/* Les noms de fichiers n'ont pas d'espace : sans coupure forcée, le titre déborde à 375 px. */}
      <div className="min-w-0 [&_h1]:wrap-anywhere">
        <PageHeader eyebrow="Import documentaire" title={doc.file_name || `Import n° ${doc.id}`}
          description={
            <span className="flex flex-wrap items-center gap-2">
              <StatusBadge status={doc.status} label={doc.status_label} />
              {doc.project && <Link to={`/projects/${doc.project.id}`} className="text-sm hover:text-brand">{doc.project.name}</Link>}
              {doc.file_ext && <Badge className="uppercase">{doc.file_ext}</Badge>}
            </span>
          }
          actions={<>
            <Button variant="outline" asChild><Link to="/imports"><ArrowLeft />Retour à la liste</Link></Button>
            {doc.file_url && <Button variant="outline" asChild><a href={doc.file_url} target="_blank" rel="noopener noreferrer"><ExternalLink />Ouvrir le fichier</a></Button>}
            <Button disabled={!doc.can_analyze} onClick={() => setAnalyzing(true)}>
              <Sparkles />{doc.status === "COMPLETED" ? "Relancer l'analyse IA" : "Analyser avec l'IA"}
            </Button>
          </>} />
      </div>

      <AIStatusNotice ai={doc.ai} fallback="IA désactivée : après extraction du texte, la structure est proposée par l'assistant heuristique." />
      {doc.analysis_running ? (
        <p role="status" className="rounded-2xl border px-4 py-3 text-sm text-muted-foreground">Une analyse est en cours pour ce document.</p>
      ) : !doc.can_analyze && (
        <p role="note" className="rounded-2xl border px-4 py-3 text-sm text-muted-foreground">
          L'analyse IA est réservée aux responsables du projet, aux chefs de projet et aux propriétaires du workspace.
        </p>
      )}

      {result && (
        <Card className="border-success/30">
          <CardHeader><CardTitle>Analyse terminée</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              {result.applied ? "Structure créée dans le projet" : "Proposition prête à valider"} « {result.project.name} » ({result.used_provider})
              {counts.length ? ` : ${counts.map(([k, v]) => `${v} ${COUNT_LABELS[k]}`).join(", ")}` : ""}.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" asChild><Link to={`/ai-proposals/${result.proposal.id}`}>{result.applied ? "Voir la proposition appliquée" : "Revoir et valider la proposition"}</Link></Button>
              <Button size="sm" variant="outline" asChild><Link to={`/projects/${result.project.id}`}>Ouvrir le projet</Link></Button>
            </div>
          </CardContent>
        </Card>
      )}

      {doc.error_message && (
        <section role="alert" className="rounded-2xl border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <p className="flex items-center gap-2 font-semibold text-destructive"><TriangleAlert className="size-4" aria-hidden="true" />Erreur détectée</p>
          <p className="mt-1 whitespace-pre-line text-muted-foreground">{doc.error_message}</p>
        </section>
      )}

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="min-w-0 xl:col-span-2">
          <CardHeader><CardTitle>Aperçu</CardTitle></CardHeader>
          <CardContent><Preview doc={doc} /></CardContent>
        </Card>
        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader><CardTitle>Informations</CardTitle></CardHeader>
            <CardContent>
              <dl className="space-y-3 text-sm">
                {info.map(([k, v]) => <div key={k} className="flex justify-between gap-4"><dt className="text-muted-foreground">{k}</dt><dd className="min-w-0 break-all text-right font-medium">{v}</dd></div>)}
                <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Projet</dt>
                  <dd className="text-right font-medium">{doc.project ? <Link to={`/projects/${doc.project.id}`} className="hover:text-brand">{doc.project.name}</Link> : "—"}</dd></div>
              </dl>
            </CardContent>
          </Card>
          {doc.proposal && (
            <Card>
              <CardHeader><CardTitle>Proposition IA issue du document</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <StatusBadge status={doc.proposal.status} label={doc.proposal.status_label} />
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" asChild><Link to={`/ai-proposals/${doc.proposal.id}`}>Ouvrir la proposition</Link></Button>
                  <Button size="sm" variant="outline" asChild><Link to={`/projects/${doc.proposal.project_id}`}>Ouvrir le projet</Link></Button>
                </div>
              </CardContent>
            </Card>
          )}
          {doc.related.length > 0 && (
            <Card>
              <CardHeader><CardTitle>Imports liés</CardTitle></CardHeader>
              <CardContent>
                <ul className="space-y-2">
                  {doc.related.map((r) => (
                    <li key={r.id}>
                      <Link to={`/imports/${r.id}`} className="block rounded-xl border p-3 hover:border-primary">
                        <span className="block break-all text-sm font-medium">{r.file_name}</span>
                        <span className="text-xs text-muted-foreground">{r.status_label} · {formatDateTime(r.created_at)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {doc.extracted_text && (
        <Card>
          <CardHeader><CardTitle>Texte extrait</CardTitle></CardHeader>
          <CardContent>
            <div className="max-h-[520px] overflow-auto whitespace-pre-wrap break-words rounded-xl border bg-muted/40 p-4 text-sm text-muted-foreground">{doc.extracted_text}</div>
          </CardContent>
        </Card>
      )}
      {payload && (
        <Card>
          <CardHeader><CardTitle>Résultat IA structuré</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {summary && <p className="whitespace-pre-line text-sm text-muted-foreground">{summary}</p>}
            <details>
              <summary className="cursor-pointer text-sm font-semibold">Données brutes (JSON)</summary>
              <pre className="mt-2 max-h-[520px] overflow-auto rounded-xl border bg-muted/40 p-4 text-xs">{JSON.stringify(payload, null, 2)}</pre>
            </details>
          </CardContent>
        </Card>
      )}

      {analyzing && <AnalyzeDialog doc={doc} onClose={() => setAnalyzing(false)} onDone={(r) => { setResult(r); setAnalyzing(false); }} />}
    </div>
  );
}
