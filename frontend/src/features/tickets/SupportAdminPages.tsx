import { Copy, KeyRound, Pencil, Plus, RefreshCw, Trash2, Webhook } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { useMe } from "@/features/auth/api";
import { WidgetHeader } from "@/features/dashboard/widgets";
import { formatDateTime } from "@/lib/format";
import { can } from "@/lib/permissions";
import { api } from "@/services/api";
import {
  useConfigDelete, useConfigList, useConfigSave, useDeliveries, useWorkspaceOptions, type ExternalApp, type RoutingRule, type SlaPolicy,
} from "./api";
import { CATEGORIES, PRIORITIES, SEVERITIES, WEBHOOK_EVENTS } from "./constants";

type Option = { id: number; name: string };

const numberField = (v: string) => (v === "" ? null : Number(v));

export function Header({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <PageHeader eyebrow="Support" title={title} description={description} actions={(
      <div className="flex flex-wrap gap-2">
        <Button asChild variant="outline" size="sm"><Link to="/tickets">Ticket Center</Link></Button>
        <Button asChild variant="outline" size="sm"><Link to="/tickets/list">Tickets</Link></Button>
        {action}
      </div>
    )} />
  );
}

// ─── Applications connectées ─────────────────────────────────────────────────

export function SecretDialog({ value, onClose }: { value: { key_id: string; secret: string } | null; onClose: () => void }) {
  const copy = (text: string) => void navigator.clipboard?.writeText(text).then(() => toast.success("Copié."));
  return (
    <Dialog open={value != null} onOpenChange={(o) => !o && onClose()} title="Identifiants d'intégration"
      description="Le secret n'est affiché qu'une seule fois. Stockez-le dans le coffre-fort du backend de l'application (jamais dans un navigateur ou une application mobile).">
      {value && (
        <div className="space-y-3">
          {([["Identifiant (X-DevFlow-App)", value.key_id], ["Secret", value.secret]] as const).map(([label, v]) => (
            <div key={label}>
              <p className="text-xs font-semibold text-muted-foreground">{label}</p>
              <div className="mt-1 flex items-center gap-2">
                <code className="min-w-0 flex-1 break-all rounded-xl bg-muted px-3 py-2 text-xs">{v}</code>
                <Button type="button" variant="outline" size="icon" onClick={() => copy(v)} aria-label={`Copier ${label}`}><Copy /></Button>
              </div>
            </div>
          ))}
          <div className="flex justify-end"><Button onClick={onClose}>J'ai enregistré le secret</Button></div>
        </div>
      )}
    </Dialog>
  );
}

