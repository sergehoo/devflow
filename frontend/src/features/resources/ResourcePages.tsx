import { ExternalLink, FileDown, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/services/api";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { LegacyForm } from "@/components/forms/LegacyForm";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { useDebouncedValue } from "@/lib/hooks";
import { legacyUrl } from "@/lib/utils";
import { useRegistry, useResourceDetail, useResourceList, useResourceMutation, type ResourceMeta } from "./api";
import { Cell } from "./Cell";

function useMeta(): { name: string; meta?: ResourceMeta; pending: boolean } {
  const { resource = "" } = useParams();
  const registry = useRegistry();
  return { name: resource, meta: registry.data?.[resource], pending: registry.isPending };
}

const done = (messages: string[] | undefined, fallback: string) => (messages?.length ? messages : [fallback]).forEach((m) => toast.success(m));

/** Liste d'un module (ListView Django : recherche, filtres GET, pagination, scoping et droits). */
export function ResourceListPage() {
  const { name, meta, pending } = useMeta();
  const [search, setSearch] = useSearchParams();
  const [q, setQ] = useState(search.get("q") ?? "");
  const debounced = useDebouncedValue(q);
  const params = { ...Object.fromEntries(search), q: debounced };
  const list = useResourceList(name, params);
  if (pending) return <PageSkeleton />;
  if (!meta) return <EmptyState title="Module introuvable" description="Ce module n'est pas disponible." />;
  const page = Number(search.get("page") ?? 1);
  const setPage = (p: number) => setSearch((s) => { s.set("page", String(p)); return s; });

  return (
    <div className="space-y-6">
      <PageHeader eyebrow={meta.group} title={meta.title}
        description={list.data ? `${list.data.count} élément(s)` : undefined}
        actions={meta.can_create && <Button asChild><Link to={`/m/${name}/new${search.toString() ? `?${search}` : ""}`}><Plus />Ajouter</Link></Button>} />
      <div className="relative max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden="true" />
        <Input type="search" className="pl-9" placeholder="Rechercher…" aria-label={`Rechercher dans ${meta.title}`} value={q}
          onChange={(e) => { setQ(e.target.value); setSearch((s) => { s.delete("page"); return s; }); }} />
      </div>
      {list.isPending ? <Skeleton className="h-80" /> : list.isError ? <ErrorState message={list.error.message} onRetry={() => void list.refetch()} /> : list.data.results.length === 0 ? (
        <EmptyState title="Aucun élément" description={q ? "Rien ne correspond à cette recherche." : "Ce module est vide pour le moment."} />
      ) : (
        <>
          <div className="overflow-x-auto rounded-[22px] border border-transparent bg-card shadow-card dark:border-border">
            <table className="w-full min-w-[40rem] text-sm">
              <thead className="border-b bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr><th className="px-4 py-3 font-semibold">Élément</th>{list.data.columns.map((c) => <th key={c.name} className="px-4 py-3 font-semibold">{c.label}</th>)}</tr>
              </thead>
              <tbody className="divide-y">
                {list.data.results.map((r) => (
                  <tr key={r.id} className="hover:bg-muted/30">
                    <td className="px-4 py-3 font-medium">{meta.has_detail ? <Link className="text-brand hover:underline" to={`/m/${name}/${r.id}`}>{r.label}</Link> : r.label}</td>
                    {list.data.columns.map((c) => <td key={c.name} className="px-4 py-3 align-top"><Cell value={r.cells[c.name] ?? null} /></td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {list.data.num_pages > 1 && (
            <nav aria-label="Pagination" className="flex items-center justify-between text-sm text-muted-foreground">
              <span>Page {list.data.page} / {list.data.num_pages}</span>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Précédent</Button>
                <Button variant="outline" size="sm" disabled={page >= list.data.num_pages} onClick={() => setPage(page + 1)}>Suivant</Button>
              </div>
            </nav>
          )}
        </>
      )}
    </div>
  );
}

/** Fiche d'un élément (DetailView Django) : champs, actions métier, exports, modification, suppression. */
export function ResourceDetailPage() {
  const { name, meta, pending } = useMeta();
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const detail = useResourceDetail(name, id);
  const mutate = useResourceMutation(name);
  const [confirm, setConfirm] = useState<{ code: string; label: string } | null>(null);
  if (pending || detail.isPending) return <PageSkeleton />;
  if (!meta) return <EmptyState title="Module introuvable" />;
  if (detail.isError) return <ErrorState message={detail.error.message} onRetry={() => void detail.refetch()} />;
  const d = detail.data;
  const run = (code: string) => mutate.mutate({ id, action: code }, {
    onSuccess: (r) => { done(r.messages, code === "delete" ? "Élément supprimé." : "Action effectuée."); setConfirm(null); if (code === "delete") navigate(`/m/${name}`); },
    onError: (e) => { toast.error(e.message); setConfirm(null); },
  });

  return (
    <div className="space-y-6">
      <PageHeader eyebrow={meta.singular} title={d.label}
        actions={<>
          {d.downloads.map((x) => <Button key={x.href} variant="outline" asChild><a href={legacyUrl(x.href)} target="_blank" rel="noreferrer"><FileDown />{x.label}</a></Button>)}
          {d.actions.map((a) => <Button key={a.code} variant="outline" onClick={() => setConfirm(a)}>{a.label}</Button>)}
          {meta.can_update && <Button variant="outline" asChild><Link to={`/m/${name}/${id}/edit`}><Pencil />Modifier</Link></Button>}
          {name === "invoice" && <Button variant="outline" asChild><Link to={`/invoices/${id}`}>Lignes, totaux et paiements</Link></Button>}
          {name === "sprint" && <Button variant="outline" asChild><Link to={`/sprints/${id}/board`}>Board du sprint</Link></Button>}
          {name === "roadmap-item" && <ShiftDates itemId={id} />}
          {meta.can_delete && <Button variant="destructive" onClick={() => setConfirm({ code: "delete", label: "Supprimer" })}><Trash2 />Supprimer</Button>}
        </>} />
      <Card>
        <CardContent className="grid gap-x-8 gap-y-4 pt-6 sm:grid-cols-2">
          {d.fields.map((f) => (
            <div key={f.name} className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">{f.label}</p>
              <div className="mt-1 break-words text-sm"><Cell value={f.value} /></div>
            </div>
          ))}
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">
        <a className="inline-flex items-center gap-1 hover:underline" href={legacyUrl(d.legacy_url)}><ExternalLink className="size-3" />Ouvrir dans l'interface historique</a>
      </p>
      <ConfirmDialog open={!!confirm} onOpenChange={(o) => !o && setConfirm(null)} title={confirm?.code === "delete" ? "Supprimer définitivement cet élément ?" : `${confirm?.label} ?`}
        description="L'opération est exécutée avec les règles de l'application." confirmLabel={confirm?.label ?? "Confirmer"}
        destructive={confirm?.code === "delete" || confirm?.code === "revoke" || confirm?.code === "cancel"} pending={mutate.isPending}
        onConfirm={() => confirm && run(confirm.code)} />
    </div>
  );
}

/** Création / modification par le formulaire Django du module (pont `forms/`). */
export function ResourceFormPage() {
  const { name, meta, pending } = useMeta();
  const params = useParams();
  const id = params.id ? Number(params.id) : undefined;
  const [search] = useSearchParams();
  const navigate = useNavigate();
  if (pending) return <PageSkeleton />;
  if (!meta) return <EmptyState title="Module introuvable" />;
  const query = Object.fromEntries([...search].filter(([k]) => k !== "page" && k !== "q"));
  return (
    <div className="space-y-6">
      <PageHeader eyebrow={meta.title} title={id ? `Modifier · ${meta.singular}` : `Nouveau · ${meta.singular}`} />
      <LegacyForm name={name} id={id} query={query} submitLabel={id ? "Enregistrer" : "Créer"} onCancel={() => navigate(-1)}
        onSuccess={({ id: newId, messages }) => {
          done(messages, id ? "Modifications enregistrées." : "Élément créé.");
          navigate(meta.has_detail && newId ? `/m/${name}/${newId}` : `/m/${name}`);
        }} />
    </div>
  );
}

/** Décalage des dates d'un élément de roadmap (vue Django existante, RBAC roadmap.edit). */
function ShiftDates({ itemId }: { itemId: number }) {
  const qc = useQueryClient();
  const [days, setDays] = useState("7");
  const shift = async () => {
    try {
      await api(`roadmap-items/${itemId}/shift-dates/`, { method: "POST", body: { delta_days: Number(days) } });
      toast.success("Dates décalées.");
      void qc.invalidateQueries({ queryKey: ["resources"] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  return (
    <span className="inline-flex items-center gap-1.5">
      <label className="sr-only" htmlFor="shift-days">Décalage en jours</label>
      <input id="shift-days" type="number" value={days} onChange={(e) => setDays(e.target.value)} className="h-9 w-20 rounded-xl border bg-card px-2 text-sm" />
      <Button variant="outline" onClick={() => void shift()}>Décaler (jours)</Button>
    </span>
  );
}
