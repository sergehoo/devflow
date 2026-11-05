import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-11 w-full rounded-xl border bg-card px-3.5 text-sm text-foreground placeholder:text-subtle-foreground",
        "transition-colors focus:border-ring focus:outline-none focus:ring-4 focus:ring-primary/10",
        "aria-[invalid=true]:border-destructive disabled:opacity-60",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export const Label = ({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) => (
  <label className={cn("mb-1.5 block text-xs font-semibold text-muted-foreground", className)} {...props} />
);

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "min-h-20 w-full rounded-xl border bg-card px-3.5 py-2.5 text-sm text-foreground placeholder:text-subtle-foreground",
        "focus:border-ring focus:outline-none focus:ring-4 focus:ring-primary/10 aria-[invalid=true]:border-destructive",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        "h-11 w-full rounded-xl border bg-card px-3 text-sm text-foreground",
        "focus:border-ring focus:outline-none focus:ring-4 focus:ring-primary/10 aria-[invalid=true]:border-destructive disabled:opacity-60",
        className,
      )}
      {...props}
    />
  ),
);
Select.displayName = "Select";

/** Libellé + champ + message d'erreur relié (aria-describedby). */
export function Field({ id, label, error, hint, children }: { id: string; label: string; error?: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error ? (
        <p id={`${id}-error`} className="mt-1 text-xs text-destructive">{error}</p>
      ) : hint ? (
        <p className="mt-1 text-xs text-subtle-foreground">{hint}</p>
      ) : null}
    </div>
  );
}