function AppForm({ app, workspace, onDone }: { app: Partial<ExternalApp> | null; workspace: number; onDone: (created?: ExternalApp) => void }) {
  const { projects, teams } = useWorkspaceOptions(workspace);
  const policies = useConfigList<SlaPolicy>("ticket-sla-policies", workspace);
  const save = useConfigSave<ExternalApp>("ticket-applications");
  const [f, setF] = useState<Partial<ExternalApp>>(() => ({
    workspace, environment: "PRODUCTION", status: "ACTIVE", teams: [], webhook_events: [], rate_limit_per_minute: 60,
    daily_ticket_quota: 500, max_attachment_mb: 10, ...app,
  }));
  const set = (patch: Partial<ExternalApp>) => setF((x) => ({ ...x, ...patch }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate(f, {
      onSuccess: (saved) => { toast.success(app?.id ? "Application mise à jour." : "Application créée."); onDone(saved); },
      onError: (err) => toast.error(err.message),
    });
  };
  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
      <Field id="app-name" label="Nom"><Input id="app-name" required maxLength={120} value={f.name ?? ""} onChange={(e) => set({ name: e.target.value })} /></Field>
      <Field id="app-code" label="Code (slug)"><Input id="app-code" required pattern="[a-z0-9-]+" maxLength={60} value={f.code ?? ""} onChange={(e) => set({ code: e.target.value })} /></Field>
      <Field id="app-env" label="Environnement">
        <Select id="app-env" value={f.environment} onChange={(e) => set({ environment: e.target.value })}>
          {[["PRODUCTION", "Production"], ["STAGING", "Pré-production"], ["TEST", "Test"], ["DEVELOPMENT", "Développement"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </Select>
      </Field>
      <Field id="app-status" label="Statut">
        <Select id="app-status" value={f.status} onChange={(e) => set({ status: e.target.value })}>
          <option value="ACTIVE">Active</option><option value="SUSPENDED">Suspendue</option><option value="ARCHIVED">Archivée</option>
        </Select>
      </Field>
      <Field id="app-project" label="Projet DevFlow associé">
        <Select id="app-project" value={f.project ?? ""} onChange={(e) => set({ project: numberField(e.target.value) })}>
          <option value="">—</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </Select>
      </Field>
      <Field id="app-team" label="Équipe par défaut">
        <Select id="app-team" value={f.default_team ?? ""} onChange={(e) => set({ default_team: numberField(e.target.value) })}>
          <option value="">— File non assignée —</option>{teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </Select>
      </Field>
      <Field id="app-sla" label="Politique SLA">
        <Select id="app-sla" value={f.sla_policy ?? ""} onChange={(e) => set({ sla_policy: numberField(e.target.value) })}>
          <option value="">Politique par défaut du workspace</option>
          {(policies.data?.results ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </Select>
      </Field>
      <Field id="app-webhook" label="URL du webhook (HTTPS)" hint="Adresses privées refusées (protection SSRF).">
        <Input id="app-webhook" type="url" value={f.webhook_url ?? ""} onChange={(e) => set({ webhook_url: e.target.value })} placeholder="https://api.mon-app.com/devflow/webhooks" />
      </Field>
      <fieldset className="sm:col-span-2">
        <legend className="mb-1.5 text-xs font-semibold text-muted-foreground">Équipes responsables</legend>
        <div className="flex flex-wrap gap-2">
          {teams.map((t) => {
            const on = (f.teams ?? []).includes(t.id);
            return (
              <label key={t.id} className="inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs">
                <input type="checkbox" checked={on} onChange={() => set({ teams: on ? f.teams!.filter((x) => x !== t.id) : [...(f.teams ?? []), t.id] })} />{t.name}
              </label>
            );
          })}
        </div>
      </fieldset>
      <fieldset className="sm:col-span-2">
        <legend className="mb-1.5 text-xs font-semibold text-muted-foreground">Événements envoyés (aucun coché = tous)</legend>
        <div className="flex flex-wrap gap-2">
          {WEBHOOK_EVENTS.map((ev) => {
            const on = (f.webhook_events ?? []).includes(ev);
            return (
              <label key={ev} className="inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs">
                <input type="checkbox" checked={on} onChange={() => set({ webhook_events: on ? f.webhook_events!.filter((x) => x !== ev) : [...(f.webhook_events ?? []), ev] })} />{ev}
              </label>
            );
          })}
        </div>
      </fieldset>
      <Field id="app-rate" label="Requêtes / minute"><Input id="app-rate" type="number" min={1} max={600} value={f.rate_limit_per_minute ?? 60} onChange={(e) => set({ rate_limit_per_minute: Number(e.target.value) })} /></Field>
      <Field id="app-quota" label="Tickets / jour"><Input id="app-quota" type="number" min={1} value={f.daily_ticket_quota ?? 500} onChange={(e) => set({ daily_ticket_quota: Number(e.target.value) })} /></Field>
      <Field id="app-mb" label="Taille max. pièce jointe (Mo)"><Input id="app-mb" type="number" min={1} max={50} value={f.max_attachment_mb ?? 10} onChange={(e) => set({ max_attachment_mb: Number(e.target.value) })} /></Field>
      <Field id="app-retention" label="Conservation des données déclarant (jours)" hint="Vide = conserver.">
        <Input id="app-retention" type="number" min={1} value={f.retention_days ?? ""} onChange={(e) => set({ retention_days: numberField(e.target.value) })} />
      </Field>
      <div className="flex justify-end gap-2 sm:col-span-2">
        <Button type="button" variant="outline" onClick={() => onDone()}>Annuler</Button>
        <Button type="submit" disabled={save.isPending}>{app?.id ? "Enregistrer" : "Créer l'application"}</Button>
      </div>
    </form>
  );
}

function Deliveries({ appId }: { appId: number }) {
  const { data, isPending, refetch } = useDeliveries(appId);
  const retry = async (id: number) => {
    try { await api(`ticket-applications/${appId}/deliveries/${id}/retry/`, { method: "POST" }); toast.success("Nouvel essai planifié."); void refetch(); }
    catch (e) { toast.error((e as Error).message); }
  };
  if (isPending) return <p className="text-sm text-muted-foreground">Chargement…</p>;
  if (!data?.length) return <p className="text-sm text-muted-foreground">Aucune livraison pour l'instant.</p>;
  return (
    <ul className="divide-y text-sm">
      {data.map((d) => (
        <li key={d.id} className="flex flex-wrap items-center gap-3 py-2">
          <code className="text-xs">{d.event}</code><span className="text-xs text-muted-foreground">{d.ticket}</span>
          <span className={d.status === "SUCCESS" ? "text-xs font-semibold text-success" : d.status === "DEAD" ? "text-xs font-semibold text-destructive" : "text-xs font-semibold text-warning"}>
            {d.status_label} · essai {d.attempt}{d.response_status ? ` · HTTP ${d.response_status}` : ""}
          </span>
          {d.error && <span className="truncate text-xs text-muted-foreground" title={d.error}>{d.error}</span>}
          <span className="ml-auto text-xs text-muted-foreground">{formatDateTime(d.created_at)}</span>
          {(d.status === "FAILED" || d.status === "DEAD") && <Button size="sm" variant="ghost" onClick={() => void retry(d.id)}><RefreshCw />Relancer</Button>}
        </li>
      ))}
    </ul>
  );
}

export function ApplicationsPage() {
  const { data: me } = useMe();
  const workspace = me?.workspace?.id;
  const admin = can(me?.permissions, "ticket.admin");
  const { data, isPending, isError, error, refetch } = useConfigList<ExternalApp>("ticket-applications", workspace);
  const [editing, setEditing] = useState<Partial<ExternalApp> | null>(null);
  const [secret, setSecret] = useState<{ key_id: string; secret: string } | null>(null);
  const [rotate, setRotate] = useState<ExternalApp | null>(null);
  const [logs, setLogs] = useState<number | null>(null);
  if (!workspace) return <EmptyState title="Aucun workspace" />;
  const doRotate = async () => {
    if (!rotate) return;
    try {
      const r = await api<{ key_id: string; secret: string }>(`ticket-applications/${rotate.id}/rotate-secret/`, { method: "POST" });
      setRotate(null); setSecret(r); void refetch();
    } catch (e) { toast.error((e as Error).message); }
  };
  return (
    <div className="space-y-5">
      <Header title="Applications connectées" description="Applications autorisées à déclarer des tickets (signature HMAC) et à recevoir les webhooks."
        action={admin && <Button size="sm" onClick={() => setEditing({})}><Plus />Nouvelle application</Button>} />
      {isPending ? <PageSkeleton /> : isError ? <ErrorState message={error.message} onRetry={() => void refetch()} /> : !data.results.length ? (
        <EmptyState title="Aucune application" description="Connectez une première application pour recevoir ses tickets." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {data.results.map((a) => (
            <Card key={a.id} className="p-5 sm:p-6">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="truncate text-[17px] font-semibold tracking-tight">{a.name}</h2>
                  <p className="text-xs text-muted-foreground">{a.code} · {a.environment.toLowerCase()} · {a.status === "ACTIVE" ? "active" : a.status.toLowerCase()}</p>
                </div>
                <Link to={`/tickets/list?open=1&application=${a.id}`} className="shrink-0 rounded-full bg-primary-faint px-3 py-1 text-xs font-semibold text-brand">{a.open_tickets} ouvert(s)</Link>
              </div>
              <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
                <dt className="text-muted-foreground">Identifiant</dt><dd className="break-all font-mono">{a.key_id}</dd>
                <dt className="text-muted-foreground">Secret</dt><dd>••••{a.secret_last4}{a.secret_rotated_at ? ` · renouvelé le ${formatDateTime(a.secret_rotated_at)}` : ""}</dd>
                <dt className="text-muted-foreground">Webhook</dt><dd className="break-all">{a.webhook_url || "—"}</dd>
                <dt className="text-muted-foreground">Limites</dt><dd>{a.rate_limit_per_minute} req/min · {a.daily_ticket_quota} tickets/j · {a.max_attachment_mb} Mo</dd>
              </dl>
              <div className="mt-4 flex flex-wrap gap-2">
                {admin && <Button size="sm" variant="outline" onClick={() => setEditing(a)}><Pencil />Modifier</Button>}
                {admin && <Button size="sm" variant="outline" onClick={() => setRotate(a)}><KeyRound />Renouveler le secret</Button>}
                <Button size="sm" variant="ghost" onClick={() => setLogs(logs === a.id ? null : a.id)} aria-expanded={logs === a.id}><Webhook />Livraisons</Button>
              </div>
              {logs === a.id && <div className="mt-4 border-t pt-3"><Deliveries appId={a.id} /></div>}
            </Card>
          ))}
        </div>
      )}
      <Dialog open={editing != null} onOpenChange={(o) => !o && setEditing(null)} title={editing?.id ? "Modifier l'application" : "Nouvelle application"} className="sm:max-w-2xl">
        {editing && <AppForm app={editing} workspace={workspace} onDone={(created) => {
          setEditing(null);
          if (created?.secret) setSecret({ key_id: created.key_id, secret: created.secret });
        }} />}
      </Dialog>
      <SecretDialog value={secret} onClose={() => setSecret(null)} />
      <ConfirmDialog open={rotate != null} onOpenChange={(o) => !o && setRotate(null)} destructive title="Renouveler le secret ?"
        description="L'ancien secret cesse immédiatement de fonctionner : mettez à jour le backend de l'application juste après."
        confirmLabel="Renouveler" onConfirm={() => void doRotate()} />
    </div>
  );
}

// ─── Routage & SLA ───────────────────────────────────────────────────────────

function RuleForm({ rule, workspace, onDone }: { rule: Partial<RoutingRule>; workspace: number; onDone: () => void }) {
  const { teams } = useWorkspaceOptions(workspace);
  const apps = useConfigList<ExternalApp>("ticket-applications", workspace);
  const save = useConfigSave<RoutingRule>("ticket-routing-rules");
  const [f, setF] = useState<Partial<RoutingRule>>({ workspace, category: "", severity: "", priority_override: "", position: 100, is_active: true, auto_assign: false, ...rule });
  const set = (p: Partial<RoutingRule>) => setF((x) => ({ ...x, ...p }));
  return (
    <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => {
      e.preventDefault();
      save.mutate(f, { onSuccess: () => { toast.success("Règle enregistrée."); onDone(); }, onError: (err) => toast.error(err.message) });
    }}>
      <Field id="rule-name" label="Nom"><Input id="rule-name" required value={f.name ?? ""} onChange={(e) => set({ name: e.target.value })} /></Field>
      <Field id="rule-position" label="Ordre d'évaluation"><Input id="rule-position" type="number" min={0} value={f.position ?? 100} onChange={(e) => set({ position: Number(e.target.value) })} /></Field>
      <Field id="rule-app" label="Application">
        <Select id="rule-app" value={f.application ?? ""} onChange={(e) => set({ application: numberField(e.target.value) })}>
          <option value="">Toutes</option>{(apps.data?.results ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </Select>
      </Field>
      <Field id="rule-cat" label="Catégorie">
        <Select id="rule-cat" value={f.category ?? ""} onChange={(e) => set({ category: e.target.value })}>
          <option value="">Toutes</option>{CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </Select>
      </Field>
      <Field id="rule-sev" label="Gravité">
        <Select id="rule-sev" value={f.severity ?? ""} onChange={(e) => set({ severity: e.target.value })}>
          <option value="">Toutes</option>{SEVERITIES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </Select>
      </Field>
      <Field id="rule-team" label="Équipe responsable">
        <Select id="rule-team" required value={f.team ?? ""} onChange={(e) => set({ team: Number(e.target.value) })}>
          <option value="">— Choisir —</option>{teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </Select>
      </Field>
      <Field id="rule-prio" label="Priorité imposée">
        <Select id="rule-prio" value={f.priority_override ?? ""} onChange={(e) => set({ priority_override: e.target.value })}>
          <option value="">Selon la gravité</option>{PRIORITIES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </Select>
      </Field>
      <div className="flex flex-col justify-end gap-2 text-sm">
        <label className="inline-flex items-center gap-2"><input type="checkbox" checked={Boolean(f.auto_assign)} onChange={(e) => set({ auto_assign: e.target.checked })} />Affecter automatiquement (agent le moins chargé)</label>
        <label className="inline-flex items-center gap-2"><input type="checkbox" checked={f.is_active !== false} onChange={(e) => set({ is_active: e.target.checked })} />Règle active</label>
      </div>
      <div className="flex justify-end gap-2 sm:col-span-2">
        <Button type="button" variant="outline" onClick={onDone}>Annuler</Button><Button type="submit" disabled={save.isPending}>Enregistrer</Button>
      </div>
    </form>
  );
}

const DAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const DEFAULT_TARGETS = { P1: { first_response: 30, resolution: 240 }, P2: { first_response: 120, resolution: 960 },
  P3: { first_response: 480, resolution: 2400 }, P4: { first_response: 1440, resolution: 7200 } };

function PolicyForm({ policy, workspace, onDone }: { policy: Partial<SlaPolicy>; workspace: number; onDone: () => void }) {
  const { teams } = useWorkspaceOptions(workspace);
  const save = useConfigSave<SlaPolicy>("ticket-sla-policies");
  const [f, setF] = useState<Partial<SlaPolicy>>({
    workspace, targets: DEFAULT_TARGETS, business_hours_only: true, business_start: "08:00", business_end: "18:00",
    business_days: [0, 1, 2, 3, 4], timezone: "Africa/Abidjan", warn_before_percent: 80, auto_escalate: true, is_default: false, ...policy,
  });
  const set = (p: Partial<SlaPolicy>) => setF((x) => ({ ...x, ...p }));
  const target = (prio: string, key: "first_response" | "resolution", v: number) =>
    set({ targets: { ...f.targets, [prio]: { ...(f.targets?.[prio] ?? DEFAULT_TARGETS.P3), [key]: v } } });
  return (
    <form className="space-y-4" onSubmit={(e) => {
      e.preventDefault();
      save.mutate(f, { onSuccess: () => { toast.success("Politique SLA enregistrée."); onDone(); }, onError: (err) => toast.error(err.message) });
    }}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id="sla-name" label="Nom"><Input id="sla-name" required value={f.name ?? ""} onChange={(e) => set({ name: e.target.value })} /></Field>
        <Field id="sla-tz" label="Fuseau horaire"><Input id="sla-tz" required value={f.timezone ?? ""} onChange={(e) => set({ timezone: e.target.value })} /></Field>
      </div>
      <table className="w-full text-sm">
        <caption className="mb-1 text-left text-xs font-semibold text-muted-foreground">Délais (minutes ouvrées)</caption>
        <thead><tr className="text-left text-xs text-muted-foreground"><th className="py-1">Priorité</th><th>1re réponse</th><th>Résolution</th></tr></thead>
        <tbody>
          {PRIORITIES.map((p) => (
            <tr key={p.value}>
              <td className="py-1 pr-2">{p.label}</td>
              {(["first_response", "resolution"] as const).map((k) => (
                <td key={k} className="py-1 pr-2">
                  <Input aria-label={`${p.label} ${k === "first_response" ? "première réponse" : "résolution"}`} type="number" min={1}
                    value={f.targets?.[p.value]?.[k] ?? DEFAULT_TARGETS[p.value][k]} onChange={(e) => target(p.value, k, Number(e.target.value))} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field id="sla-start" label="Début de service"><Input id="sla-start" type="time" value={f.business_start ?? "08:00"} onChange={(e) => set({ business_start: e.target.value })} /></Field>
        <Field id="sla-end" label="Fin de service"><Input id="sla-end" type="time" value={f.business_end ?? "18:00"} onChange={(e) => set({ business_end: e.target.value })} /></Field>
        <Field id="sla-warn" label="Alerte à (% du délai)"><Input id="sla-warn" type="number" min={10} max={99} value={f.warn_before_percent ?? 80} onChange={(e) => set({ warn_before_percent: Number(e.target.value) })} /></Field>
      </div>
      <fieldset>
        <legend className="mb-1.5 text-xs font-semibold text-muted-foreground">Jours ouvrés</legend>
        <div className="flex flex-wrap gap-2">
          {DAYS.map((d, i) => {
            const on = (f.business_days ?? []).includes(i);
            return <label key={d} className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs"><input type="checkbox" checked={on}
              onChange={() => set({ business_days: on ? f.business_days!.filter((x) => x !== i) : [...(f.business_days ?? []), i].sort() })} />{d}</label>;
          })}
        </div>
      </fieldset>
      <Field id="sla-esc" label="Équipe d'escalade">
        <Select id="sla-esc" value={f.escalation_team ?? ""} onChange={(e) => set({ escalation_team: numberField(e.target.value) })}>
          <option value="">—</option>{teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </Select>
      </Field>
      <div className="flex flex-wrap gap-4 text-sm">
        <label className="inline-flex items-center gap-2"><input type="checkbox" checked={Boolean(f.business_hours_only)} onChange={(e) => set({ business_hours_only: e.target.checked })} />Heures ouvrées uniquement</label>
        <label className="inline-flex items-center gap-2"><input type="checkbox" checked={Boolean(f.auto_escalate)} onChange={(e) => set({ auto_escalate: e.target.checked })} />Escalade automatique au dépassement</label>
        <label className="inline-flex items-center gap-2"><input type="checkbox" checked={Boolean(f.is_default)} onChange={(e) => set({ is_default: e.target.checked })} />Politique par défaut</label>
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onDone}>Annuler</Button><Button type="submit" disabled={save.isPending}>Enregistrer</Button>
      </div>
    </form>
  );
}

export function SupportSettingsPage() {
  const { data: me } = useMe();
  const workspace = me?.workspace?.id;
  const admin = can(me?.permissions, "ticket.admin");
  const rules = useConfigList<RoutingRule>("ticket-routing-rules", workspace);
  const policies = useConfigList<SlaPolicy>("ticket-sla-policies", workspace);
  const { teams } = useWorkspaceOptions(workspace);
  const apps = useConfigList<ExternalApp>("ticket-applications", workspace);
  const removeRule = useConfigDelete("ticket-routing-rules");
  const removePolicy = useConfigDelete("ticket-sla-policies");
  const [rule, setRule] = useState<Partial<RoutingRule> | null>(null);
  const [policy, setPolicy] = useState<Partial<SlaPolicy> | null>(null);
  if (!workspace) return <EmptyState title="Aucun workspace" />;
  const name = (list: Option[] | { id: number; name: string }[], id: number | null) => list.find((x) => x.id === id)?.name ?? "Toutes";
  const del = (m: typeof removeRule, id: number) => m.mutate(id, { onSuccess: () => toast.success("Supprimé."), onError: (e) => toast.error(e.message) });
  return (
    <div className="space-y-5">
      <Header title="Routage & SLA" description="Application + catégorie + gravité → équipe ; délais de service, heures ouvrées et escalade."
        action={admin && <Button asChild variant="outline" size="sm"><Link to="/tickets/email">Canaux e-mail</Link></Button>} />
      <Card className="p-5 sm:p-6">
        <WidgetHeader title="Règles de routage" meta="évaluées par ordre croissant, première règle applicable"
          action={admin && <Button size="sm" onClick={() => setRule({})}><Plus />Règle</Button>} />
        {rules.isPending ? <p className="mt-3 text-sm text-muted-foreground">Chargement…</p> : !rules.data?.results.length ? (
          <p className="mt-3 text-sm text-muted-foreground">Aucune règle : les tickets vont à l'équipe par défaut de l'application, sinon en file non assignée.</p>
        ) : (
          <ul className="mt-3 divide-y text-sm">
            {rules.data.results.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3 py-2.5">
                <span className="w-10 text-xs text-muted-foreground">#{r.position}</span>
                <span className="font-medium">{r.name}</span>
                <span className="text-xs text-muted-foreground">
                  {name(apps.data?.results ?? [], r.application)} · {CATEGORIES.find((c) => c.value === r.category)?.label ?? "toutes catégories"} · {SEVERITIES.find((s) => s.value === r.severity)?.label ?? "toutes gravités"} → <strong>{name(teams, r.team)}</strong>
                  {r.auto_assign ? " · affectation auto" : ""}{r.priority_override ? ` · ${r.priority_override}` : ""}{r.is_active ? "" : " · inactive"}
                </span>
                {admin && <span className="ml-auto flex gap-1">
                  <Button size="icon" variant="ghost" aria-label={`Modifier ${r.name}`} onClick={() => setRule(r)}><Pencil /></Button>
                  <Button size="icon" variant="ghost" aria-label={`Supprimer ${r.name}`} onClick={() => del(removeRule, r.id)}><Trash2 /></Button>
                </span>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card className="p-5 sm:p-6">
        <WidgetHeader title="Politiques SLA" action={admin && <Button size="sm" onClick={() => setPolicy({})}><Plus />Politique</Button>} />
        {!policies.data?.results.length ? (
          <p className="mt-3 text-sm text-muted-foreground">Aucune politique : délais par défaut 24/7 (P1 : 30 min / 4 h, P2 : 2 h / 16 h, P3 : 8 h / 40 h, P4 : 24 h / 120 h).</p>
        ) : (
          <ul className="mt-3 divide-y text-sm">
            {policies.data.results.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-3 py-2.5">
                <span className="font-medium">{p.name}{p.is_default ? " (par défaut)" : ""}</span>
                <span className="text-xs text-muted-foreground">
                  {p.business_hours_only ? `${p.business_start.slice(0, 5)}–${p.business_end.slice(0, 5)} · ${p.business_days.map((d) => DAYS[d]).join(", ")}` : "24/7"} · {p.timezone} · alerte à {p.warn_before_percent} %{p.auto_escalate ? " · escalade auto" : ""}
                </span>
                {admin && <span className="ml-auto flex gap-1">
                  <Button size="icon" variant="ghost" aria-label={`Modifier ${p.name}`} onClick={() => setPolicy(p)}><Pencil /></Button>
                  <Button size="icon" variant="ghost" aria-label={`Supprimer ${p.name}`} onClick={() => del(removePolicy, p.id)}><Trash2 /></Button>
                </span>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Dialog open={rule != null} onOpenChange={(o) => !o && setRule(null)} title={rule?.id ? "Modifier la règle" : "Nouvelle règle de routage"} className="sm:max-w-2xl">
        {rule && <RuleForm rule={rule} workspace={workspace} onDone={() => setRule(null)} />}
      </Dialog>
      <Dialog open={policy != null} onOpenChange={(o) => !o && setPolicy(null)} title={policy?.id ? "Modifier la politique" : "Nouvelle politique SLA"} className="sm:max-w-2xl">
        {policy && <PolicyForm policy={policy} workspace={workspace} onDone={() => setPolicy(null)} />}
      </Dialog>
    </div>
  );
}
