/** Formulaires Django (pont `/api/v1/forms/`) ouverts dans une boîte de dialogue depuis la fiche projet. */
import { useState } from "react";
import { toast } from "sonner";
import { LegacyForm } from "@/components/forms/LegacyForm";
import { Dialog } from "@/components/ui/dialog";
import { useInvalidateProject } from "./api";

export interface FormSpec {
  name: string;
  title: string;
  id?: number;
  query?: Record<string, string>;
  hidden?: string[];
  exclude?: string[];
  endpoint?: string;
  submitLabel?: string;
  /** Appelé après succès (après invalidation de la fiche). */
  onDone?: (result: { id: number; messages: string[] }) => void;
}

/**
 * Formulaire Django (pont `/api/v1/forms/`) dans une boîte de dialogue : création / modification
 * sans quitter la fiche, puis rafraîchissement de la fiche.
 *
 * `workspaceId` (workspace du projet) est transmis à chaque formulaire (`?workspace=`, validé par
 * Django) : la fiche peut afficher un projet hors du workspace courant, dont les vues Django
 * rejetteraient sinon le projet (choix invalide) ou l'objet (404).
 */
export function useFormDialog(projectId: number, workspaceId?: number) {
  const [spec, setSpec] = useState<FormSpec | null>(null);
  const invalidate = useInvalidateProject(projectId);
  const query = spec && workspaceId ? { ...spec.query, workspace: String(workspaceId) } : spec?.query;
  // Le workspace découle du projet : champ masqué (valeur initiale fournie par la vue Django).
  const hidden = workspaceId ? [...(spec?.hidden ?? []), "workspace"] : spec?.hidden;
  const element = (
    <Dialog open={!!spec} onOpenChange={(v) => !v && setSpec(null)} title={spec?.title ?? ""} className="sm:max-w-2xl">
      {spec && (
        <LegacyForm compact name={spec.name} id={spec.id} query={query} hidden={hidden} exclude={spec.exclude}
          endpoint={spec.endpoint} submitLabel={spec.submitLabel ?? "Enregistrer"} onCancel={() => setSpec(null)}
          onSuccess={(result) => {
            (result.messages?.length ? result.messages : ["Enregistré."]).forEach((m) => toast.success(m));
            const done = spec.onDone;
            setSpec(null);
            void invalidate();
            done?.(result);
          }} />
      )}
    </Dialog>
  );
  return { open: setSpec, element };
}
