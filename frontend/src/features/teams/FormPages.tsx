import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { LegacyForm } from "@/components/forms/LegacyForm";
import { PageHeader } from "@/components/layout/page";

/** Formulaires Django : TeamCreate/UpdateView (équipe) et TeamMembershipCreate (intégration) / UpdateView (membre). */
function FormPage({ kind }: { kind: "team" | "member" }) {
  const params = useParams();
  const id = params.id ? Number(params.id) : undefined;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const title = kind === "team" ? (id ? "Modifier l'équipe" : "Nouvelle équipe") : (id ? "Modifier le membre" : "Intégrer un collaborateur");
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Organisation" title={title}
        description={kind === "member" && !id ? "Crée le compte, l'adhésion au workspace et envoie l'invitation d'activation." : undefined} />
      <LegacyForm name={kind} id={id} onCancel={() => navigate(-1)}
        onSuccess={({ id: objId, messages }) => {
          void qc.invalidateQueries({ queryKey: ["teams"] });
          (messages.length ? messages : ["Enregistré."]).forEach((m) => toast.success(m));
          navigate(kind === "team" ? `/teams/${objId}` : "/members");
        }} />
    </div>
  );
}

export const TeamFormPage = () => <FormPage kind="team" />;
export const MemberFormPage = () => <FormPage kind="member" />;
