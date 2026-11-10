import {
  AlertTriangle, CheckCircle2, Copy, Inbox, KeyRound, Loader2, Mail, Pencil, PlugZap, Plus, RefreshCw, RotateCcw, Webhook, XCircle,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { Pagination } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { useMe } from "@/features/auth/api";
import { formatDateTime } from "@/lib/format";
import { can } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import { useConfigList, useConfigSave, useMailMessages, useWorkspaceOptions, type ExternalApp, type Mailbox } from "./api";
import { CATEGORIES } from "./constants";
import { Header } from "./SupportAdminPages";

type ConnResult = { imap: { ok: boolean; detail: string } | null; smtp: { ok: boolean; detail: string } | null };

const list = (value: string) => value.split(/[\s,;]+/).map((x) => x.trim().toLowerCase()).filter(Boolean);
const secLabel = { SSL: "SSL/TLS", STARTTLS: "STARTTLS" } as const;

function MailboxForm({ box, workspace, onDone }: { box: Partial<Mailbox>; workspace: number; onDone: (saved?: Mailbox) => void }) {
  const { projects } = useWorkspaceOptions(workspace);
  const apps = useConfigList<ExternalApp>("ticket-applications", workspace);
  const save = useConfigSave<Mailbox>("ticket-mailboxes");
  const [f, setF] = useState<Partial<Mailbox>>(() => ({
    workspace, inbound: "IMAP", imap_port: 993, imap_security: "SSL", imap_folder: "INBOX", smtp_port: 465, smtp_security: "SSL",
    auto_acknowledge: true, default_category: "QUESTION", allowed_domains: [], blocked_senders: [], max_attachment_mb: 10, is_active: true, ...box,
  }));
  const [domains, setDomains] = useState((box.allowed_domains ?? []).join(", "));
  const [blocked, setBlocked] = useState((box.blocked_senders ?? []).join(", "));
  const set = (patch: Partial<Mailbox>) => setF((x) => ({ ...x, ...patch }));
  const imap = f.inbound === "IMAP";
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const payload: Partial<Mailbox> = { ...f, allowed_domains: list(domains), blocked_senders: list(blocked) };
    (["imap_password", "smtp_password"] as const).forEach((k) => { if (!payload[k]) delete payload[k]; });
    save.mutate(payload, {
      onSuccess: (saved) => { toast.success(box.id ? "Boîte mise à jour." : "Boîte créée."); onDone(saved); },
      onError: (err) => toast.error(err.message),
    });
  };
  return (
    <form onSubmit={submit} className="space-y-5">
      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="mb-2 text-xs font-bold uppercase tracking-[0.12em] text-brand">Boîte</legend>
        <Field id="mb-name" label="Nom"><Input id="mb-name" required maxLength={120} value={f.name ?? ""} onChange={(e) => set({ name: e.target.value })} /></Field>
        <Field id="mb-address" label="Adresse de support"><Input id="mb-address" type="email" required value={f.address ?? ""} onChange={(e) => set({ address: e.target.value })} placeholder="support@mon-entreprise.com" /></Field>
        <Field id="mb-app" label="Application associée">
          <Select id="mb-app" required value={f.application ?? ""} onChange={(e) => set({ application: Number(e.target.value) })}>
            <option value="">— Choisir —</option>{(apps.data?.results ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </Select>
        </Field>
        <Field id="mb-project" label="Projet (facultatif)">
          <Select id="mb-project" value={f.project ?? ""} onChange={(e) => set({ project: e.target.value ? Number(e.target.value) : null })}>
            <option value="">Projet de l'application</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </Field>
        <Field id="mb-from" label="Nom d'expéditeur des réponses"><Input id="mb-from" maxLength={120} value={f.from_name ?? ""} onChange={(e) => set({ from_name: e.target.value })} placeholder="Support DevFlow" /></Field>
        <Field id="mb-inbound" label="Réception">
          <Select id="mb-inbound" value={f.inbound} onChange={(e) => set({ inbound: e.target.value as Mailbox["inbound"] })}>
            <option value="IMAP">IMAP (relève toutes les 2 min)</option><option value="WEBHOOK">Webhook du fournisseur e-mail</option>
          </Select>
        </Field>
      </fieldset>

      {imap && (
        <fieldset className="grid gap-3 sm:grid-cols-3">
          <legend className="mb-2 text-xs font-bold uppercase tracking-[0.12em] text-brand">IMAP (TLS obligatoire)</legend>
          <div className="sm:col-span-2"><Field id="mb-ihost" label="Serveur"><Input id="mb-ihost" required value={f.imap_host ?? ""} onChange={(e) => set({ imap_host: e.target.value.trim() })} placeholder="imap.mon-fournisseur.com" /></Field></div>
          <Field id="mb-iport" label="Port"><Input id="mb-iport" type="number" min={1} max={65535} value={f.imap_port ?? 993} onChange={(e) => set({ imap_port: Number(e.target.value) })} /></Field>
          <Field id="mb-isec" label="Sécurité">
            <Select id="mb-isec" value={f.imap_security} onChange={(e) => set({ imap_security: e.target.value as Mailbox["imap_security"] })}>
              <option value="SSL">SSL/TLS (993)</option><option value="STARTTLS">STARTTLS (143)</option>
            </Select>
          </Field>
          <Field id="mb-iuser" label="Identifiant"><Input id="mb-iuser" required autoComplete="off" value={f.imap_username ?? ""} onChange={(e) => set({ imap_username: e.target.value })} /></Field>
          <Field id="mb-ipass" label="Mot de passe" hint={box.has_imap_password ? "Laisser vide pour conserver." : "Chiffré, jamais réaffiché."}>
            <Input id="mb-ipass" type="password" autoComplete="new-password" required={!box.has_imap_password} value={f.imap_password ?? ""}
              onChange={(e) => set({ imap_password: e.target.value })} placeholder={box.has_imap_password ? "••••••••" : ""} />
          </Field>
          <Field id="mb-folder" label="Dossier"><Input id="mb-folder" value={f.imap_folder ?? "INBOX"} onChange={(e) => set({ imap_folder: e.target.value })} /></Field>
        </fieldset>
      )}

      <fieldset className="grid gap-3 sm:grid-cols-3">
        <legend className="mb-2 text-xs font-bold uppercase tracking-[0.12em] text-brand">SMTP — envoi des réponses</legend>
        <p className="-mt-1 text-xs text-muted-foreground sm:col-span-3">Vide : envoi par la messagerie de DevFlow avec « Répondre à » = adresse de support.</p>
        <div className="sm:col-span-2"><Field id="mb-shost" label="Serveur"><Input id="mb-shost" value={f.smtp_host ?? ""} onChange={(e) => set({ smtp_host: e.target.value.trim() })} placeholder="smtp.mon-fournisseur.com" /></Field></div>
        <Field id="mb-sport" label="Port"><Input id="mb-sport" type="number" min={1} max={65535} value={f.smtp_port ?? 465} onChange={(e) => set({ smtp_port: Number(e.target.value) })} /></Field>
        <Field id="mb-ssec" label="Sécurité">
          <Select id="mb-ssec" value={f.smtp_security} onChange={(e) => set({ smtp_security: e.target.value as Mailbox["smtp_security"] })}>
            <option value="SSL">SSL/TLS (465)</option><option value="STARTTLS">STARTTLS (587)</option>
          </Select>
        </Field>
        <Field id="mb-suser" label="Identifiant"><Input id="mb-suser" autoComplete="off" value={f.smtp_username ?? ""} onChange={(e) => set({ smtp_username: e.target.value })} /></Field>
        <Field id="mb-spass" label="Mot de passe" hint={box.has_smtp_password ? "Laisser vide pour conserver." : undefined}>
          <Input id="mb-spass" type="password" autoComplete="new-password" value={f.smtp_password ?? ""} onChange={(e) => set({ smtp_password: e.target.value })}
            placeholder={box.has_smtp_password ? "••••••••" : ""} />
        </Field>
      </fieldset>

      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="mb-2 text-xs font-bold uppercase tracking-[0.12em] text-brand">Règles de réception</legend>
        <Field id="mb-cat" label="Catégorie des nouveaux tickets">
          <Select id="mb-cat" value={f.default_category} onChange={(e) => set({ default_category: e.target.value })}>
            {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </Select>
        </Field>
        <Field id="mb-mb" label="Taille max. pièce jointe (Mo)"><Input id="mb-mb" type="number" min={1} max={50} value={f.max_attachment_mb ?? 10} onChange={(e) => set({ max_attachment_mb: Number(e.target.value) })} /></Field>
        <Field id="mb-allowed" label="Domaines autorisés à créer des tickets" hint="Vide = tous. Séparés par des virgules (ex. client.com).">
          <Textarea id="mb-allowed" rows={2} value={domains} onChange={(e) => setDomains(e.target.value)} />
        </Field>
        <Field id="mb-blocked" label="Expéditeurs ou domaines bloqués" hint="Adresses ou domaines, séparés par des virgules.">
          <Textarea id="mb-blocked" rows={2} value={blocked} onChange={(e) => setBlocked(e.target.value)} />
        </Field>
        <div className="flex flex-wrap gap-4 text-sm sm:col-span-2">
          <label className="inline-flex items-center gap-2"><input type="checkbox" checked={Boolean(f.auto_acknowledge)} onChange={(e) => set({ auto_acknowledge: e.target.checked })} />Accusé de réception avec la référence</label>
          <label className="inline-flex items-center gap-2"><input type="checkbox" checked={f.is_active !== false} onChange={(e) => set({ is_active: e.target.checked })} />Boîte active</label>
        </div>
      </fieldset>

      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={() => onDone()}>Annuler</Button>
        <Button type="submit" disabled={save.isPending}>{save.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}{box.id ? "Enregistrer" : "Créer la boîte"}</Button>
      </div>
    </form>
  );
}

const STATUS_TONE: Record<string, string> = {
  PROCESSED: "text-success", SENT: "text-success", REJECTED: "text-destructive", DEAD: "text-destructive", FAILED: "text-warning",
  IGNORED: "text-muted-foreground", RECEIVED: "text-muted-foreground", PENDING: "text-muted-foreground",
};
const FILTERS = [["", "Tous"], ["REJECTED,DEAD,FAILED", "À traiter"], ["PROCESSED,SENT", "Traités"], ["IGNORED", "Ignorés"]] as const;

function MessageHistory({ box }: { box: Mailbox }) {
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const { data, isPending, refetch } = useMailMessages(box.id, status, page);
  const reprocess = async (id: number) => {
    try {
      await api(`ticket-mailboxes/${box.id}/messages/${id}/reprocess/`, { method: "POST" });
      toast.success("Message remis en traitement.");
      void refetch();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filtrer les messages">
        {FILTERS.map(([value, label]) => (
          <Button key={label} size="sm" variant={status === value ? "default" : "ghost"} aria-pressed={status === value}
            onClick={() => { setStatus(value); setPage(1); }}>{label}</Button>
        ))}
      </div>
      {isPending ? <p className="text-sm text-muted-foreground">Chargement…</p> : !data?.results.length ? (
        <p className="text-sm text-muted-foreground">Aucun message.</p>
      ) : (
        <ul className="divide-y text-sm">
          {data.results.map((m) => (
            <li key={m.id} className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2.5">
              <span className={cn("w-16 shrink-0 text-[11px] font-semibold uppercase", m.direction === "IN" ? "text-muted-foreground" : "text-brand")}>
                {m.direction === "IN" ? "Entrant" : "Sortant"}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{m.subject || "(sans objet)"}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {m.direction === "IN" ? m.from : m.to} · {formatDateTime(m.created_at)} · {m.kind_label}
                  {m.ticket && <> · <Link to={`/tickets/${m.ticket.id}`} className="font-medium text-foreground hover:text-brand">{m.ticket.reference}</Link></>}
                </p>
                {m.reason && <p className="text-xs text-muted-foreground">{m.reason}</p>}
              </div>
              <span className={cn("text-xs font-semibold", STATUS_TONE[m.status])}>{m.status_label}</span>
              {m.can_reprocess && <Button size="sm" variant="ghost" onClick={() => void reprocess(m.id)}><RotateCcw />Retraiter</Button>}
            </li>
          ))}
        </ul>
      )}
      {data && <Pagination page={page} count={data.count} pageSize={50} onPage={setPage} />}
    </div>
  );
}

function ConnectionResult({ value }: { value: ConnResult }) {
  return (
    <ul className="space-y-1.5 text-xs" aria-live="polite">
      {(["imap", "smtp"] as const).filter((k) => value[k]).map((k) => (
        <li key={k} className={cn("flex items-start gap-1.5", value[k]!.ok ? "text-success" : "text-destructive")}>
          {value[k]!.ok ? <CheckCircle2 className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" /> : <XCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />}
          <span><strong className="uppercase">{k}</strong> — {value[k]!.detail}</span>
        </li>
      ))}
    </ul>
  );
}

function MailboxCard({ box, appName, onEdit, onSecret }: { box: Mailbox; appName: string; onEdit: () => void; onSecret: (s: { url: string; secret: string }) => void }) {
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<ConnResult | null>(null);
  const [history, setHistory] = useState(false);
  const [rotate, setRotate] = useState(false);
  const failing = box.consecutive_failures > 0;
  const test = async () => {
    setTesting(true);
    try {
      setResult(await api<ConnResult>(`ticket-mailboxes/${box.id}/test/`, { method: "POST" }));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setTesting(false);
    }
  };
  const sync = async () => {
    try {
      await api(`ticket-mailboxes/${box.id}/sync/`, { method: "POST" });
      toast.success("Relève planifiée.");
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const doRotate = async () => {
    try {
      const r = await api<{ webhook_secret: string; webhook_url: string }>(`ticket-mailboxes/${box.id}/rotate-webhook-secret/`, { method: "POST" });
      setRotate(false);
      onSecret({ url: r.webhook_url, secret: r.webhook_secret });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const stats = box.stats ?? {};
  return (
    <Card className="p-5 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-full bg-primary-soft text-foreground" aria-hidden="true">
            {box.inbound === "IMAP" ? <Inbox className="size-[18px]" /> : <Webhook className="size-[18px]" />}
          </span>
          <div className="min-w-0">
            <h2 className="truncate text-[17px] font-semibold tracking-tight">{box.name}</h2>
            <p className="truncate text-xs text-muted-foreground">{box.address} · {appName}</p>
          </div>
        </div>
        <span className={cn("shrink-0 rounded-full px-3 py-1 text-xs font-semibold",
          !box.is_active ? "bg-hover text-muted-foreground" : failing ? "bg-destructive/10 text-destructive" : "bg-success/10 text-success")}>
          {!box.is_active ? "Désactivée" : failing ? "En erreur" : "Active"}
        </span>
      </div>
      <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
        <dt className="text-muted-foreground">Réception</dt>
        <dd>{box.inbound === "IMAP" ? `IMAP ${box.imap_host}:${box.imap_port} · ${secLabel[box.imap_security]} · ${box.imap_folder}` : "Webhook du fournisseur (signature HMAC)"}</dd>
        <dt className="text-muted-foreground">Envoi</dt>
        <dd>{box.smtp_host ? `SMTP ${box.smtp_host}:${box.smtp_port} · ${secLabel[box.smtp_security]}` : "Messagerie DevFlow (Répondre à : boîte)"}</dd>
        {box.inbound === "IMAP" && <><dt className="text-muted-foreground">Dernière relève</dt><dd>{box.last_sync_at ? formatDateTime(box.last_sync_at) : "—"}{box.last_success_at ? ` · succès ${formatDateTime(box.last_success_at)}` : ""}</dd></>}
        {box.inbound === "WEBHOOK" && <><dt className="text-muted-foreground">URL</dt><dd className="break-all font-mono">{box.webhook_url}</dd></>}
        <dt className="text-muted-foreground">7 derniers jours</dt>
        <dd>{stats.PROCESSED ?? 0} traité(s) · {(stats.REJECTED ?? 0) + (stats.DEAD ?? 0)} rejeté(s) · {stats.IGNORED ?? 0} ignoré(s)</dd>
      </dl>
      {box.last_error && failing && (
        <p role="alert" className="mt-3 flex items-start gap-2 rounded-2xl bg-destructive/10 p-3 text-xs text-destructive">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          <span>{box.consecutive_failures} échec(s) consécutif(s){box.last_error_at ? ` · ${formatDateTime(box.last_error_at)}` : ""} — {box.last_error}</span>
        </p>
      )}
      {result && <div className="mt-3 rounded-2xl bg-muted p-3"><ConnectionResult value={result} /></div>}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={onEdit}><Pencil />Modifier</Button>
        <Button size="sm" variant="outline" onClick={() => void test()} disabled={testing}>
          {testing ? <Loader2 className="animate-spin" aria-hidden="true" /> : <PlugZap />}Tester la connexion
        </Button>
        {box.inbound === "IMAP" && box.is_active && <Button size="sm" variant="ghost" onClick={() => void sync()}><RefreshCw />Relever</Button>}
        {box.inbound === "WEBHOOK" && <Button size="sm" variant="ghost" onClick={() => setRotate(true)}><KeyRound />Secret webhook</Button>}
        <Button size="sm" variant="ghost" onClick={() => setHistory(!history)} aria-expanded={history}><Mail />Messages</Button>
      </div>
      {history && <div className="mt-4 border-t pt-3"><MessageHistory box={box} /></div>}
      <ConfirmDialog open={rotate} onOpenChange={setRotate} destructive title="Renouveler le secret du webhook ?"
        description="L'ancien secret cesse immédiatement de fonctionner : mettez à jour la configuration du fournisseur e-mail."
        confirmLabel="Renouveler" onConfirm={() => void doRotate()} />
    </Card>
  );
}

function WebhookSecretDialog({ value, onClose }: { value: { url: string; secret: string } | null; onClose: () => void }) {
  const copy = (text: string) => void navigator.clipboard?.writeText(text).then(() => toast.success("Copié."));
  return (
    <Dialog open={value != null} onOpenChange={(o) => !o && onClose()} title="Webhook entrant"
      description="Le secret n'est affiché qu'une seule fois. Configurez-le chez votre fournisseur : chaque requête doit être signée (HMAC-SHA256).">
      {value && (
        <div className="space-y-3">
          {([["URL de réception", value.url], ["Secret de signature", value.secret]] as const).map(([label, v]) => (
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

export function EmailChannelsPage() {
  const { data: me } = useMe();
  const workspace = me?.workspace?.id;
  const admin = can(me?.permissions, "ticket.admin");
  const { data, isPending, isError, error, refetch } = useConfigList<Mailbox>("ticket-mailboxes", admin ? workspace : undefined);
  const apps = useConfigList<ExternalApp>("ticket-applications", admin ? workspace : undefined);
  const [editing, setEditing] = useState<Partial<Mailbox> | null>(null);
  const [secret, setSecret] = useState<{ url: string; secret: string } | null>(null);
  if (!workspace) return <EmptyState title="Aucun workspace" />;
  const appName = (id: number) => apps.data?.results.find((a) => a.id === id)?.name ?? "Application";
  return (
    <div className="space-y-5">
      <Header title="Canaux e-mail" description="Boîtes de support : chaque e-mail crée ou complète un ticket, avec accusé de réception et réponses bidirectionnelles."
        action={admin && <Button size="sm" onClick={() => setEditing({})}><Plus />Nouvelle boîte</Button>} />
      {!admin ? (
        <EmptyState title="Réservé aux administrateurs du support" description="La configuration des boîtes e-mail nécessite le droit ticket.admin." />
      ) : isPending ? <PageSkeleton /> : isError ? <ErrorState message={error.message} onRetry={() => void refetch()} /> : !data.results.length ? (
        <EmptyState title="Aucune boîte configurée" description="Ajoutez une adresse de support (IMAP ou webhook) pour recevoir les tickets par e-mail." />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {data.results.map((b) => (
            <MailboxCard key={b.id} box={b} appName={appName(b.application)} onEdit={() => setEditing(b)} onSecret={setSecret} />
          ))}
        </div>
      )}
      <Dialog open={editing != null} onOpenChange={(o) => !o && setEditing(null)} title={editing?.id ? "Modifier la boîte" : "Nouvelle boîte de support"} className="sm:max-w-3xl">
        {editing && <MailboxForm box={editing} workspace={workspace} onDone={(saved) => {
          setEditing(null);
          if (saved?.webhook_secret) setSecret({ url: saved.webhook_url, secret: saved.webhook_secret });
        }} />}
      </Dialog>
      <WebhookSecretDialog value={secret} onClose={() => setSecret(null)} />
    </div>
  );
}
