import { CheckCircle2, Copy, ExternalLink, KeyRound, Mail, XCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useCollection, useCollectionAction, type ChannelStatus, type Collection, type CollectionMode, type CollectionTest, type ExternalApp } from "./api";

const INFO: Record<CollectionMode, { title: string; text: string }> = {
  api: { title: "API REST", text: "Pour une application dotée d'un backend : appels serveur à serveur signés HMAC (identifiant + secret, jamais dans un navigateur)." },
  form: { title: "Formulaire existant", text: "Connecte le formulaire de signalement déjà présent dans l'application, sans API ni backend. Le domaine de la page doit être autorisé ci-dessous." },
  widget: { title: "Widget intégré", text: "Bouton « Signaler un problème » ajouté par une simple balise script (HTML, React, Django, PHP…). Affichable uniquement sur les domaines autorisés." },
  hosted: { title: "Formulaire public hébergé", text: "Page DevFlow propre à l'application, sans aucune intégration : partagez simplement le lien. Le déclarant reçoit une référence et un code de suivi." },
};

function snippet(mode: CollectionMode, c: Collection, app: ExternalApp) {
  const base = window.location.origin;
  switch (mode) {
    case "api": return `POST ${base}/api/v1/integrations/tickets/\nX-DevFlow-App: ${c.key_id}\nX-DevFlow-Timestamp: <epoch>\nX-DevFlow-Signature: sha256=<HMAC(secret, "timestamp.METHODE.chemin.sha256(corps)")>\n\n{"external_id": "…", "title": "…", "reporter": {"id": "…"}}`;
    case "form": return `<script src="${base}/static/support/devflow-intake.js"></script>\n<script>\n  DevFlowIntake.connect(document.querySelector("#formulaire-signalement"), {\n    app: "${c.public_key}",\n    fields: { title: "sujet", description: "message", email: "email", name: "nom" },\n  });\n</script>`;
    case "widget": return `<script src="${base}/static/support/devflow-widget.js"\n        data-app="${c.public_slug}" data-name="${app.name.replace(/"/g, "")}" defer></script>`;
    case "hosted": return `${base}${c.hosted_path}`;
  }
}

function Channel({ status }: { status: ChannelStatus }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
      <dt className="text-muted-foreground">Dernier ticket</dt>
      <dd>{status.last_ticket ? <Link className="font-medium hover:text-brand" to={`/tickets/${status.last_ticket.id}`}>{status.last_ticket.reference}</Link> : "—"}
        {status.last_ticket && <span className="text-muted-foreground"> · {formatDateTime(status.last_ticket.created_at)}</span>}
        {status.count_30d != null && <span className="text-muted-foreground"> · {status.count_30d} sur 30 j</span>}</dd>
      <dt className="text-muted-foreground">Dernière erreur</dt>
      <dd className={status.last_error ? "text-destructive" : ""}>{status.last_error ? `${status.last_error.reason}${status.last_error.at ? ` · ${formatDateTime(status.last_error.at)}` : ""}` : "Aucune"}</dd>
    </dl>
  );
}

/**
 * « Modes de collecte » d'une application : API, formulaire existant (SDK), widget,
 * formulaire public hébergé et e-mail. Aucun mode n'impose une API côté application ;
 * seule la clé PUBLIQUE de soumission apparaît dans le code à copier (jamais le secret).
 */
export function CollectionModesDialog({ app, onClose }: { app: ExternalApp | null; onClose: () => void }) {
  return (
    <Dialog open={app != null} onOpenChange={(o) => !o && onClose()} title={`Modes de collecte · ${app?.name ?? ""}`} className="sm:max-w-3xl"
      description="Choisissez comment cette application transmet ses signalements à DevFlow. Une application sans API peut utiliser le formulaire existant, le widget ou le formulaire public.">
      {app && <CollectionBody key={app.id} app={app} />}
    </Dialog>
  );
}

