import { KeyRound, UserRound } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { PageSkeleton } from "@/components/feedback/states";
import { LegacyForm } from "@/components/forms/LegacyForm";
import { PageHeader } from "@/components/layout/page";
import { Card } from "@/components/ui/card";
import { Avatar } from "@/components/ui/misc";
import { meQueryKey, useMe } from "@/features/auth/api";
import { WidgetHeader } from "@/features/dashboard/widgets";

/** Mon profil : mêmes formulaires et règles que /profile/ (UserProfileForm, DevFlowPasswordChangeForm). */
export function ProfilePage() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  if (!me) return <PageSkeleton />;
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Compte" title="Mon profil" description="Informations personnelles, préférences et sécurité du compte." />
      <Card className="flex flex-wrap items-center gap-4 p-5 sm:p-6">
        <Avatar name={me.full_name} src={me.avatar} className="size-16 text-lg" />
        <div className="min-w-0">
          <p className="text-lg font-semibold">{me.full_name}</p>
          <p className="text-sm text-muted-foreground">{me.email}</p>
          {me.workspace && <p className="text-xs text-muted-foreground">{me.workspace.name} · {me.workspace.role_label}</p>}
        </div>
      </Card>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Card className="p-5 sm:p-6">
          <WidgetHeader title={<span className="inline-flex items-center gap-2"><UserRound className="size-4" aria-hidden="true" />Informations</span>} />
          <div className="mt-4">
            <LegacyForm name="profile" compact onSuccess={() => { toast.success("Profil mis à jour."); void qc.invalidateQueries({ queryKey: meQueryKey }); }} />
          </div>
        </Card>
        <Card className="p-5 sm:p-6">
          <WidgetHeader title={<span className="inline-flex items-center gap-2"><KeyRound className="size-4" aria-hidden="true" />Mot de passe</span>} />
          <div className="mt-4">
            <LegacyForm name="password" compact submitLabel="Changer le mot de passe" onSuccess={() => toast.success("Mot de passe modifié : votre session reste active.")} />
          </div>
        </Card>
      </div>
    </div>
  );
}
