import { Loader2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";
import { Button, type ButtonProps } from "@/components/ui/button";
import { legacyUrl } from "@/lib/utils";

export const DOWNLOAD_ERROR = "Le document n'a pas pu être généré. Réessayez plus tard ; si le problème persiste, contactez l'administrateur.";

function filenameFrom(res: Response): string | null {
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(res.headers.get("Content-Disposition") ?? "");
  return m?.[1] ? decodeURIComponent(m[1]) : null;
}

/**
 * Export Django (Word / PDF) téléchargé sans quitter React. En cas d'échec, la vue
 * historique redirige vers son ancienne page avec un message : on reste ici et on
 * affiche l'erreur.
 */
export function DownloadButton({ href, filename, children, variant = "outline", size }: {
  href: string; filename: string; children: ReactNode; variant?: ButtonProps["variant"]; size?: ButtonProps["size"];
}) {
  const [pending, setPending] = useState(false);
  const download = async () => {
    setPending(true);
    try {
      // Les exports de l'API (/api/…) passent par la même origine que le reste du client HTTP.
      const res = await fetch(href.startsWith("/api/") ? href : legacyUrl(href), { credentials: "include", redirect: "manual" });
      const type = res.headers.get("Content-Type") ?? "";
      if (!res.ok || res.type === "opaqueredirect" || type.startsWith("text/html")) throw new Error(DOWNLOAD_ERROR);
      const url = URL.createObjectURL(await res.blob());
      const link = Object.assign(document.createElement("a"), { href: url, download: filenameFrom(res) ?? filename });
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch {
      toast.error(DOWNLOAD_ERROR);
    } finally {
      setPending(false);
    }
  };
  return (
    <Button type="button" variant={variant} size={size} disabled={pending} aria-busy={pending} onClick={download}>
      {pending && <Loader2 className="animate-spin" aria-hidden="true" />}
      {children}
    </Button>
  );
}
