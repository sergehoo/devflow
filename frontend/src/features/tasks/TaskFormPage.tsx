import { useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { LegacyForm } from "@/components/forms/LegacyForm";
import { PageHeader } from "@/components/layout/page";
import { useInvalidateTasks } from "./api";

/** Création / modification via les vues Django TaskCreateView / TaskUpdateView (préremplissage ?project=&sprint=&parent=). */
export function TaskFormPage() {
  const params = useParams();
  const id = params.id ? Number(params.id) : undefined;
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const invalidate = useInvalidateTasks();
  const query = Object.fromEntries(["project", "sprint", "parent", "assignee", "backlog_item"].flatMap((k) => (search.get(k) ? [[k, search.get(k)!]] : [])));
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Tâches" title={id ? "Modifier la tâche" : "Nouvelle tâche"} />
      <LegacyForm
        name="task"
        id={id}
        query={query}
        submitLabel={id ? "Enregistrer les modifications" : "Créer la tâche"}
        onCancel={() => navigate(-1)}
        onSuccess={({ id: taskId, messages }) => {
          void invalidate();
          (messages.length ? messages : [id ? "Tâche mise à jour." : "Tâche créée."]).forEach((m) => toast.success(m));
          navigate(`/tasks/${taskId}`);
        }}
      />
    </div>
  );
}
