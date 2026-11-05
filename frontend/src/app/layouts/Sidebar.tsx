import * as Collapsible from "@radix-ui/react-dialog";
import { ChevronDown, ExternalLink, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useState } from "react";
import { NavLink, useLocation } from "react-router";
import { NAVIGATION, resolveLegacy, type NavGroup, type NavItem } from "@/app/navigation";
import { cn, legacyUrl } from "@/lib/utils";
import { useUiStore } from "@/stores/ui";
import type { Me } from "@/types/auth";

const itemClass = (active: boolean) =>
  cn(
    "group flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors",
    active ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground",
  );

function ItemLink({ item, me, nested, collapsed }: { item: NavItem | NavGroup; me: Me; nested?: boolean; collapsed?: boolean }) {
  const Icon = "icon" in item ? item.icon : null;
  const content = (
    <>
      {Icon && <Icon className="size-[18px] shrink-0" aria-hidden="true" />}
      <span className={cn("truncate", collapsed && "sr-only")}>{item.label}</span>
    </>
  );
  if (item.to) {
    return (
      <NavLink to={item.to} end={item.to === "/"} className={({ isActive }) => cn(itemClass(isActive), nested && "py-1.5 pl-10")}>
        {content}
      </NavLink>
    );
  }
  const href = resolveLegacy(item, me);
  if (!href) return null;
  return (
    <a href={legacyUrl(href)} className={cn(itemClass(false), nested && "py-1.5 pl-10")} title="Ouvre la page dans l'interface classique">
      {content}
      {!collapsed && <ExternalLink className="ml-auto size-3 opacity-0 group-hover:opacity-60" aria-hidden="true" />}
    </a>
  );
}

function Group({ group, me, collapsed }: { group: NavGroup; me: Me; collapsed: boolean }) {
  const location = useLocation();
  const items = (group.items ?? []).filter((i) => !i.visible || i.visible(me));
  const containsActive = items.some((i) => i.to && location.pathname.startsWith(i.to));
  const [open, setOpen] = useState(containsActive);
  if (!items.length) return null;
  const Icon = group.icon;
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={cn(itemClass(containsActive), "w-full")}
        title={collapsed ? group.label : undefined}
      >
        <Icon className="size-[18px] shrink-0" aria-hidden="true" />
        <span className={cn("truncate", collapsed && "sr-only")}>{group.label}</span>
        {!collapsed && <ChevronDown className={cn("ml-auto size-4 transition-transform", open && "rotate-180")} aria-hidden="true" />}
      </button>
      {open && !collapsed && (
        <div className="mt-0.5 space-y-0.5">
          {items.map((item) => <ItemLink key={item.label} item={item} me={me} nested />)}
        </div>
      )}
    </div>
  );
}

export function SidebarContent({ me, collapsed = false }: { me: Me; collapsed?: boolean }) {
  return (
    <nav aria-label="Navigation principale" className="flex-1 space-y-1 overflow-y-auto px-3 py-3">
      {NAVIGATION.filter((g) => !g.visible || g.visible(me)).map((group) =>
        group.items ? (
          <Group key={group.label} group={group} me={me} collapsed={collapsed} />
        ) : (
          <ItemLink key={group.label} item={group} me={me} collapsed={collapsed} />
        ),
      )}
    </nav>
  );
}

function Brand({ collapsed }: { collapsed: boolean }) {
  return (
    <div className="flex h-16 items-center gap-2 px-5">
      <span className="font-serif text-xl font-semibold text-foreground">
        {collapsed ? "D" : <>Dev<em className="text-primary">Flow</em></>}
      </span>
    </div>
  );
}

export function Sidebar({ me }: { me: Me }) {
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  const toggle = useUiStore((s) => s.toggleSidebar);
  return (
    <aside className={cn("sticky top-0 hidden h-screen shrink-0 flex-col border-r bg-card transition-[width] duration-200 lg:flex", collapsed ? "w-[72px]" : "w-64")}>
      <Brand collapsed={collapsed} />
      <SidebarContent me={me} collapsed={collapsed} />
      <button
        type="button"
        onClick={toggle}
        className="m-3 flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold text-muted-foreground hover:bg-muted"
        aria-label={collapsed ? "Déplier la barre latérale" : "Replier la barre latérale"}
      >
        {collapsed ? <PanelLeftOpen className="size-4" /> : <><PanelLeftClose className="size-4" /> Replier</>}
      </button>
    </aside>
  );
}

export function MobileSidebar({ me }: { me: Me }) {
  const open = useUiStore((s) => s.mobileNavOpen);
  const setOpen = useUiStore((s) => s.setMobileNavOpen);
  return (
    <Collapsible.Root open={open} onOpenChange={setOpen}>
      <Collapsible.Portal>
        <Collapsible.Overlay className="fixed inset-0 z-40 bg-black/40 lg:hidden" />
        <Collapsible.Content className="fixed inset-y-0 left-0 z-50 flex w-72 flex-col bg-card shadow-2xl lg:hidden" onClick={(e) => {
          if ((e.target as HTMLElement).closest("a")) setOpen(false);
        }}>
          <Collapsible.Title className="sr-only">Navigation</Collapsible.Title>
          <Brand collapsed={false} />
          <SidebarContent me={me} />
        </Collapsible.Content>
      </Collapsible.Portal>
    </Collapsible.Root>
  );
}
