import * as T from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

export const TooltipProvider = T.Provider;

/** Infobulle accessible (survol + focus clavier), utilisée par la barre d'icônes. */
export function Tooltip({ label, side = "right", children }: { label: ReactNode; side?: "top" | "right" | "bottom" | "left"; children: ReactNode }) {
  return (
    <T.Root delayDuration={120}>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content side={side} sideOffset={12}
          className="z-50 rounded-lg bg-foreground px-2.5 py-1.5 text-xs font-semibold text-background shadow-lg">
          {label}
          <T.Arrow className="fill-foreground" />
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}
