import type { HTMLAttributes } from "react";
import { cn, initials } from "@/lib/utils";

export const Skeleton = ({ className, ...props }: HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("animate-pulse rounded-xl bg-muted", className)} aria-hidden="true" {...props} />
);

export const Badge = ({ className, ...props }: HTMLAttributes<HTMLSpanElement>) => (
  <span
    className={cn("inline-flex items-center rounded-full bg-muted px-2.5 py-0.5 text-[11px] font-semibold text-muted-foreground", className)}
    {...props}
  />
);

export function Avatar({ name, src, className }: { name: string; src?: string | null; className?: string }) {
  return src ? (
    <img src={src} alt="" className={cn("size-9 rounded-full object-cover", className)} />
  ) : (
    <span
      aria-hidden="true"
      className={cn("flex size-9 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground", className)}
    >
      {initials(name)}
    </span>
  );
}
