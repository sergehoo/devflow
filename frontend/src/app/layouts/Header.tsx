import { Building2, Check, ChevronsUpDown, LogOut, Menu, MessageSquare, Monitor, Moon, Sun, User } from "lucide-react";
import { Link, useMatches, useNavigate } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar } from "@/components/ui/misc";
import { useLogout, useSwitchWorkspace } from "@/features/auth/api";
import { totalUnread, useConversations } from "@/features/messenger/api";
import { NotificationBell, UnreadBadge } from "@/features/notifications/NotificationBell";
import { legacyUrl } from "@/lib/utils";
import { useUiStore, type ThemeMode } from "@/stores/ui";
import type { Me } from "@/types/auth";

export interface RouteHandle {
  crumb?: string;
}

function Breadcrumbs() {
  const crumbs = useMatches()
    .map((m) => ({ id: m.id, path: m.pathname, crumb: (m.handle as RouteHandle | undefined)?.crumb }))
    .filter((m): m is { id: string; path: string; crumb: string } => Boolean(m.crumb));
  return (
    <nav aria-label="Fil d'Ariane" className="hidden min-w-0 items-center gap-1.5 text-sm md:flex">
      {crumbs.map((c, i) => (
        <span key={c.id} className="flex items-center gap-1.5 truncate">
          {i > 0 && <span className="text-subtle-foreground">/</span>}
          {i === crumbs.length - 1 ? (
            <span aria-current="page" className="truncate font-semibold text-foreground">{c.crumb}</span>
          ) : (
            <Link to={c.path} className="truncate text-muted-foreground hover:text-foreground">{c.crumb}</Link>
          )}
        </span>
      ))}
    </nav>
  );
}

function WorkspaceSwitcher({ me }: { me: Me }) {
  const switchWorkspace = useSwitchWorkspace();
  if (!me.workspace) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="max-w-56" aria-label="Changer de workspace">
          <Building2 /> <span className="truncate">{me.workspace.name}</span> <ChevronsUpDown className="opacity-50" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel>Workspaces</DropdownMenuLabel>
        {me.workspaces.map((w) => (
          <DropdownMenuItem
            key={w.id}
            disabled={switchWorkspace.isPending}
            onSelect={() =>
              w.id !== me.workspace?.id &&
              switchWorkspace.mutate(w.id, {
                onSuccess: () => toast.success(`Workspace « ${w.name} » sélectionné.`),
                onError: (e) => toast.error(e.message),
              })
            }
          >
            <span className="truncate">{w.name}</span>
            {w.id === me.workspace?.id && <Check className="ml-auto !text-primary" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function MessengerLink() {
  const { data } = useConversations();
  const unread = totalUnread(data);
  return (
    <Button variant="ghost" size="icon" className="relative" asChild>
      <Link to="/messenger" aria-label={unread ? `Messagerie (${unread} non lus)` : "Messagerie"}>
        <MessageSquare />
        <UnreadBadge count={unread} label={`${unread} messages non lus`} />
      </Link>
    </Button>
  );
}

const THEMES: { value: ThemeMode; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Clair", icon: Sun },
  { value: "dark", label: "Sombre", icon: Moon },
  { value: "system", label: "Système", icon: Monitor },
];

export function Header({ me }: { me: Me }) {
  const setMobileNavOpen = useUiStore((s) => s.setMobileNavOpen);
  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);
  const logout = useLogout();
  const navigate = useNavigate();
  const ThemeIcon = THEMES.find((t) => t.value === theme)?.icon ?? Monitor;

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b bg-card/80 px-4 backdrop-blur lg:px-6">
      <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMobileNavOpen(true)} aria-label="Ouvrir la navigation">
        <Menu />
      </Button>
      <WorkspaceSwitcher me={me} />
      <Breadcrumbs />
      <div className="ml-auto flex items-center gap-1">
        <MessengerLink />
        <NotificationBell />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Thème"><ThemeIcon /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-36">
            {THEMES.map((t) => (
              <DropdownMenuItem key={t.value} onSelect={() => setTheme(t.value)}>
                <t.icon /> {t.label} {theme === t.value && <Check className="ml-auto !text-primary" />}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button type="button" className="ml-1 rounded-full" aria-label="Menu utilisateur">
              <Avatar name={me.full_name} src={me.avatar} />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>
              <span className="block text-sm text-foreground">{me.full_name}</span>
              <span className="block font-normal">{me.workspace?.role_label || me.email}</span>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <a href={legacyUrl("/profile/")}><User /> Mon profil</a>
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <a href={legacyUrl("/")}><Monitor /> Interface classique</a>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() => logout.mutate(undefined, { onSettled: () => navigate("/login", { replace: true }) })}
              className="text-destructive"
            >
              <LogOut className="!text-destructive" /> Déconnexion
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
