import * as Drawer from "@radix-ui/react-dialog";
import { ChevronDown, ExternalLink, LogOut } from "lucide-react";
import { useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router";
import { NAVIGATION, resolveLegacy, type NavGroup, type NavItem } from "@/app/navigation";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip } from "@/components/ui/tooltip";
import { useLogout } from "@/features/auth/api";
import { cn, legacyUrl } from "@/lib/utils";
import { useUiStore } from "@/stores/ui";
import type { Me } from "@/types/auth";

/** Groupe affiché en bas de la barre (référence : réglages + déconnexion). */
const BOTTOM_GROUP = "Paramètres";
/** Entrées qui ne doivent pas rester actives sur leurs sous-pages (ex. /meetings vs /meetings/series). */
const EXACT = new Set(["/", "/meetings", "/timesheets"]);

const visibleItems = (group: NavGroup, me: Me) => (group.items ?? []).filter((i) => !i.visible || i.visible(me));
const isActive = (pathname: string, to: string) => (EXACT.has(to) ? pathname === to : pathname === to || pathname.startsWith(`${to}/`));

export function BrandMark({ className }: { className?: string }) {
  return (
    <span aria-hidden="true" className={cn("relative flex size-11 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-[0_4px_14px_rgba(255,212,79,0.45)]", className)}>
      <span className="text-lg font-extrabold leading-none tracking-tighter">D</span>
      <span className="absolute -bottom-1 left-1/2 size-2 -translate-x-1/2 rotate-45 rounded-[3px] bg-primary" />
    </span>
  );
}

/** Classe d'un bouton d'icône : actif = fond gris clair + indicateur jaune à gauche. */
const iconClass = (active: boolean) =>
  cn(
    "relative flex size-11 items-center justify-center rounded-2xl transition-colors outline-none",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
    "before:absolute before:-left-[19px] before:top-1/2 before:h-6 before:w-1 before:-translate-y-1/2 before:rounded-r-full before:bg-primary before:transition-opacity",
    active ? "bg-hover text-foreground before:opacity-100" : "text-muted-foreground before:opacity-0 hover:bg-hover hover:text-foreground",
  );

function LegacyOrRoute({ item, me }: { item: NavItem; me: Me }) {
  if (item.to) {
    return <DropdownMenuItem asChild><NavLink to={item.to}>{item.label}</NavLink></DropdownMenuItem>;
  }
  const href = resolveLegacy(item, me);
  if (!href) return null;
  return (
    <DropdownMenuItem asChild>
      <a href={legacyUrl(href)} title="Ouvre la page dans l'interface classique">
        {item.label}<ExternalLink className="ml-auto !size-3.5 opacity-60" aria-hidden="true" />
      </a>
    </DropdownMenuItem>
  );
}

