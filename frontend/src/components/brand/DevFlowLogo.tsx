import { useId } from "react";
import { cn } from "@/lib/utils";
import { BRAND_COLORS, FULL_LOGO_RATIO, MARK, type MarkLevel } from "./geometry";

/**
 * Logo DevFlow : une ampoule (l'idée) qui contient un engrenage (l'exécution).
 * Le jaune est fixe ; l'engrenage suit `currentColor` (noir en clair, crème en sombre).
 *
 * - `symbol`  : symbole détaillé (à partir de 56 px) ;
 * - `compact` : symbole aux traits épaissis (24 à 48 px) ;
 * - `full`    : logo complet « DEV flow » (image du logo officiel, déclinée clair / sombre).
 */
export type DevFlowLogoVariant = "full" | "symbol" | "compact";

interface Props {
  variant?: DevFlowLogoVariant;
  /** Hauteur en pixels. */
  size?: number;
  className?: string;
  /** Texte alternatif ; `null` = décoratif (masqué aux lecteurs d'écran). */
  title?: string | null;
}

function Mark({ level, size, title }: { level: MarkLevel; size: number; title: string | null }) {
  const titleId = useId();
  const g = MARK[level];
  const line = { fill: "none", strokeLinecap: "round", strokeLinejoin: "round", strokeWidth: g.stroke } as const;
  return (
    <svg viewBox={g.viewBox} width={size} height={size} className="shrink-0" role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true} aria-labelledby={title ? titleId : undefined} focusable="false">
      {title && <title id={titleId}>{title}</title>}
      <path d={g.yellow} stroke={BRAND_COLORS.yellow} {...line} />
      <path d={g.gear} stroke="currentColor" {...line} />
      {g.hub.filled ? <circle cx={g.hub.cx} cy={g.hub.cy} r={g.hub.r} fill="currentColor" />
        : <circle cx={g.hub.cx} cy={g.hub.cy} r={g.hub.r} stroke="currentColor" {...line} />}
    </svg>
  );
}

const asset = (name: string) => `${import.meta.env.BASE_URL}brand/${name}`;

export function DevFlowLogo({ variant = "symbol", size = 40, className, title = "DevFlow" }: Props) {
  if (variant !== "full") {
    const level: MarkLevel = variant === "symbol" && size >= 56 ? "detailed" : "compact";
    return <span className={cn("inline-flex text-foreground", className)}><Mark level={level} size={size} title={title} /></span>;
  }
  const width = Math.round(size * FULL_LOGO_RATIO);
  const img = { width, height: size, alt: "", decoding: "async" as const, draggable: false };
  // Deux images (clair / sombre, thème piloté par la classe `.dark`) ; le nom est porté par le conteneur.
  return (
    <span className={cn("inline-flex shrink-0", className)} style={{ width, height: size }}
      role={title ? "img" : undefined} aria-label={title ?? undefined} aria-hidden={title ? undefined : true}>
      <img {...img} src={asset("devflow-logo.png")} className="block dark:hidden" />
      <img {...img} src={asset("devflow-logo-dark.png")} className="hidden dark:block" />
    </span>
  );
}
