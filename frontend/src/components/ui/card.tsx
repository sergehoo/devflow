import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export const Card = ({ className, ...props }: HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("rounded-[22px] border border-transparent bg-card shadow-card dark:border-border", className)} {...props} />
);
export const CardHeader = ({ className, ...props }: HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("flex flex-col gap-1 p-5 pb-0 sm:px-6 sm:pt-6", className)} {...props} />
);
export const CardTitle = ({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) => (
  <h2 className={cn("text-[17px] font-semibold tracking-tight text-foreground", className)} {...props} />
);
export const CardDescription = ({ className, ...props }: HTMLAttributes<HTMLParagraphElement>) => (
  <p className={cn("text-sm text-muted-foreground", className)} {...props} />
);
export const CardContent = ({ className, ...props }: HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("p-5 sm:p-6", className)} {...props} />
);
