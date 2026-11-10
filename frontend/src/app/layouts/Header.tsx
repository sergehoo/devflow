import { Building2, Check, ChevronDown, ChevronsUpDown, LogOut, Menu, MessageSquare, Monitor, Moon, Search, Sun, SunMedium, User, X } from "lucide-react";
import { useState } from "react";
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
import { GlobalSearch } from "@/features/search/GlobalSearch";
import { legacyUrl } from "@/lib/utils";
import { useUiStore, type ThemeMode } from "@/stores/ui";
import type { Me } from "@/types/auth";
import { BrandMark } from "./Sidebar";

export interface RouteHandle {
  crumb?: string;
}

/** Fil d'Ariane (affiché au-dessus du contenu dès le 2e niveau). */
export function Breadcrumbs() {
  const crumbs = useMatches()
    .map((m) => ({ id: m.id, path: m.pathname, crumb: (m.handle as RouteHandle | undefined)?.crumb }))
    .filter((m): m is { id: string; path: string; crumb: string } => Boolean(m.crumb));
  if (crumbs.length < 2) return null;
  return (
    <nav aria-label="Fil d'Ariane" className="mb-4 flex min-w-0 flex-wrap items-center gap-1.5 text-xs">
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
        <Button variant="outline" size="sm" className="h-9 max-w-48 border-transparent shadow-card dark:border-border" aria-label="Changer de workspace">
          <Building2 /> <span className="truncate">{me.workspace.name}</span> <ChevronsUpDown className="opacity-50" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
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
            {w.id === me.workspace?.id && <Check className="ml-auto !text-brand" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const roundIcon = "relative size-10 rounded-full border border-transparent bg-card text-muted-foreground shadow-card hover:bg-card hover:text-foreground dark:border-border";

function MessengerLink() {
  const { data } = useConversations();
  const unread = totalUnread(data);
  return (
    <Button variant="ghost" size="icon" className={roundIcon} asChild>
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

const dateLabel = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

function Greeting({ me }: { me: Me }) {
  const now = new Date();
  const hello = now.getHours() < 18 ? "Bonjour" : "Bonsoir";
  return (
    <div className="hidden min-w-0 leading-tight xl:block">
      <p className="truncate text-xs font-semibold capitalize text-foreground">{dateLabel.format(now)}</p>
      <p className="mt-0.5 flex items-center gap-1.5 truncate text-xs text-muted-foreground">
        <SunMedium className="size-3.5 text-brand" aria-hidden="true" />{hello}{me.first_name ? `, ${me.first_name}` : ""}
      </p>
    </div>
  );
}

/** Barre supérieure : date et salutation, recherche globale, workspace, messagerie, notifications, profil. */
export function Header({ me }: { me: Me }) {
  const setMobileNavOpen = useUiStore((s) => s.setMobileNavOpen);
  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);
  const logout = useLogout();
  const navigate = useNavigate();
  const [mobileSearch, setMobileSearch] = useState(false);
  const ThemeIcon = THEMES.find((t) => t.value === theme)?.icon ?? Monitor;

  return (
    <header className="sticky top-0 z-30 bg-background/85 px-4 pb-2 pt-3 backdrop-blur-md lg:px-8 lg:pt-4">
      <div className="flex h-12 items-center gap-3">
        <Button variant="ghost" size="icon" className={`${roundIcon} lg:hidden`} onClick={() => setMobileNavOpen(true)} aria-label="Ouvrir la navigation">
          <Menu />
        </Button>
        <Link to="/" className="flex items-center gap-2 font-bold lg:hidden" aria-label="DevFlow — tableau de bord">
          <BrandMark className="size-9 rounded-xl" />
        </Link>
        <Greeting me={me} />
        <div className="mx-auto hidden w-full max-w-[440px] md:block">
          <GlobalSearch />
        </div>
        <div className="ml-auto flex items-center gap-2 md:ml-0">
          <Button variant="ghost" size="icon" className={`${roundIcon} md:hidden`} onClick={() => setMobileSearch((v) => !v)}
            aria-label={mobileSearch ? "Fermer la recherche" : "Rechercher"} aria-expanded={mobileSearch}>
            {mobileSearch ? <X /> : <Search />}
          </Button>
          <div className="hidden sm:block"><WorkspaceSwitcher me={me} /></div>
          <MessengerLink />
          <div className="[&>button]:size-10 [&>button]:rounded-full [&>button]:bg-card [&>button]:shadow-card"><NotificationBell /></div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className={`${roundIcon} hidden sm:inline-flex`} aria-label="Thème"><ThemeIcon /></Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-36">
              {THEMES.map((t) => (
                <DropdownMenuItem key={t.value} onSelect={() => setTheme(t.value)}>
                  <t.icon /> {t.label} {theme === t.value && <Check className="ml-auto !text-brand" />}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button type="button" className="flex items-center gap-2.5 rounded-full py-1 pl-1 pr-1 text-left outline-none focus-visible:outline-2 focus-visible:outline-ring sm:pr-2" aria-label="Menu utilisateur">
                <Avatar name={me.full_name} src={me.avatar} className="size-10" />
                <span className="hidden min-w-0 leading-tight xl:block">
                  <span className="block max-w-36 truncate text-sm font-semibold">{me.full_name}</span>
                  <span className="block max-w-36 truncate text-xs text-muted-foreground">{me.workspace?.role_label || me.email}</span>
                </span>
                <ChevronDown className="hidden size-4 text-muted-foreground xl:block" aria-hidden="true" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>
                <span className="block text-sm text-foreground">{me.full_name}</span>
                <span className="block font-normal">{me.workspace?.role_label || me.email}</span>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <div className="sm:hidden">
                {THEMES.map((t) => (
                  <DropdownMenuItem key={t.value} onSelect={() => setTheme(t.value)}>
                    <t.icon /> Thème {t.label.toLowerCase()} {theme === t.value && <Check className="ml-auto !text-brand" />}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
              </div>
              <DropdownMenuItem asChild>
                <Link to="/profile"><User /> Mon profil</Link>
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <a href={legacyUrl("/dashboard/classic/")}><Monitor /> Interface classique</a>
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
      </div>
      {mobileSearch && (
        <div className="mt-2 space-y-2 md:hidden">
          <GlobalSearch autoFocus />
          <div className="sm:hidden"><WorkspaceSwitcher me={me} /></div>
        </div>
      )}
    </header>
  );
}
