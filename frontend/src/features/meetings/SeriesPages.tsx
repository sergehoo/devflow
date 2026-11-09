import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Pencil, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge, Skeleton } from "@/components/ui/misc";
import { MEETINGS_KEY, messagesOf, postAction, useSeries, useSeriesList } from "./api";
import { MEETING_STATUS_BADGE, fmtDate, fmtDateTime, fmtLong, fmtTime } from "./constants";
import { useUrlSearch } from "./useUrlSearch";

/** Séries récurrentes (`MeetingSeriesListView`). */
export function SeriesListPage() {
  const [search, setSearch] = useSearchParams();
  const [q, setQ] = useUrlSearch();
  const list = useSeriesList(Object.fromEntries(search));
  const page = Number(search.get("page") ?? 1);
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Réunions" title="Séries de réunions"
        description="Comités, dailys, sprint reviews et autres rendez-vous récurrents : les occurrences sont générées chaque nuit sur 60 jours glissants."
        actions={<>
          <Button variant="outline" asChild><Link to="/meetings"><ArrowLeft />Toutes les réunions</Link></Button>
          <Button asChild><Link to="/meetings/series/new"><Plus />Nouvelle série</Link></Button>
        </>} />
      <div className="relative max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden="true" />
        <Input type="search" className="pl-9" placeholder="Rechercher une série…" aria-label="Rechercher une série" value={q}
          onChange={(e) => setQ(e.target.value)} />
      </div>
      {list.isPending ? <Skeleton className="h-64" /> : list.isError ? <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />
        : !list.data.results.length ? (
          <EmptyState title="Aucune série récurrente" description={q ? "Rien ne correspond à cette recherche." : undefined}
            action={<Button size="sm" asChild><Link to="/meetings/series/new"><Plus />Créer ma première série</Link></Button>} />
        ) : (
          <>
            <ul className="divide-y overflow-hidden rounded-2xl border bg-card">
              {list.data.results.map((s) => (
                <li key={s.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1 basis-60">
                    <Link to={`/meetings/series/${s.id}`} className="font-medium hover:text-primary">{s.name}</Link>
                    {s.description && <p className="mt-0.5 line-clamp-1 text-[11px] text-muted-foreground">{s.description}</p>}
                  </div>
                  <span className="text-xs text-muted-foreground">{s.type_label}</span>
                  <span className="text-xs">{s.recurrence_label}</span>
                  <span className="text-xs text-muted-foreground">{s.default_projects_count} projet(s)</span>
                  <Badge className={s.is_active ? "bg-success/15 text-success" : ""}>{s.is_active ? "Active" : "Pause"}</Badge>
                </li>
              ))}
            </ul>
            {list.data.num_pages > 1 && (
              <nav aria-label="Pagination" className="flex items-center justify-between text-sm text-muted-foreground">
                <span>Page {list.data.page} / {list.data.num_pages}</span>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setSearch((s) => { s.set("page", String(page - 1)); return s; })}>Précédent</Button>
                  <Button variant="outline" size="sm" disabled={page >= list.data.num_pages} onClick={() => setSearch((s) => { s.set("page", String(page + 1)); return s; })}>Suivant</Button>
                </div>
              </nav>
            )}
          </>
        )}
    </div>
  );
}

