import { FileSpreadsheet } from "lucide-react";
import { useState } from "react";
import { Button, type ButtonProps } from "@/components/ui/button";
import { useMe } from "@/features/auth/api";
import { DownloadButton } from "@/features/meetings/DownloadButton";
import { can } from "@/lib/permissions";
import { trackingExportUrl, type TrackingFilters } from "./api";
import { ExportTrackingDialog, type Preselection } from "./ExportTrackingDialog";

/**
 * « Exporter le suivi Excel » : le classeur de suivi de la Direction, généré par Django
 * depuis les données DevFlow, limité au périmètre de l'utilisateur.
 * - avec `filters` (écran Pilotage) : téléchargement direct des lignes filtrées à l'écran ;
 * - sinon (Projets, tableau de bord) : fenêtre de configuration (projets cochés, période, mode),
 *   `preselect` proposant de reprendre les projets filtrés de la liste d'origine.
 * `gated` masque le bouton aux rôles sans accès au suivi (le contrôle réel reste côté Django).
 */
export function ExportTrackingButton({ filters, variant = "outline", gated = false, preselect }: {
  filters?: TrackingFilters; variant?: ButtonProps["variant"]; gated?: boolean; preselect?: Preselection;
}) {
  const { data: me } = useMe();
  const [open, setOpen] = useState(false);
  if (gated && !(can(me?.permissions, "project.view") || can(me?.permissions, "task.view_assigned"))) return null;
  if (filters) {
    return (
      <DownloadButton href={trackingExportUrl(filters)} filename="Suivi_Pole_Developpement.xlsx" variant={variant}>
        <FileSpreadsheet aria-hidden="true" />Exporter le suivi Excel
      </DownloadButton>
    );
  }
  return (
    <>
      <Button type="button" variant={variant} aria-haspopup="dialog" onClick={() => setOpen(true)}>
        <FileSpreadsheet aria-hidden="true" />Exporter le suivi Excel
      </Button>
      <ExportTrackingDialog open={open} onOpenChange={setOpen} preselect={preselect} />
    </>
  );
}
