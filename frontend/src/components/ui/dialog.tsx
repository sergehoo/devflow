import * as RD from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Button } from "./button";

export function Dialog({ open, onOpenChange, title, description, children, className }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <RD.Root open={open} onOpenChange={onOpenChange}>
      <RD.Portal>
        <RD.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <RD.Content
          className={cn(
            "fixed inset-x-0 bottom-0 z-50 max-h-[92vh] overflow-y-auto rounded-t-3xl border bg-card p-6 shadow-2xl",
            "sm:inset-auto sm:left-1/2 sm:top-1/2 sm:w-full sm:max-w-lg sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-3xl",
            className,
          )}
          {...(description ? {} : { "aria-describedby": undefined })}
        >
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <RD.Title className="text-lg font-semibold">{title}</RD.Title>
              {description && <RD.Description className="mt-1 text-sm text-muted-foreground">{description}</RD.Description>}
            </div>
            <RD.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Fermer"><X /></Button>
            </RD.Close>
          </div>
          {children}
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}

export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel, destructive, pending, onConfirm }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  destructive?: boolean;
  pending?: boolean;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={title} description={description}>
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
        <Button variant={destructive ? "destructive" : "default"} disabled={pending} onClick={onConfirm}>{confirmLabel}</Button>
      </div>
    </Dialog>
  );
}