/** Fiche série (`MeetingSeriesDetailView`) : régénération 60 j, occurrences à venir et historique. */
export function SeriesDetailPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: s, isPending, isError, error, refetch } = useSeries(id);
  const [pending, setPending] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  if (isPending) return <PageSkeleton />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;

  const call = async (path: string, fallback: string, after?: () => void) => {
    setPending(true);
    try {
      messagesOf(await postAction(path), fallback).forEach((m) => toast.success(m));
      await qc.invalidateQueries({ queryKey: MEETINGS_KEY });
      after?.();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setPending(false);
    }
  };
  const meta: [string, string][] = [
    ["Début", fmtDate(s.start_date)], ["Fin", s.end_date ? fmtDate(s.end_date) : "— sans fin —"], ["Heure", s.time_local], ["Durée", `${s.duration_minutes} min`],
    ["Organisateur", s.organizer || "—"], ["Lieu", s.location || "—"],
  ];

  return (
    <div className="space-y-6">
      <PageHeader eyebrow={`Série · ${s.type_label}`} title={s.name}
        description={<span className="flex flex-wrap items-center gap-2">{s.recurrence_label}<Badge className={s.is_active ? "bg-success/15 text-success" : ""}>{s.is_active ? "Active" : "Pause"}</Badge></span>}
        actions={<>
          <Button variant="outline" asChild><Link to={`/meetings/series/${id}/edit`}><Pencil />Modifier</Link></Button>
          <Button disabled={pending} onClick={() => void call(`resources/meeting-series/${id}/actions/regenerate/`, "Occurrences régénérées.")}><RefreshCw />Régénérer 60 j</Button>
          <Button variant="outline" className="text-destructive" onClick={() => setConfirmDelete(true)}><Trash2 />Supprimer</Button>
        </>} />
      {s.description && <p className="text-sm text-muted-foreground">{s.description}</p>}
      <Card>
        <CardContent className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
          {meta.map(([k, v]) => <div key={k}><p className="text-[11px] uppercase text-muted-foreground">{k}</p><p className="font-medium">{v}</p></div>)}
          {s.meeting_link && <div className="min-w-0"><p className="text-[11px] uppercase text-muted-foreground">Lien visio</p>
            <a href={s.meeting_link} target="_blank" rel="noreferrer" className="block truncate text-primary hover:underline">{s.meeting_link}</a></div>}
          {s.default_projects.length > 0 && <div className="sm:col-span-2 lg:col-span-3"><p className="text-[11px] uppercase text-muted-foreground">Projets en revue</p>
            <p className="flex flex-wrap gap-x-2">{s.default_projects.map((p) => <Link key={p.id} to={`/projects/${p.id}`} className="text-primary hover:underline">{p.name}</Link>)}</p></div>}
          {s.default_participants.length > 0 && <div className="sm:col-span-2 lg:col-span-3"><p className="text-[11px] uppercase text-muted-foreground">Participants par défaut</p>
            <p>{s.default_participants.map((u) => u?.name).join(", ")}</p></div>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Occurrences à venir</CardTitle></CardHeader>
        <CardContent>
          {s.upcoming.length ? (
            <ul className="divide-y">
              {s.upcoming.map((o) => (
                <li key={o.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <Link to={`/meetings/${o.id}`} className="text-sm hover:text-primary">{fmtLong(o.scheduled_at)} — {fmtTime(o.scheduled_at)}</Link>
                  <Badge className={MEETING_STATUS_BADGE[o.status]}>{o.status_label}</Badge>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm italic text-muted-foreground">Aucune occurrence à venir. Cliquez sur « Régénérer » pour forcer.</p>}
        </CardContent>
      </Card>
      {s.past.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Historique</CardTitle></CardHeader>
          <CardContent>
            <ul className="divide-y">
              {s.past.map((o) => (
                <li key={o.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <Link to={`/meetings/${o.id}`} className="text-sm text-muted-foreground hover:text-primary">{fmtDateTime(o.scheduled_at)}</Link>
                  <span className="text-[11px] text-muted-foreground">{o.status_label}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
      {!s.upcoming.length && !s.past.length && <EmptyState title="Aucune occurrence" description="La série n'a encore généré aucune réunion." />}
      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} destructive pending={pending}
        title="Supprimer cette série ?" description="Les occurrences déjà créées restent dans la liste des réunions." confirmLabel="Supprimer"
        onConfirm={() => void call(`resources/meeting-series/${id}/delete/`, "Série supprimée.", () => navigate("/meetings/series"))} />
    </div>
  );
}
