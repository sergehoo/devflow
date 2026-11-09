import { Bell, Briefcase, CheckSquare, GitPullRequest, MessageSquare, Settings2, ShieldAlert, Sparkles, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDateTime } from "@/lib/format";
import type { AppNotification } from "./api";

const ICONS: Record<string, typeof Bell> = {
  TASK: CheckSquare, PROJECT: Briefcase, RISK: ShieldAlert, PR: GitPullRequest, MESSAGE: MessageSquare,
  SPRINT: Zap, AI: Sparkles, SYSTEM: Settings2,
};

export function NotificationItem({ n, onOpen, compact }: { n: AppNotification; onOpen: (n: AppNotification) => void; compact?: boolean }) {
  const Icon = ICONS[n.type] ?? Bell;
  return (
    <button type="button" onClick={() => onOpen(n)}
      className={cn("flex w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        !n.is_read && "bg-primary/5")}>
      <span className={cn("mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg", n.is_read ? "bg-muted text-muted-foreground" : "bg-primary/10 text-brand")}>
        <Icon className="size-4" aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className={cn("truncate text-sm", !n.is_read && "font-semibold")}>{n.title}</span>
          {!n.is_read && <span className="size-2 shrink-0 rounded-full bg-primary" aria-label="Non lue" />}
        </span>
        {n.body && <span className={cn("block text-xs text-muted-foreground", compact ? "line-clamp-1" : "line-clamp-2")}>{n.body}</span>}
        <span className="mt-0.5 block text-[11px] text-subtle-foreground">
          {n.type_label} · {formatDateTime(n.created_at)}{!compact && n.workspace ? ` · ${n.workspace.name}` : ""}
        </span>
      </span>
    </button>
  );
}
