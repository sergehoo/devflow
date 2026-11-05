import { Navigate } from "react-router";
import { EmptyState, PageSkeleton } from "@/components/feedback/states";
import { useMe } from "@/features/auth/api";

/** « Identité & papier en-tête » : mêmes champs que WorkspaceBrandingView, dans le formulaire workspace. */
export function BrandingRedirect() {
  const { data: me, isPending } = useMe();
  if (isPending) return <PageSkeleton />;
  if (!me?.workspace) return <EmptyState title="Aucun workspace actif" />;
  return <Navigate replace to={`/workspaces/${me.workspace.id}/edit`} />;
}
