import { Download, Eye, FileText, FolderOpen, Upload } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { formatDateTime } from "@/lib/format";
import type { DocumentsTab as Data, ProjectDocument } from "../api";
import type { FormSpec } from "../formDialog";
import { ActionBar, EmptyLine, Pill, Section, Stat, StatGrid, Table, Td } from "../ui";

const IMAGE = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"]);
const TEXT = new Set(["txt", "csv", "html", "htm"]);
const OFFICE = new Set(["doc", "docx", "xls", "xlsx", "ppt", "pptx"]);

/**
 * Visionneuse intégrée (port de _document_modal.html) — fichiers servis par `/media/` protégé.
 * Sécurité : texte / HTML affichés dans une iframe `sandbox` sans `allow-scripts` (aucun script exécuté,
 * `allow-same-origin` seul pour transmettre la session au `/media/` protégé) ; les fichiers Office ne
 * sont plus envoyés à un visualiseur externe (l'URL protégée n'y est pas accessible) : ouverture / téléchargement.
 */
export function DocumentViewer({ doc, onClose }: { doc: ProjectDocument | null; onClose: () => void }) {
  const ext = doc?.ext ?? "";
  const url = doc?.url ?? "";
  const fallback = (title: string, text: string) => (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
      <FileText className="size-10 text-muted-foreground" aria-hidden="true" />
      <p className="font-semibold">{title}</p>
      <p className="max-w-md text-sm text-muted-foreground">{text}</p>
      <Button asChild><a href={url} target="_blank" rel="noopener noreferrer"><Download />Ouvrir / télécharger le document</a></Button>
    </div>
  );
  let body;
  if (!url) body = fallback("Document indisponible", "Aucun fichier n'est associé à cet import.");
  else if (IMAGE.has(ext)) body = <div className="flex h-full items-center justify-center p-4"><img src={url} alt={doc?.name ?? "Document"} className="max-h-full max-w-full rounded-xl object-contain" /></div>;
  else if (ext === "pdf") body = <iframe title={doc?.name ?? "Document PDF"} src={url} className="size-full bg-white" />;
  else if (TEXT.has(ext)) body = <iframe title={doc?.name ?? "Document texte"} src={url} sandbox="allow-same-origin" className="size-full bg-white" />;
  else if (OFFICE.has(ext)) body = fallback("Prévisualisation Office indisponible", "Les fichiers Word, Excel et PowerPoint s'ouvrent dans votre application bureautique.");
  else body = fallback("Prévisualisation non disponible", "Ce type de fichier ne peut pas être affiché dans la visionneuse intégrée.");
  return (
    <Dialog open={!!doc} onOpenChange={(v) => !v && onClose()} title={doc?.name ?? "Document"} description={doc ? `${doc.type_label} · ${doc.status_label}` : undefined}
      className="sm:max-w-5xl">
      <div className="h-[70vh] overflow-hidden rounded-2xl border bg-muted">{body}</div>
      {url && <div className="mt-3 flex justify-end"><Button variant="outline" asChild><a href={url} target="_blank" rel="noopener noreferrer"><Eye />Ouvrir dans un onglet</a></Button></div>}
    </Dialog>
  );
}

/** Onglet Documents : imports documentaires du projet (upload, lecture intégrée, téléchargement). */
export function DocumentsTab({ projectId, data, openForm }: { projectId: number; data: Data; openForm: (s: FormSpec) => void }) {
  const [viewing, setViewing] = useState<ProjectDocument | null>(null);
  const upload = () => openForm({
    name: "project-import", title: "Importer un document", query: { project: String(projectId) }, hidden: ["project", "status"], submitLabel: "Importer",
  });
  const s = data.summary;
  return (
    <div className="space-y-6">
      <ActionBar title="Documents projet" description="Lecture intégrée, consultation et import des fichiers du projet.">
        <Button size="sm" onClick={upload}><Upload />Importer un document</Button>
        <Button size="sm" variant="outline" asChild><Link to={`/m/project-import?project=${projectId}`}><FolderOpen />Voir tous les imports</Link></Button>
      </ActionBar>

      <StatGrid>
        <Stat label="Total documents" value={s.count} />
        <Stat label="En traitement" value={s.processing} />
        <Stat label="Traitement terminé" value={s.completed} />
        <Stat label="Échecs" value={<span className={s.failed ? "text-destructive" : undefined}>{s.failed}</span>} />
      </StatGrid>

      <Section title="Bibliothèque documentaire" description="Cliquez sur « Lire » pour ouvrir un document dans la visionneuse intégrée." count={data.documents.length}>
        {data.documents.length ? (
          <Table caption="Documents du projet" minWidth="min-w-[720px]" head={["Document", "Type", "Statut", "Déposé par", "Date", ""]}>
            {data.documents.map((d) => (
              <tr key={d.id} className="hover:bg-muted/40">
                <Td className="min-w-48">
                  <Link to={`/m/project-import/${d.id}`} className="block max-w-xs truncate font-medium hover:text-brand">{d.name}</Link>
                  {d.has_text && <span className="block text-xs text-muted-foreground">Texte extrait disponible</span>}
                  {d.error_message && <span className="block text-xs text-destructive">{d.error_message}</span>}
                </Td>
                <Td className="text-muted-foreground">{d.type_label}</Td>
                <Td><Pill tone={d.status === "COMPLETED" ? "success" : d.status === "FAILED" ? "danger" : d.status === "PROCESSING" ? "warning" : "muted"}>{d.status_label}</Pill></Td>
                <Td className="text-muted-foreground">{d.uploaded_by || "—"}</Td>
                <Td className="whitespace-nowrap text-muted-foreground">{formatDateTime(d.created_at)}</Td>
                <Td>
                  {d.url ? (
                    <div className="flex justify-end gap-1.5">
                      <Button size="sm" variant="outline" onClick={() => setViewing(d)} aria-label={`Lire ${d.name}`}><Eye />Lire</Button>
                      <Button size="sm" asChild><a href={d.url} download aria-label={`Télécharger ${d.name}`}><Download />Télécharger</a></Button>
                    </div>
                  ) : <Pill>Indisponible</Pill>}
                </Td>
              </tr>
            ))}
          </Table>
        ) : <EmptyLine>Aucun document projet.</EmptyLine>}
      </Section>

      <DocumentViewer doc={viewing} onClose={() => setViewing(null)} />
    </div>
  );
}
