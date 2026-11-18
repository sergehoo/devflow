import { AlertTriangle, ChevronDown, ChevronRight, History, Pencil, Plus, Trash2, UserCheck, Users, Wallet } from "lucide-react";
import { Fragment, useMemo, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/input";
import { Badge, Skeleton } from "@/components/ui/misc";
import { useMe } from "@/features/auth/api";
import { StatCard } from "@/features/dashboard/widgets";
import { formatDate, formatHours, formatMoney, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useArchiveRate, useRates, useSaveRate, type Rate, type RateMember, type RatePayload, type RatesBoard } from "./rates";

const STATUS: Record<Rate["status"], { label: string; className: string }> = {
  current: { label: "En vigueur", className: "bg-success/15 text-success" },
  future: { label: "À venir", className: "bg-info/15 text-info" },
  past: { label: "Terminé", className: "bg-muted text-muted-foreground" },
};

/** Unité du montant saisi : « 75 000 XOF / jour » plutôt que « / journalier ». */
const PER: Record<string, string> = { HOURLY: "heure", DAILY: "jour", MONTHLY: "mois" };
const per = (rate: Rate) => PER[rate.unit] ?? rate.unit_label.toLowerCase();

/** Ce qui valorise réellement les heures d'un collaborateur sans TJM général en vigueur. */
function missingLabel(m: RateMember, currency: string) {
  if (!m.home) return "TJM général géré par son espace principal : tarifs propres aux projets d'ici uniquement";
  const projectRate = m.rates.some((x) => x.project && x.status === "current");
  if (m.profile_cost_per_day) return `Aucun TJM : heures valorisées au coût du profil (${formatMoney(m.profile_cost_per_day, currency)} / jour)`;
  if (projectRate) return "TJM général manquant : seules les heures du projet à tarif négocié sont valorisées";
  return "Aucun TJM : heures valorisées à 0";
}

const SHOWN = new Set(["cost_rate_amount", "sale_rate_amount", "valid_from", "valid_to", "project"]);

const nextDay = (iso: string) => new Date(Date.parse(`${iso}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10);

const period = (r: Rate) => (r.valid_to ? `${formatDate(r.valid_from)} → ${formatDate(r.valid_to)}` : `depuis le ${formatDate(r.valid_from)}`);

/**
 * Finance › TJM des collaborateurs : coût journalier (coût réel des projets) et tarif de vente.
 * Un tarif s'applique à partir de sa date de début ; le coût des heures déjà saisies reste figé,
 * sauf revalorisation demandée. Lecture : ``billing.view`` ; modification : ``billing.manage``.
 */
export function RatesPage() {
  const { data: me } = useMe();
  const workspace = me?.workspace?.id;
  const { data, isPending, isError, error, refetch } = useRates(workspace);
  const [search, setSearch] = useState("");
  const [missingOnly, setMissingOnly] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [editing, setEditing] = useState<{ member: RateMember; rate?: Rate } | null>(null);
  const [removing, setRemoving] = useState<{ member: RateMember; rate: Rate } | null>(null);

  const members = useMemo(() => (data?.members ?? []).filter((m) =>
    (!missingOnly || !m.current) && `${m.name} ${m.job_title} ${m.team}`.toLowerCase().includes(search.trim().toLowerCase())), [data, search, missingOnly]);

  if (me && workspace == null) return <EmptyState title="Aucun workspace" description="Sélectionnez un workspace pour gérer les TJM." />;
  if (workspace == null || isPending) return <Skeleton className="h-96" />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;
  const c = data.currency;

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Finance" title="TJM des collaborateurs"
        description="Coût journalier (pris en compte dans le coût réel des projets) et tarif de vente de chaque collaborateur. Un tarif s'applique à partir de sa date de début ; les heures déjà saisies gardent leur coût, sauf si vous choisissez de les revaloriser." />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={Users} value={data.summary.members} unit="" label="Collaborateurs" />
        <StatCard icon={UserCheck} value={data.summary.with_rate} unit="" label="Avec un TJM en vigueur" />
        <StatCard icon={AlertTriangle} value={data.summary.without_rate} unit="" label="Sans TJM général"
          hint={data.summary.without_rate ? "Coût du profil, sinon 0." : undefined} />
        <StatCard icon={Wallet} value={data.summary.unvalued_entries} unit="" label="Saisies non valorisées"
          hint={data.summary.unvalued_entries ? "À revaloriser." : undefined} />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Input type="search" aria-label="Rechercher un collaborateur" placeholder="Rechercher un collaborateur, un poste, une équipe…"
          className="max-w-sm" value={search} onChange={(e) => setSearch(e.target.value)} />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="size-4 accent-primary" checked={missingOnly} onChange={(e) => setMissingOnly(e.target.checked)} />
          Sans TJM uniquement
        </label>
      </div>

      {members.length === 0 ? <EmptyState title="Aucun collaborateur" description="Aucun collaborateur ne correspond à ces critères." /> : (
        <div className="overflow-x-auto rounded-[22px] border border-transparent bg-card shadow-card dark:border-border">
          <table className="w-full min-w-[920px] text-sm">
            <caption className="sr-only">TJM des collaborateurs de {data.workspace.name}</caption>
            <thead className="border-b bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>{["", "Collaborateur", "Niveau", "Coût / jour", "Vente / jour", "Marge sur coût", "Période", `Heures (${data.hours_window} j)`, ""].map((h, i) =>
                <th key={`${h}-${i}`} scope="col" className="px-4 py-3 font-semibold">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y">
              {members.map((m) => {
                const expanded = open === m.user_id && m.rates.length > 0;
                const r = m.current;
                return (
                  <Fragment key={m.user_id}>
                    <tr className="hover:bg-muted/40">
                      <td className="w-10 px-2 py-2.5">
                        {m.rates.length > 0 && (
                          <Button size="icon" variant="ghost" className="size-7" aria-expanded={expanded}
                            aria-label={`${expanded ? "Masquer" : "Afficher"} l'historique des tarifs de ${m.name}`} onClick={() => setOpen(expanded ? null : m.user_id)}>
                            {expanded ? <ChevronDown /> : <ChevronRight />}
                          </Button>
                        )}
                      </td>
                      <td className="px-4 py-2.5">
                        <p className="font-medium">{m.name}</p>
                        {(m.job_title || m.team) && <p className="text-xs text-muted-foreground">{[m.job_title, m.team].filter(Boolean).join(" · ")}</p>}
                      </td>
                      {r ? (
                        <>
                          <td className="px-4 py-2.5">{r.worker_level_label}</td>
                          <td className="px-4 py-2.5 whitespace-nowrap font-semibold tabular-nums">{formatMoney(r.daily_cost, r.currency || c)}</td>
                          <td className="px-4 py-2.5 whitespace-nowrap tabular-nums">{Number(r.daily_sale) > 0 ? formatMoney(r.daily_sale, r.currency || c) : "—"}</td>
                          <td className="px-4 py-2.5 whitespace-nowrap tabular-nums">{r.margin_percent != null ? `${formatNumber(r.margin_percent)} %` : "—"}</td>
                          <td className="px-4 py-2.5 whitespace-nowrap text-muted-foreground">{period(r)}</td>
                        </>
                      ) : (
                        <td colSpan={5} className="px-4 py-2.5">
                          <span className={cn("inline-flex items-center gap-1.5", m.home && "text-warning")}>
                            {m.home && <AlertTriangle className="size-4" aria-hidden="true" />}{missingLabel(m, c)}
                          </span>
                        </td>
                      )}
                      <td className="px-4 py-2.5 whitespace-nowrap tabular-nums">
                        {formatHours(m.hours_30d)}
                        {m.unvalued_entries > 0 && <Badge className="ml-2 bg-warning/15 text-warning">{m.unvalued_entries} à 0</Badge>}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        {data.can_manage && (() => {
                          const label = r ? "Nouveau tarif" : m.home ? "Définir le TJM" : "Tarif projet";
                          return (
                            <Button size="sm" variant={r || !m.home ? "outline" : "default"} onClick={() => setEditing({ member: m })} aria-label={`${label} pour ${m.name}`}>
                              <Plus />{label}
                            </Button>
                          );
                        })()}
                      </td>
                    </tr>
                    {expanded && (
                      <tr className="bg-muted/40">
                        <td colSpan={9} className="px-6 py-4">
                          <h4 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground"><History className="size-3.5" aria-hidden="true" />Historique des tarifs</h4>
                          <ul className="space-y-2" aria-label={`Tarifs de ${m.name}`}>
                            {m.rates.map((rate) => (
                              <li key={rate.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl bg-card px-3 py-2 text-sm">
                                <Badge className={STATUS[rate.status].className}>{STATUS[rate.status].label}</Badge>
                                <span className="whitespace-nowrap">{period(rate)}</span>
                                <span className="text-muted-foreground">{rate.project ? `Projet ${rate.project.name}` : "Tous les projets"}</span>
                                <span className="whitespace-nowrap tabular-nums">Coût {formatMoney(rate.cost_rate_amount, rate.currency)} / {per(rate)}</span>
                                <span className="whitespace-nowrap tabular-nums">Vente {Number(rate.sale_rate_amount) > 0 ? `${formatMoney(rate.sale_rate_amount, rate.currency)} / ${per(rate)}` : "—"}</span>
                                {data.can_manage && (
                                  <span className="ml-auto flex gap-1">
                                    <Button size="sm" variant="ghost" onClick={() => setEditing({ member: m, rate })} aria-label={`Modifier le tarif du ${formatDate(rate.valid_from)} de ${m.name}`}><Pencil />Modifier</Button>
                                    <Button size="sm" variant="ghost" onClick={() => setRemoving({ member: m, rate })} aria-label={`Supprimer le tarif du ${formatDate(rate.valid_from)} de ${m.name}`}><Trash2 />Supprimer</Button>
                                  </span>
                                )}
                              </li>
                            ))}
                          </ul>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {!data.can_manage && <p className="text-xs text-muted-foreground">Consultation seule : la modification des TJM est réservée aux personnes autorisées à gérer la facturation.</p>}

      {editing && <RateDialog board={data} member={editing.member} rate={editing.rate} workspace={workspace} onClose={() => setEditing(null)} />}
      {removing && <RemoveDialog member={removing.member} rate={removing.rate} workspace={workspace} onClose={() => setRemoving(null)} />}
    </div>
  );
}

function RateDialog({ board, member, rate, workspace, onClose }: {
  board: RatesBoard; member: RateMember; rate?: Rate; workspace: number; onClose: () => void;
}) {
  const save = useSaveRate(workspace);
  const base = rate ?? member.current;
  // Premier TJM : depuis le début de l'année (heures déjà saisies) ; jamais à l'intérieur d'une
  // période terminée : au plus tôt le lendemain de la dernière fin.
  const lastEnd = member.rates.filter((r) => !r.project && r.valid_to && r.valid_to < board.today)
    .reduce<string | null>((max, r) => (!max || r.valid_to! > max ? r.valid_to! : max), null);
  const yearStart = `${board.today.slice(0, 4)}-01-01`;
  const firstStart = lastEnd && nextDay(lastEnd) > yearStart ? nextDay(lastEnd) : yearStart;
  const defaultStart = rate ? rate.valid_from : member.current ? board.today : firstStart;
  const [form, setForm] = useState({
    worker_level: base?.worker_level ?? "OTHER",
    unit: base?.unit ?? "DAILY",
    currency: base?.currency ?? board.currency,
    cost_rate_amount: base ? String(Number(base.cost_rate_amount)) : "",
    sale_rate_amount: base ? String(Number(base.sale_rate_amount)) : "",
    valid_from: defaultStart,
    valid_to: rate?.valid_to ?? "",
    project: rate?.project ? String(rate.project.id) : member.home ? "" : String(board.projects[0]?.id ?? ""),
    revalue: member.rates.length === 0 || member.unvalued_entries > 0,
  });
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }));
  const [errors, setErrors] = useState<Record<string, string>>({});

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setErrors({});
    const body: RatePayload = {
      ...(rate ? {} : { user: member.user_id }),
      worker_level: form.worker_level, unit: form.unit, currency: form.currency,
      cost_rate_amount: form.cost_rate_amount, sale_rate_amount: form.sale_rate_amount || "0",
      valid_from: form.valid_from, valid_to: form.valid_to || null,
      project: form.project ? Number(form.project) : null, revalue: form.revalue,
    };
    save.mutate({ id: rate?.id, body }, {
      onSuccess: (res) => {
        const n = res.revalued?.entries;
        toast.success(`Tarif de ${member.name} enregistré${n ? ` · ${n} saisie(s) revalorisée(s)` : ""}.`);
        onClose();
      },
      onError: (err) => {
        const data = (err as { data?: Record<string, string[] | string> }).data;
        if (data && typeof data === "object") {
          const mapped = Object.fromEntries(Object.entries(data).map(([k, v]) => [k, [v].flat().join(" ")]));
          const detail = Object.entries(mapped).filter(([k]) => !SHOWN.has(k)).map(([, v]) => v).join(" ");
          setErrors({ ...mapped, detail });
        } else toast.error(err.message);
      },
    });
  };

  const field = (name: string) => errors[name] && <p id={`rate-${name}-error`} className="mt-1 text-xs text-destructive">{errors[name]}</p>;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} className="sm:max-w-xl"
      title={rate ? `Modifier le tarif de ${member.name}` : member.current ? `Nouveau tarif pour ${member.name}` : `Définir le TJM de ${member.name}`}
      description={rate ? "Correction du tarif sur sa période." : "Le tarif en vigueur sera clos la veille de la date de début."}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        {errors.detail && <p role="alert" className="rounded-xl bg-destructive/5 p-3 text-sm text-destructive">{errors.detail}</p>}
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm">Niveau
            <Select className="mt-1" value={form.worker_level} onChange={(e) => set({ worker_level: e.target.value })}>
              {board.levels.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
            </Select>
          </label>
          <label className="text-sm">Unité
            <Select className="mt-1" value={form.unit} onChange={(e) => set({ unit: e.target.value })}>
              {board.units.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
            </Select>
          </label>
          <label className="text-sm">Coût interne ({form.currency})
            <Input className="mt-1" type="number" min="0" step="any" required inputMode="decimal" value={form.cost_rate_amount}
              aria-invalid={!!errors.cost_rate_amount} onChange={(e) => set({ cost_rate_amount: e.target.value })} />
            {field("cost_rate_amount")}
          </label>
          <label className="text-sm">Tarif de vente ({form.currency})
            <Input className="mt-1" type="number" min="0" step="any" inputMode="decimal" value={form.sale_rate_amount} placeholder="Facultatif"
              aria-invalid={!!errors.sale_rate_amount} onChange={(e) => set({ sale_rate_amount: e.target.value })} />
            {field("sale_rate_amount")}
          </label>
          <label className="text-sm">À partir du
            <Input className="mt-1" type="date" required value={form.valid_from} aria-invalid={!!errors.valid_from} onChange={(e) => set({ valid_from: e.target.value })} />
            {field("valid_from")}
          </label>
          <label className="text-sm">Jusqu'au <span className="text-muted-foreground">(facultatif)</span>
            <Input className="mt-1" type="date" value={form.valid_to} aria-invalid={!!errors.valid_to} onChange={(e) => set({ valid_to: e.target.value })} />
            {field("valid_to")}
          </label>
          <label className="text-sm sm:col-span-2">S'applique à
            <Select className="mt-1" value={form.project} onChange={(e) => set({ project: e.target.value })} disabled={!!rate}>
              {member.home && <option value="">Tous les projets (TJM général)</option>}
              {board.projects.map((p) => <option key={p.id} value={p.id}>Projet {p.name} uniquement</option>)}
              {rate?.project && !board.projects.some((p) => p.id === rate.project!.id) && (
                <option value={rate.project.id}>Projet {rate.project.name} uniquement (archivé)</option>
              )}
            </Select>
            {!member.home && <p className="mt-1 text-xs text-muted-foreground">Le TJM général de {member.name} est géré par son espace de travail principal.</p>}
            {field("project")}
          </label>
        </div>
        <label className={cn("flex items-start gap-3 rounded-xl border p-3 text-sm", form.revalue && "border-primary/40 bg-primary/5")}>
          <input type="checkbox" className="mt-0.5 size-4 accent-primary" checked={form.revalue} onChange={(e) => set({ revalue: e.target.checked })} />
          <span>
            <span className="font-medium">Revaloriser les heures déjà saisies à partir du {form.valid_from ? formatDate(form.valid_from) : "début"}</span>
            <span className="mt-0.5 block text-xs text-muted-foreground">Recalcule leur coût avec ce tarif. Sinon, seules les prochaines saisies l'utilisent.</span>
          </span>
        </label>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>Annuler</Button>
          <Button type="submit" disabled={save.isPending || !form.cost_rate_amount || !form.valid_from}>{save.isPending ? "Enregistrement…" : "Enregistrer"}</Button>
        </div>
      </form>
    </Dialog>
  );
}

function RemoveDialog({ member, rate, workspace, onClose }: { member: RateMember; rate: Rate; workspace: number; onClose: () => void }) {
  const archive = useArchiveRate(workspace);
  return (
    <ConfirmDialog open onOpenChange={(o) => !o && onClose()} destructive pending={archive.isPending}
      title={`Supprimer le tarif de ${member.name} ?`}
      description={`Tarif ${period(rate)} (${formatMoney(rate.cost_rate_amount, rate.currency)}). Les heures de cette période seront revalorisées avec le tarif restant applicable (ou à 0).`}
      confirmLabel="Supprimer et revaloriser"
      onConfirm={() => archive.mutate({ id: rate.id, revalue: true }, {
        onSuccess: (res) => { toast.success(`Tarif supprimé${res.revalued?.entries ? ` · ${res.revalued.entries} saisie(s) revalorisée(s)` : ""}.`); onClose(); },
        onError: (err) => toast.error(err.message),
      })} />
  );
}
