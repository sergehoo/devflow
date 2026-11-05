import { KeyRound, Pencil, Search, UserMinus, UserPlus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { PageHeader, Pagination } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/input";
import { Avatar, Badge, Skeleton } from "@/components/ui/misc";
import { useMe } from "@/features/auth/api";
import { formatDate } from "@/lib/format";
import { useDebouncedValue } from "@/lib/hooks";
import { useMembers, useTeamAction, type Member } from "./api";

const EMPTY = { q: "", team: "", role: "", status: "", page: 1 };

export function MembersPage() {
  const { data: me } = useMe();
  const [f, setF] = useState(EMPTY);
  const q = useDebouncedValue(f.q);
  const { data, isPending, isError, error, refetch } = useMembers({ ...f, q });
  const action = useTeamAction();
  const [reset, setReset] = useState<Member | null>(null);
  const [removing, setRemoving] = useState<Member | null>(null);
  const set = (patch: Partial<typeof EMPTY>) => setF((x) => ({ ...x, page: 1, ...patch }));

  const run = (name: string, m: Member, data?: Record<string, string>) => action.mutate({ action: name, id: m.id, data }, {
    onSuccess: (r) => { (r.messages?.length ? r.messages : ["Action effectuée."]).forEach((msg) => toast.success(msg)); setReset(null); setRemoving(null); },
    onError: (e) => { toast.error(e.message); setReset(null); setRemoving(null); },
  });

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Organisation" title="Membres" description={data ? `${data.count} membre(s)` : undefined}
        actions={data?.permissions.can_onboard && <Button asChild><Link to="/members/new"><UserPlus />Intégrer un collaborateur</Link></Button>} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[2fr_repeat(3,1fr)]">
        <div className="relative sm:col-span-2 lg:col-span-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden="true" />
          <Input type="search" className="pl-9" placeholder="Nom, email, poste…" aria-label="Rechercher un membre" value={f.q} onChange={(e) => set({ q: e.target.value })} />
        </div>
        {([["team", "Équipe", "teams"], ["role", "Rôle", "roles"], ["status", "Statut", "statuses"]] as const).map(([key, label, opt]) => (
          <Select key={key} aria-label={label} value={f[key]} onChange={(e) => set({ [key]: e.target.value })}>
            <option value="">{label} : tous</option>
            {data?.filters[opt].map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </Select>
        ))}
      </div>

      {isPending ? <Skeleton className="h-96" /> : isError ? <ErrorState message={error.message} onRetry={() => void refetch()} /> : data.results.length === 0 ? (
        <EmptyState title="Aucun membre" />
      ) : (
        <>
          <div className="overflow-x-auto rounded-2xl border bg-card">
            <table className="w-full min-w-[900px] text-sm">
              <caption className="sr-only">Membres du workspace</caption>
              <thead className="border-b bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>{["Membre", "Équipe", "Rôle", "Manager (N+1)", "Capacité", "Charge", "Statut", ""].map((h) => <th key={h} scope="col" className="px-4 py-3 font-semibold">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y">
                {data.results.map((m) => (
                  <tr key={m.id} className="hover:bg-muted/40">
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-3">
                        <Avatar name={m.user.name} className="size-8" />
                        <div className="min-w-0"><p className="truncate font-medium">{m.user.name}{m.is_owner && <Badge className="ml-2">Propriétaire</Badge>}</p><p className="truncate text-xs text-muted-foreground">{m.job_title || m.user.email}</p></div>
                      </div>
                    </td>
                    <td className="px-4 py-2.5">{m.team ? <Link to={`/teams/${m.team.id}`} className="hover:text-primary">{m.team.name}</Link> : "—"}</td>
                    <td className="px-4 py-2.5">{m.role_label}</td>
                    <td className="px-4 py-2.5">{m.manager || "—"}</td>
                    <td className="px-4 py-2.5 tabular-nums">{m.capacity_hours_per_week != null ? `${m.capacity_hours_per_week} h/sem.` : "—"}</td>
                    <td className="px-4 py-2.5 tabular-nums">{m.current_load_percent} %</td>
                    <td className="px-4 py-2.5"><Badge>{m.status_label}</Badge>{m.joined_at && <span className="block text-[11px] text-muted-foreground">depuis {formatDate(m.joined_at)}</span>}</td>
                    <td className="px-4 py-2.5">
                      <span className="flex justify-end gap-1">
                        <Button size="icon" variant="ghost" aria-label={`Modifier ${m.user.name}`} asChild><Link to={`/members/${m.id}/edit`}><Pencil /></Link></Button>
                        {data.permissions.can_manage_passwords && m.user.id !== me?.id && (
                          <Button size="icon" variant="ghost" aria-label={`Réinitialiser le mot de passe de ${m.user.name}`} onClick={() => setReset(m)}><KeyRound /></Button>
                        )}
                        {!m.is_owner && <Button size="icon" variant="ghost" aria-label={`Retirer ${m.user.name}`} onClick={() => setRemoving(m)}><UserMinus /></Button>}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={f.page} count={data.count} onPage={(page) => setF((x) => ({ ...x, page }))} />
        </>
      )}

      <Dialog open={!!reset} onOpenChange={(o) => !o && setReset(null)} title="Réinitialiser le mot de passe"
        description={reset ? `${reset.user.name} recevra un lien sécurisé par email (aucun mot de passe en clair).` : undefined}>
        <div className="space-y-3">
          <Button className="w-full justify-start" variant="outline" disabled={action.isPending} onClick={() => reset && run("member-password-reset", reset, { mode: "link" })}>
            Envoyer un lien — l'ancien mot de passe reste valable jusqu'au changement
          </Button>
          <Button className="w-full justify-start" variant="destructive" disabled={action.isPending} onClick={() => reset && run("member-password-reset", reset, { mode: "force" })}>
            Forcer — invalide l'ancien mot de passe et déconnecte les sessions
          </Button>
        </div>
      </Dialog>
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} destructive pending={action.isPending}
        title="Retirer ce membre ?" description={removing ? `${removing.user.name} perdra l'accès à ce workspace.` : ""} confirmLabel="Retirer"
        onConfirm={() => removing && run("member-delete", removing)} />
    </div>
  );
}
