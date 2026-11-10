import { useId } from "react";
import { cn } from "@/lib/utils";
import { BRAND_COLORS, COMPACT, DETAILED } from "./geometry";

/**
 * Signature DevFlow : un flux en S (le « / » de </>) porté par deux voies de
 * données binaires. L'encre suit `currentColor` (anthracite en clair, crème en
 * sombre) ; le jaune et l'ambre sont fixes.
 *
 * - `symbol`  : symbole détaillé, caractères 0/1 (à partir de 56 px) ;
 * - `compact` : symbole simplifié, 1 = trait, 0 = point (petites tailles) ;
 * - `full`    : symbole + logotype « DevFlow ».
 */
export type DevFlowLogoVariant = "full" | "symbol" | "compact";

interface Props {
  variant?: DevFlowLogoVariant;
  /** Hauteur du symbole en pixels. */
  size?: number;
  className?: string;
  /** Texte alternatif ; `null` = décoratif (masqué aux lecteurs d'écran). */
  title?: string | null;
}

function Mark({ detailed, size, title }: { detailed: boolean; size: number; title: string | null }) {
  const titleId = useId();
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className="shrink-0" role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true} aria-labelledby={title ? titleId : undefined} focusable="false">
      {title && <title id={titleId}>{title}</title>}
      {detailed ? (
        <>
          <path d={DETAILED.flow} fill="none" stroke={BRAND_COLORS.yellow} strokeWidth={6.5} strokeLinecap="round" />
          {([["ink", "currentColor"], ["amber", BRAND_COLORS.amber]] as const).map(([lane, color]) => (
            <g key={lane} fill={color}>
              {DETAILED[lane].map(([x, y, angle, bit], i) => (
                <g key={i} transform={`translate(${x} ${y}) rotate(${angle})`}>
                  {bit ? <rect x={-0.93} y={-3.1} width={1.86} height={6.2} rx={0.93} />
                    : <ellipse rx={1.86} ry={2.6} fill="none" stroke={color} strokeWidth={1.49} />}
                </g>
              ))}
            </g>
          ))}
        </>
      ) : (
        <>
          <path d={COMPACT.flow} fill="none" stroke={BRAND_COLORS.yellow} strokeWidth={8} strokeLinecap="round" />
          <path d={COMPACT.ink} fill="none" stroke="currentColor" strokeWidth={4.6} strokeLinecap="round" strokeDasharray="0 7.5 6 7.5" />
          <path d={COMPACT.amber} fill="none" stroke={BRAND_COLORS.amber} strokeWidth={4.6} strokeLinecap="round" strokeDasharray="0 7.5 6 7.5" />
        </>
      )}
    </svg>
  );
}

export function DevFlowLogo({ variant = "symbol", size = 40, className, title = "DevFlow" }: Props) {
  const detailed = variant === "symbol" || (variant === "full" && size >= 56);
  if (variant !== "full") {
    return <span className={cn("inline-flex text-foreground", className)}><Mark detailed={detailed} size={size} title={title} /></span>;
  }
  return (
    <span className={cn("inline-flex items-center gap-2.5 text-foreground", className)} role={title ? "img" : undefined}
      aria-label={title ?? undefined} aria-hidden={title ? undefined : true}>
      <Mark detailed={detailed} size={size} title={null} />
      <span aria-hidden="true" className="font-extrabold leading-none tracking-[-0.03em]" style={{ fontSize: Math.round(size * 0.5) }}>
        Dev<span className="text-brand">Flow</span>
      </span>
    </span>
  );
}