/** Groupe à sous-pages : icône + panneau contextuel (navigation clavier Radix). */
function ContextNavigation({ group, me }: { group: NavGroup; me: Me }) {
  const { pathname } = useLocation();
  const items = visibleItems(group, me);
  if (!items.length) return null;
  const active = items.some((i) => i.to && isActive(pathname, i.to));
  const Icon = group.icon;
  return (
    <DropdownMenu>
      <Tooltip label={group.label}>
        <DropdownMenuTrigger className={iconClass(active)} aria-label={group.label}>
          <Icon className="size-5" strokeWidth={1.75} aria-hidden="true" />
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent side="right" align="start" sideOffset={18} className="min-w-60">
        <DropdownMenuLabel>{group.label}</DropdownMenuLabel>
        {items.map((item) => <LegacyOrRoute key={item.label} item={item} me={me} />)}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function IconLink({ group }: { group: NavGroup }) {
  const { pathname } = useLocation();
  const Icon = group.icon;
  if (!group.to) return null;
  return (
    <Tooltip label={group.label}>
      <NavLink to={group.to} aria-label={group.label} className={iconClass(isActive(pathname, group.to))}>
        <Icon className="size-5" strokeWidth={1.75} aria-hidden="true" />
      </NavLink>
    </Tooltip>
  );
}

function NavEntry({ group, me }: { group: NavGroup; me: Me }) {
  return group.items ? <ContextNavigation group={group} me={me} /> : <IconLink group={group} />;
}

function useSignOut() {
  const logout = useLogout();
  const navigate = useNavigate();
  return () => logout.mutate(undefined, { onSettled: () => navigate("/login", { replace: true }) });
}

/** Barre latérale compacte (≥ lg) : logo, modules en icônes, réglages et déconnexion en bas. */
export function Sidebar({ me }: { me: Me }) {
  const signOut = useSignOut();
  const groups = NAVIGATION.filter((g) => !g.visible || g.visible(me));
  const bottom = groups.find((g) => g.label === BOTTOM_GROUP);
  return (
    <aside className="sticky top-0 hidden h-screen w-[92px] shrink-0 p-3 pr-0 lg:block">
      <div className="flex h-full flex-col items-center rounded-[26px] bg-card py-5 shadow-card dark:border dark:border-border">
        <NavLink to="/" aria-label="DevFlow — tableau de bord" className="rounded-2xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
          <BrandMark />
        </NavLink>
        <nav aria-label="Navigation principale" className="mt-8 flex flex-1 flex-col items-center gap-2.5 overflow-y-auto overflow-x-hidden px-[19px] py-1">
          {groups.filter((g) => g !== bottom).map((g) => <NavEntry key={g.label} group={g} me={me} />)}
        </nav>
        <div className="flex flex-col items-center gap-2.5 px-[19px] pt-3">
          {bottom && <NavEntry group={bottom} me={me} />}
          <Tooltip label="Déconnexion">
            <button type="button" onClick={signOut} aria-label="Déconnexion" className={iconClass(false)}>
              <LogOut className="size-5" strokeWidth={1.75} aria-hidden="true" />
            </button>
          </Tooltip>
        </div>
      </div>
    </aside>
  );
}

// ─── Mobile / tablette : tiroir avec libellés ────────────────────────────────

function DrawerGroup({ group, me }: { group: NavGroup; me: Me }) {
  const { pathname } = useLocation();
  const items = visibleItems(group, me);
  const containsActive = items.some((i) => i.to && isActive(pathname, i.to));
  const [open, setOpen] = useState(containsActive);
  if (!items.length) return null;
  const Icon = group.icon;
  return (
    <div>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className={cn("flex w-full items-center gap-3 rounded-2xl px-3 py-2.5 text-sm font-semibold", containsActive ? "bg-hover text-foreground" : "text-muted-foreground hover:bg-hover hover:text-foreground")}>
        <Icon className="size-5" strokeWidth={1.75} aria-hidden="true" />{group.label}
        <ChevronDown className={cn("ml-auto size-4 transition-transform", open && "rotate-180")} aria-hidden="true" />
      </button>
      {open && (
        <div className="mt-1 space-y-0.5 pl-11">
          {items.map((item) => {
            if (item.to) {
              return (
                <NavLink key={item.label} to={item.to} end={EXACT.has(item.to)}
                  className={({ isActive: a }) => cn("block rounded-xl px-3 py-2 text-sm", a ? "bg-primary-faint font-semibold text-foreground" : "text-muted-foreground hover:bg-hover hover:text-foreground")}>
                  {item.label}
                </NavLink>
              );
            }
            const href = resolveLegacy(item, me);
            return href ? (
              <a key={item.label} href={legacyUrl(href)} className="flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-muted-foreground hover:bg-hover hover:text-foreground">
                {item.label}<ExternalLink className="size-3.5 opacity-60" aria-hidden="true" />
              </a>
            ) : null;
          })}
        </div>
      )}
    </div>
  );
}

export function MobileSidebar({ me }: { me: Me }) {
  const open = useUiStore((s) => s.mobileNavOpen);
  const setOpen = useUiStore((s) => s.setMobileNavOpen);
  const signOut = useSignOut();
  return (
    <Drawer.Root open={open} onOpenChange={setOpen}>
      <Drawer.Portal>
        <Drawer.Overlay className="fixed inset-0 z-40 bg-black/30 lg:hidden" />
        <Drawer.Content
          className="fixed inset-y-3 left-3 z-50 flex w-[min(20rem,calc(100vw-1.5rem))] flex-col rounded-[26px] bg-card p-4 shadow-2xl lg:hidden"
          onClick={(e) => { if ((e.target as HTMLElement).closest("a")) setOpen(false); }}
        >
          <Drawer.Title className="flex items-center gap-3 px-1 pb-4 text-lg font-bold">
            <BrandMark className="size-10" />DevFlow
          </Drawer.Title>
          <nav aria-label="Navigation principale" className="flex-1 space-y-1 overflow-y-auto">
            {NAVIGATION.filter((g) => !g.visible || g.visible(me)).map((g) =>
              g.items ? <DrawerGroup key={g.label} group={g} me={me} /> : (
                <NavLink key={g.label} to={g.to!} end={EXACT.has(g.to!)}
                  className={({ isActive: a }) => cn("flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm font-semibold", a ? "bg-hover text-foreground" : "text-muted-foreground hover:bg-hover hover:text-foreground")}>
                  <g.icon className="size-5" strokeWidth={1.75} aria-hidden="true" />{g.label}
                </NavLink>
              ),
            )}
          </nav>
          <button type="button" onClick={signOut} className="mt-3 flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm font-semibold text-muted-foreground hover:bg-hover hover:text-foreground">
            <LogOut className="size-5" strokeWidth={1.75} aria-hidden="true" />Déconnexion
          </button>
        </Drawer.Content>
      </Drawer.Portal>
    </Drawer.Root>
  );
}
