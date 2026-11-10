import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { LegacyForm } from "@/components/forms/LegacyForm";
import { PageHeader } from "@/components/layout/page";

/** Création / modification via le formulaire Django `ProjectForm` (mêmes règles que l'interface classique). */
export function ProjectFormPage() {
  const params = useParams();
  const id = params.id ? Number(params.id) : undefined;
  const navigate = useNavigate();
  const qc = useQueryClient();
  // --- projet --- `?workspace=` (fiche d'un projet hors workspace courant) : validé par la vue Django.
  const workspace = useSearchParams()[0].get("workspace");
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Projets"
        title={id ? "Modifier le projet" : "Nouveau projet"}
        description={id ? undefined : "Les membres des équipes choisies sont ajoutés automatiquement ; la configuration de la méthodologie est appliquée à la création."}
      />
      <LegacyForm
        name="project"
        id={id}
        query={workspace ? { workspace } : undefined}
        submitLabel={id ? "Enregistrer les modifications" : "Créer le projet"}
        onCancel={() => navigate(-1)}
        onSuccess={({ id: projectId, messages }) => {
          void qc.invalidateQueries({ queryKey: ["projects"] });
          void qc.invalidateQueries({ queryKey: ["dashboard"] });
          messages.forEach((m) => toast.success(m));
          if (!messages.length) toast.success(id ? "Projet mis à jour." : "Projet créé.");
          navigate(`/projects/${projectId}`);
        }}
      />
    </div>
  );
}
