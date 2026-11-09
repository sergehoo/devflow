import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { LegacyForm } from "@/components/forms/LegacyForm";
import { PageHeader } from "@/components/layout/page";
import { MEETINGS_KEY } from "./api";

const done = (messages: string[] | undefined, fallback: string) => (messages?.length ? messages : [fallback]).forEach((m) => toast.success(m));

/**
 * Planifier / modifier une réunion : formulaire Django `ProjectMeetingForm` via le pont
 * `forms/meeting` (champs et choix filtrés par workspace, invitation par défaut de tous
 * les membres à la création, synchronisation des participations et des revues projet).
 */
export function MeetingFormPage() {
  const params = useParams();
  const id = params.id ? Number(params.id) : undefined;
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const project = search.get("project");
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Réunions" title={id ? "Modifier la réunion" : "Planifier une réunion"}
        description="Astuce : commencez une ligne des notes par « Action : » pour qu'elle soit détectée par l'analyse IA." />
      <LegacyForm name="meeting" id={id} query={!id && project ? { project } : undefined} submitLabel={id ? "Enregistrer" : "Créer la réunion"}
        onCancel={() => navigate(-1)}
        onSuccess={({ id: newId, messages }) => {
          done(messages, id ? "Réunion mise à jour." : "Réunion enregistrée.");
          void qc.invalidateQueries({ queryKey: MEETINGS_KEY });
          navigate(`/meetings/${newId ?? id}`);
        }} />
    </div>
  );
}

/** Créer / modifier une série récurrente (`MeetingSeriesForm`, génération des occurrences à la création). */
export function SeriesFormPage() {
  const params = useParams();
  const id = params.id ? Number(params.id) : undefined;
  const navigate = useNavigate();
  const qc = useQueryClient();
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Réunions · Séries" title={id ? "Modifier la série" : "Nouvelle série récurrente"}
        description="Les occurrences sont générées automatiquement sur 60 jours glissants." />
      <LegacyForm name="meeting-series" id={id} submitLabel={id ? "Enregistrer" : "Créer la série"} onCancel={() => navigate(-1)}
        onSuccess={({ id: newId, messages }) => {
          done(messages, id ? "Série mise à jour." : "Série créée.");
          void qc.invalidateQueries({ queryKey: MEETINGS_KEY });
          navigate(`/meetings/series/${newId ?? id}`);
        }} />
    </div>
  );
}
