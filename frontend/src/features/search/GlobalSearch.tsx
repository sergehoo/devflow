import { useQuery } from "@tanstack/react-query";
import { CheckSquare, Compass, FolderKanban, Loader2, Search } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router";
import { NAVIGATION } from "@/app/navigation";
import { useMe } from "@/features/auth/api";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { Paginated } from "@/types/api";

interface Hit { id: string; kind: "page" | "project" | "task"; label: string; hint: string; to: string }

const KIND = {
  page: { title: "Pages", icon: Compass },
  project: { title: "Projets", icon: FolderKanban },
  task: { title: "Tâches", icon: CheckSquare },
} as const;

function useDebounced(value: string, delay = 250) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}

const norm = (s: string) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

/**
 * Recherche globale : pages (navigation filtrée par droits d'affichage), projets et
 * tâches via l'API (``?search=``, scopée au workspace côté Django). ⌘K / Ctrl+K.
 */
export function GlobalSearch({ autoFocus, className }: { autoFocus?: boolean; className?: string }) {
  const { data: me } = useMe();
  const navigate = useNavigate();
  const listId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const term = useDebounced(q.trim());
  const enabled = term.length >= 2;

  const projects = useQuery({
    queryKey: ["search", "projects", term], enabled, staleTime: 30_000,
    queryFn: ({ signal }) => api<Paginated<{ id: number; name: string; status_label: string }>>("projects/", { signal, params: { search: term, page_size: 5 } }),
  });
  const tasks = useQuery({
    queryKey: ["search", "tasks", term], enabled, staleTime: 30_000,
    queryFn: ({ signal }) => api<Paginated<{ id: number; title: string; project_name: string }>>("tasks/", { signal, params: { search: term, page_size: 5 } }),
  });

  const hits = useMemo<Hit[]>(() => {
    if (!enabled || !me) return [];
    const t = norm(term);
    const pages: Hit[] = NAVIGATION.filter((g) => !g.visible || g.visible(me)).flatMap((g) =>
      g.items
        ? g.items.filter((i) => i.to && (!i.visible || i.visible(me))).map((i) => ({ label: i.label, group: g.label, to: i.to! }))
        : g.to ? [{ label: g.label, group: "", to: g.to }] : [],
    ).filter((p) => norm(`${p.label} ${p.group}`).includes(t)).slice(0, 4)
      .map((p) => ({ id: `page-${p.to}`, kind: "page", label: p.label, hint: p.group, to: p.to }));
    return [
      ...pages,
      ...(projects.data?.results ?? []).map((p): Hit => ({ id: `project-${p.id}`, kind: "project", label: p.name, hint: p.status_label, to: `/projects/${p.id}` })),
      ...(tasks.data?.results ?? []).map((x): Hit => ({ id: `task-${x.id}`, kind: "task", label: x.title, hint: x.project_name, to: `/tasks/${x.id}` })),
    ];
  }, [enabled, me, term, projects.data, tasks.data]);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        input.current?.focus();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const go = (hit: Hit | undefined) => {
    if (!hit) return;
    navigate(hit.to);
    setOpen(false);
    setQ("");
    input.current?.blur();
  };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, hits.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); go(hits[active]); }
    else if (e.key === "Escape") { setOpen(false); input.current?.blur(); }
  };

  const loading = enabled && (projects.isFetching || tasks.isFetching);
  const show = open && q.trim().length >= 2;
  return (
    <div className={cn("relative w-full", className)}>
      <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
      <input
        ref={input}
        type="search"
        role="combobox"
        aria-expanded={show}
        aria-controls={listId}
        aria-activedescendant={show && hits[active] ? `${listId}-${hits[active].id}` : undefined}
        aria-label="Rechercher des tâches, projets, pages"
        placeholder="Rechercher tâches, projets, pages…"
        autoFocus={autoFocus}
        value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={onKeyDown}
        className="h-11 w-full rounded-full border border-transparent bg-card pl-11 pr-14 text-sm [&::-webkit-search-cancel-button]:appearance-none text-foreground shadow-card placeholder:text-muted-foreground focus:border-border focus:outline-none dark:border-border"
      />
      <kbd className="pointer-events-none absolute right-3 top-1/2 hidden -translate-y-1/2 rounded-md bg-hover px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground sm:block">⌘K</kbd>
      {show && (
        <div id={listId} role="listbox" aria-label="Résultats de recherche"
          className="absolute inset-x-0 top-[calc(100%+8px)] z-50 max-h-[70vh] overflow-y-auto rounded-2xl border bg-card p-1.5 shadow-[0_12px_32px_rgba(32,32,32,0.12)]">
          {loading && !hits.length && <p className="flex items-center gap-2 px-3 py-3 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" aria-hidden="true" />Recherche…</p>}
          {!loading && !hits.length && <p className="px-3 py-3 text-sm text-muted-foreground">Aucun résultat pour « {q.trim()} ».</p>}
          {(["page", "project", "task"] as const).map((kind) => {
            const group = hits.filter((h) => h.kind === kind);
            if (!group.length) return null;
            const Icon = KIND[kind].icon;
            return (
              <div key={kind} role="group" aria-label={KIND[kind].title}>
                <p className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-subtle-foreground">{KIND[kind].title}</p>
                {group.map((h) => {
                  const i = hits.indexOf(h);
                  return (
                    <div key={h.id} id={`${listId}-${h.id}`} role="option" aria-selected={i === active}
                      onMouseDown={(e) => e.preventDefault()} onClick={() => go(h)} onMouseEnter={() => setActive(i)}
                      className={cn("flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2 text-sm", i === active && "bg-hover")}>
                      <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                      <span className="truncate font-medium">{h.label}</span>
                      {h.hint && <span className="ml-auto truncate text-xs text-muted-foreground">{h.hint}</span>}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
