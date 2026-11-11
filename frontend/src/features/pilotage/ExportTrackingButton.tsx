import { FileSpreadsheet } from "lucide-react";
import type { ButtonProps } from "@/components/ui/button";
import { useMe } from "@/features/auth/api";
import { DownloadButton } from "@/features/meetings/DownloadButton";
import { can } from "@/lib/permissions";
import { trackingExportUrl, type TrackingFilters } from "./api";

/**
 * « Exporter le suivi Excel » : le classeur de suivi de la Direction, généré par Django
 * depuis les données DevFlow, limité au périmètre de l'utilisateur et aux filtres transmis.
 * `gated` masque le bouton aux rôles sans accès au suivi (le contrôle réel reste côté Django).
 */
export function ExportTrackingButton({ filters, variant = "outline", gated = false }: {
  filters?: TrackingFilters; variant?: ButtonProps["variant"]; gated?: boolean;
}) {
  const { data: me } = useMe();
  if (gated && !(can(me?.permissions, "project.view") || can(me?.permissions, "task.view_assigned"))) return null;
  return (
    <DownloadButton href={trackingExportUrl(filters)} filename="Suivi_Pole_Developpement.xlsx" variant={variant}>
      <FileSpreadsheet aria-hidden="true" />Exporter le suivi Excel
    </DownloadButton>
  );
}
