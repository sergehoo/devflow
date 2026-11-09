import { CalendarCheck, CalendarPlus, Gavel, LayoutDashboard, MapPin, Plus, Repeat, Search, Users, X } from "lucide-react";
import { Link, useSearchParams } from "react-router";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Badge, Skeleton } from "@/components/ui/misc";
import { cn } from "@/lib/utils";
import { useMeetings, type MeetingRow } from "./api";
import { MEETING_STATUS_BADGE, fmtDateTime, relative } from "./constants";
import { useUrlSearch } from "./useUrlSearch";

/** Sous-navigation commune des pages réunions. */
export function MeetingsNav() {
  return (
    <>
      <Button variant="outline" asChild><Link to="/meetings/dashboard"><LayoutDashboard />Vue d'ensemble</Link></Button>
      <Button variant="outline" asChild><Link to="/meetings/series"><Repeat />Séries</Link></Button>
      <Button variant="outline" asChild><Link to="/meetings/decisions"><Gavel />Décisions</Link></Button>
    </>
  );
}

function MeetingItem({ m, highlight }: { m: MeetingRow; highlight?: boolean }) {
  return (
    <li className={cn("flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-muted/30", highlight && "bg-primary/5")}>
      <div className="min-w-0 flex-1 basis-60">
        <Link to={`/meetings/${m.id}`} className="font-medium hover:text-brand">{m.title}</Link>
        <p className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
          {m.project && <span>{m.project.name}</span>}
          {m.organizer && <span>par {m.organizer}</span>}
          {m.location && <span className="inline-flex items-center gap-1"><MapPin className="size-3" aria-hidden="true" />{m.location}</span>}
        </p>
      </div>
      <Badge className="bg-info/15 text-info">{m.type_label}</Badge>
      <div className="w-40 text-xs">
        <p>{fmtDateTime(m.scheduled_at)}</p>
        <p className="text-[11px] text-muted-foreground">{m.duration_label} · {relative(m.scheduled_at)}</p>
      </div>
      <span className="inline-flex w-12 items-center gap-1 text-xs text-muted-foreground" title="Participants">
        <Users className="size-3.5" aria-hidden="true" /><span className="sr-only">Participants :</span>{m.participants_count ?? 0}
      </span>
      <Badge className={MEETING_STATUS_BADGE[m.status]}>{m.status_label}</Badge>
    </li>
  );
}

/** Liste des réunions (`ProjectMeetingListView` : à venir puis passées, recherche, type, statut, `?project=`). */
export function MeetingsPage() {
  const [search, setSearch] = useSearchParams();
  const [q, setQ] = useUrlSearch();
  const params: Record<string, string> = Object.fromEntries(search);
  const list = useMeetings(params);
  const project = search.get("project") ?? "";
  const set = (key: string, value: string) => setSearch((s) => { if (value) s.set(key, value); else s.delete(key); s.delete("page"); return s; });
  const page = Number(search.get("page") ?? 1);
  const data = list.data;
  const upcoming = data?.results.filter((r) => !r.is_past) ?? [];
  const past = data?.results.filter((r) => r.is_past) ?? [];

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Collaboration" title="Réunions"
        description="Cadrage, suivi, comités et rétrospectives : notes, décisions, actions et enregistrements."
        actions={<>
          <MeetingsNav />
          <Button asChild><Link to={`/meetings/new${project ? `?project=${project}` : ""}`}><Plus />Nouvelle réunion</Link></Button>
        </>} />

      <div className="flex flex-wrap gap-2">
        <div className="relative min-w-0 flex-1 basis-56">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden="true" />
          <Input type="search" className="pl-9" placeholder="Rechercher…" aria-label="Rechercher une réunion" value={q}
            onChange={(e) => setQ(e.target.value)} />
        </div>
        <Select aria-label="Type de réunion" className="w-auto min-w-40 flex-1 sm:flex-none" value={search.get("type") ?? ""} onChange={(e) => set("type", e.target.value)}>
          <option value="">Tous types</option>
          {data?.type_choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </Select>
        <Select aria-label="Statut" className="w-auto min-w-40 flex-1 sm:flex-none" value={search.get("status") ?? ""} onChange={(e) => set("status", e.target.value)}>
          <option value="">Tous statuts</option>
          {data?.status_choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </Select>
      </div>
      {project && (
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <Badge className="bg-primary/10 text-brand">Projet : {data?.current_project?.name ?? `#${project}`}</Badge>
          {data?.current_project && <Link to={`/projects/${project}`} className="text-xs text-brand hover:underline">Voir le projet</Link>}
          <Button size="sm" variant="ghost" onClick={() => set("project", "")}><X />Tous les projets</Button>
        </p>
      )}

      {list.isPending ? <Skeleton className="h-80" /> : list.isError ? <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />
        : !data || data.results.length === 0 ? (
          <EmptyState title="Aucune réunion" description={q || search.get("type") || search.get("status") ? "Rien ne correspond à ces filtres." : "Planifiez votre première réunion."}
            action={<Button asChild size="sm"><Link to={`/meetings/new${project ? `?project=${project}` : ""}`}><CalendarPlus />Planifier une réunion</Link></Button>} />
        ) : (
          <div className="space-y-4">
            {([["À venir", upcoming, CalendarPlus], ["Passées", past, CalendarCheck]] as const).map(([label, rows, Icon]) => rows.length > 0 && (
              <section key={label} aria-label={label} className="overflow-hidden rounded-[22px] border border-transparent bg-card shadow-card dark:border-border">
                <h2 className="flex items-center gap-2 border-b bg-muted/40 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">
                  <Icon className="size-3.5" aria-hidden="true" />{label} · {rows.length} réunion{rows.length > 1 ? "s" : ""}
                </h2>
                <ul className="divide-y">{rows.map((m, i) => <MeetingItem key={m.id} m={m} highlight={label === "À venir" && i === 0 && page === 1} />)}</ul>
              </section>
            ))}
            {data.num_pages > 1 && (
              <nav aria-label="Pagination" className="flex items-center justify-between text-sm text-muted-foreground">
                <span>{data.count} réunion(s) · page {data.page} / {data.num_pages}</span>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setSearch((s) => { s.set("page", String(page - 1)); return s; })}>Précédent</Button>
                  <Button variant="outline" size="sm" disabled={page >= data.num_pages} onClick={() => setSearch((s) => { s.set("page", String(page + 1)); return s; })}>Suivant</Button>
                </div>
              </nav>
            )}
          </div>
        )}
    </div>
  );
}