function CollectionBody({ app }: { app: ExternalApp }) {
  const { data, isPending } = useCollection(app.id);
  const action = useCollectionAction(app.id);
  const [origins, setOrigins] = useState<string | null>(null);
  const [tests, setTests] = useState<Partial<Record<CollectionMode, CollectionTest>>>({});
  // Affichage immédiat du choix pendant l'enregistrement (retour à l'état serveur en cas d'erreur).
  const [asked, setAsked] = useState<Partial<Record<CollectionMode, boolean>>>({});
  if (isPending || !data) return <Skeleton className="h-64" />;
  const fail = (e: Error) => toast.error(e.message);
  const toggle = (mode: CollectionMode, on: boolean) => {
    setAsked((a) => ({ ...a, [mode]: on }));
    action.mutate({ method: "PATCH", body: { modes: { [mode]: on } } }, {
      onSuccess: () => toast.success(on ? "Mode activé." : "Mode désactivé."), onError: fail,
      onSettled: () => setAsked((a) => { const next = { ...a }; delete next[mode]; return next; }),
    });
  };
  const saveOrigins = () => action.mutate(
    { method: "PATCH", body: { allowed_origins: (origins ?? "").split(/\s+/).filter(Boolean) } },
    { onSuccess: () => { setOrigins(null); toast.success("Domaines autorisés enregistrés."); }, onError: fail },
  );
  const test = (mode: CollectionMode) => action.mutate({ path: "test/", body: { mode } }, { onSuccess: (r) => setTests((t) => ({ ...t, [mode]: r })), onError: fail });
  const copy = (text: string) => void navigator.clipboard?.writeText(text).then(() => toast.success("Copié."), () => toast.error("Copie impossible."));

  return (
    <div className="space-y-4">
      <section aria-label="Domaines autorisés" className="rounded-2xl bg-muted p-4">
        <label htmlFor="allowed-origins" className="text-sm font-semibold">Domaines autorisés <span className="font-normal text-muted-foreground">(formulaire existant et widget, un par ligne)</span></label>
        <Textarea id="allowed-origins" rows={2} className="mt-2 font-mono text-xs" placeholder="https://app.exemple.com"
          value={origins ?? data.allowed_origins.join("\n")} onChange={(e) => setOrigins(e.target.value)} />
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">Contrôlés par DevFlow à chaque envoi (pas seulement par CORS).</p>
          <Button size="sm" variant="outline" disabled={origins == null || action.isPending} onClick={saveOrigins}>Enregistrer les domaines</Button>
        </div>
        {data.public_key && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">Clé publique de soumission :</span><code className="break-all">{data.public_key}</code>
            <Button size="sm" variant="ghost" disabled={action.isPending} onClick={() => action.mutate({ path: "rotate-key/" }, { onSuccess: () => toast.success("Nouvelle clé publique : mettez à jour vos intégrations."), onError: fail })}>
              <KeyRound />Renouveler
            </Button>
          </div>
        )}
      </section>

      {(Object.keys(INFO) as CollectionMode[]).map((mode) => {
        const on = asked[mode] ?? data.modes[mode];
        const ready = mode === "api" || Boolean(data.public_key);
        const code = ready ? snippet(mode, data, app) : "";
        const result = tests[mode];
        return (
          <section key={mode} aria-label={INFO[mode].title} className="rounded-2xl border p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-semibold">{INFO[mode].title}</h3>
                <span className={cn("mt-0.5 inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold", on ? "bg-success/15 text-success" : "bg-hover text-muted-foreground")}>{on ? "Actif" : "Inactif"}</span>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" role="switch" className="size-4 accent-[var(--color-primary)]" checked={on} disabled={action.isPending}
                  aria-label={`Activer : ${INFO[mode].title}`} onChange={(e) => toggle(mode, e.target.checked)} />
                Activé
              </label>
            </div>
            <p className="mt-2 text-sm text-muted-foreground">{INFO[mode].text}</p>
            {on && code && (
              <div className="mt-3">
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-xl bg-muted p-3 font-mono text-[11px]" aria-label={`Code ${INFO[mode].title}`}>{code}</pre>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => copy(code)}><Copy />Copier</Button>
                  {mode === "hosted" && <Button size="sm" variant="outline" asChild><a href={code} target="_blank" rel="noreferrer"><ExternalLink />Ouvrir le formulaire</a></Button>}
                </div>
              </div>
            )}
            <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_auto] sm:items-start">
              <Channel status={data.channels[mode]} />
              <Button size="sm" variant="ghost" disabled={action.isPending} onClick={() => test(mode)}>Tester la configuration</Button>
            </div>
            {result && (
              <ul className="mt-2 space-y-1 text-xs" aria-label={`Résultat du test ${INFO[mode].title}`}>
                {result.checks.map((c) => (
                  <li key={c.label} className={cn("flex items-center gap-1.5", c.ok ? "text-success" : "text-destructive")}>
                    {c.ok ? <CheckCircle2 className="size-3.5" aria-hidden="true" /> : <XCircle className="size-3.5" aria-hidden="true" />}{c.label}
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}

      <section aria-label="E-mail" className="rounded-2xl border p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="font-semibold">E-mail</h3>
            <span className={cn("mt-0.5 inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold", data.channels.email.enabled ? "bg-success/15 text-success" : "bg-hover text-muted-foreground")}>
              {data.channels.email.enabled ? "Actif" : "Inactif"}
            </span>
          </div>
          <Button size="sm" variant="outline" asChild><Link to="/tickets/email"><Mail />Canaux e-mail</Link></Button>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          {data.channels.email.mailboxes?.length ? data.channels.email.mailboxes.map((m) => m.address).join(", ") : "Aucune boîte de support rattachée à cette application."}
        </p>
        <div className="mt-3"><Channel status={data.channels.email} /></div>
      </section>
    </div>
  );
}
