import * as Dropdown from "@radix-ui/react-dropdown-menu";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

export const DropdownMenu = Dropdown.Root;
export const DropdownMenuTrigger = Dropdown.Trigger;
export const DropdownMenuLabel = ({ className, ...props }: ComponentProps<typeof Dropdown.Label>) => (
  <Dropdown.Label className={cn("px-2 py-1.5 text-xs font-semibold text-subtle-foreground", className)} {...props} />
);
export const DropdownMenuSeparator = () => <Dropdown.Separator className="my-1 h-px bg-border" />;

export function DropdownMenuContent({ className, sideOffset = 6, ...props }: ComponentProps<typeof Dropdown.Content>) {
  return (
    <Dropdown.Portal>
      <Dropdown.Content
        sideOffset={sideOffset}
        className={cn("z-50 min-w-52 rounded-2xl border bg-card p-1.5 shadow-[0_12px_32px_rgba(32,32,32,0.12)]", className)}
        {...props}
      />
    </Dropdown.Portal>
  );
}

export const DropdownMenuItem = ({ className, ...props }: ComponentProps<typeof Dropdown.Item>) => (
  <Dropdown.Item
    className={cn(
      "flex cursor-pointer select-none items-center gap-2 rounded-xl px-2.5 py-2 text-sm text-foreground outline-none",
      "data-[highlighted]:bg-hover data-[disabled]:opacity-50 [&_svg]:size-4 [&_svg]:text-muted-foreground",
      className,
    )}
    {...props}
  />
);
