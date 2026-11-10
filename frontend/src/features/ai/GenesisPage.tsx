import { CheckCircle2, ExternalLink, Info, Loader2, Sparkles, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, type FieldValues } from "react-hook-form";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import type { FormFieldSchema } from "@/components/forms/schema";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { ApiError } from "@/services/api";
import { useGenesis, useGenesisSchema, type GenesisResult } from "./api";
import { COUNT_LABELS } from "./constants";
import { AIStatusNotice } from "./shared";

const STEPS = [
  "Lecture du brief et du contexte du workspace",
  "Construction de la roadmap et des phases",
  "Découpage en jalons et sprints",
  "Génération du backlog et des tâches",
  "Dépendances et affectations par profil",
  "Création du projet et estimation budgétaire",
];

const GENERATED = [
  ["Roadmap", "phases du projet (cadrage → maintenance)"],
  ["Sprints & jalons", "découpage temporel cohérent"],
  ["Backlog & tâches", "couvrant les phases standard, avec critères d'acceptation"],
  ["Dépendances", "entre tâches, dans l'ordre logique"],
  ["Affectations", "recommandations selon les profils des membres du workspace"],
  ["Budget estimatif", "calculé à partir du TJM des membres"],
] as const;

function GenerationProgress() {
  const [step, setStep] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 4000);
    return () => clearInterval(id);
  }, []);
  return (
    <Card aria-live="polite">
      <CardContent className="space-y-3">
        <p className="flex items-center gap-2 font-semibold"><Loader2 className="size-5 animate-spin text-brand" aria-hidden="true" />Génération en cours…</p>
        <ol className="space-y-1.5 text-sm">
          {STEPS.map((label, i) => (
            <li key={label} className={i < step ? "text-success" : i === step ? "font-medium text-foreground" : "text-muted-foreground"}>
              {i < step ? "✓ " : i === step ? "• " : ""}{label}
            </li>
          ))}
        </ol>
        <p className="text-xs text-muted-foreground">Selon le fournisseur IA, la génération prend de quelques secondes à une minute.</p>
      </CardContent>
    </Card>
  );
}

function Result({ result, onReset }: { result: GenesisResult; onReset: () => void }) {
  const pid = result.project.id;
  const counts = Object.entries(result.counts).filter(([k, v]) => COUNT_LABELS[k] && typeof v === "number" && v > 0);
  const failed = typeof result.counts.error === "string";
  return (
    <Card className="border-success/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><CheckCircle2 className="size-5 text-success" aria-hidden="true" />Projet « {result.project.name} » créé</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Structure générée par <strong>{result.used_provider}</strong>
          {counts.length ? ` : ${counts.map(([k, v]) => `${v} ${COUNT_LABELS[k]}`).join(", ")}.` : "."}
        </p>
        {failed && (
          <p role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            L'application automatique a échoué ({String(result.counts.error)}). Vous pouvez reprendre la proposition manuellement.
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button asChild><Link to={`/projects/${pid}`}>Ouvrir le projet</Link></Button>
          <Button variant="outline" asChild><Link to={`/tasks?project=${pid}`}>Tâches</Link></Button>
          <Button variant="outline" asChild><Link to={`/m/sprint?project=${pid}`}>Sprints</Link></Button>
          <Button variant="outline" asChild><Link to={`/ai-proposals/${result.proposal.id}`}><ExternalLink />Proposition IA</Link></Button>
          <Button variant="ghost" onClick={onReset}><Wand2 />Créer un autre projet</Button>
        </div>
      </CardContent>
    </Card>
  );
}

/** DevFlow Genesis : création d'un projet complet (roadmap, jalons, sprints, backlog, tâches) depuis un brief. */
export function GenesisPage() {
  const schema = useGenesisSchema();
  if (schema.isPending) return <PageSkeleton />;
  if (schema.isError) return <ErrorState message={schema.error.message} onRetry={() => void schema.refetch()} />;
  return <GenesisForm fields={schema.data.fields} ai={schema.data.ai} canCreate={schema.data.can_create !== false} />;
}

function GenesisForm({ fields, ai, canCreate }: { fields: FormFieldSchema[]; ai: { available: boolean; provider: string }; canCreate: boolean }) {
  const navigate = useNavigate();
  const genesis = useGenesis();
  const [result, setResult] = useState<GenesisResult | null>(null);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const byName = Object.fromEntries(fields.map((f) => [f.name, f])) as Record<string, FormFieldSchema | undefined>;
  const defaults: FieldValues = Object.fromEntries(fields.map((f) => [f.name, f.type === "checkbox" ? Boolean(f.value) : f.value == null ? "" : String(f.value)]));
  const form = useForm<FieldValues>({ defaultValues: defaults });
  const err = (name: string) => form.formState.errors[name]?.message as string | undefined;

  const submit = form.handleSubmit((values) => {
    setGlobalError(null);
    let invalid = false;
    for (const name of ["name", "description", "workspace"]) {
      if (!String(values[name] ?? "").trim()) { form.setError(name, { message: "Champ obligatoire." }); invalid = true; }
    }
    if (invalid) return;
    genesis.mutate({ ...values, target_date: values.target_date || null, auto_apply: Boolean(values.auto_apply) }, {
      onSuccess: (res) => {
        res.messages.forEach((m) => toast.success(m));
        if (res.applied) setResult(res);
        else navigate(`/ai-proposals/${res.proposal.id}`);
      },
      onError: (e) => {
        if (e instanceof ApiError && e.status === 400 && e.data && typeof e.data === "object") {
          const others: string[] = [];
          Object.entries(e.data as Record<string, string[] | string>).forEach(([k, v]) => {
            const msg = [v].flat().join(" ");
            if (byName[k]) form.setError(k, { message: msg }); else others.push(msg);
          });
          setGlobalError(others.join(" ") || null);
        } else setGlobalError(e.message);
      },
    });
  });

  const select = (name: string) => {
    const f = byName[name];
    if (!f) return null;
    return (
      <Field id={`g-${name}`} label={`${f.label}${f.required ? " *" : ""}`} error={err(name)} hint={f.help_text || undefined}>
        <Select id={`g-${name}`} aria-invalid={!!err(name)} disabled={genesis.isPending} {...form.register(name)}>
          {f.choices?.map((c) => <option key={c.value} value={c.value}>{c.value ? c.label : "Sélectionner…"}</option>)}
        </Select>
      </Field>
    );
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader eyebrow="DevFlow Genesis · IA" title="Créer un projet avec l'IA"
        description="Donnez un nom et une description : DevFlow génère la roadmap, les jalons, les sprints, le backlog, les tâches et leurs dépendances." />
      <AIStatusNotice ai={ai} fallback="IA désactivée : la structure sera générée par l'assistant heuristique (phases standard). Le projet est créé dans tous les cas." />

      {result ? <Result result={result} onReset={() => { setResult(null); form.reset(defaults); }} /> : (
        <form onSubmit={submit} noValidate className="space-y-4">
          {!canCreate && (
            <p role="alert" className="rounded-2xl border border-warning/30 bg-warning/10 p-4 text-sm">
              Votre rôle ne permet pas de créer un projet : la création par l'IA est réservée aux chefs de projet et aux propriétaires du workspace.
            </p>
          )}
          {globalError && <p role="alert" className="rounded-2xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{globalError}</p>}
          <Card>
            <CardContent className="space-y-4">
              <Field id="g-name" label={`${byName.name?.label ?? "Nom du projet"} *`} error={err("name")}>
                <Input id="g-name" maxLength={160} placeholder="ex. Plateforme e-commerce v3" aria-invalid={!!err("name")} disabled={genesis.isPending} {...form.register("name")} />
              </Field>
              <Field id="g-description" label={`${byName.description?.label ?? "Description"} *`} error={err("description")}
                hint="Plus c'est précis (objectifs, périmètre, technologies, contraintes), mieux l'IA structurera le projet.">
                <Textarea id="g-description" rows={6} aria-invalid={!!err("description")} disabled={genesis.isPending}
                  placeholder="Refonte du site marchand avec gestion du paiement, back-office et application mobile…" {...form.register("description")} />
              </Field>
              <div className="grid gap-4 sm:grid-cols-2">
                {select("workspace")}
                {select("priority")}
                {select("methodology")}
                {byName.target_date && (
                  <Field id="g-target_date" label={byName.target_date.label} error={err("target_date")}>
                    <Input id="g-target_date" type="date" disabled={genesis.isPending} {...form.register("target_date")} />
                  </Field>
                )}
              </div>
              {byName.auto_apply && (
                <label className="flex items-start gap-3 rounded-xl bg-muted/60 p-3 text-sm">
                  <input type="checkbox" className="mt-0.5 size-4 accent-primary" disabled={genesis.isPending} {...form.register("auto_apply")} />
                  <span><span className="font-semibold">Appliquer automatiquement</span>
                    <span className="block text-xs text-muted-foreground">Décocher pour relire et valider la proposition (aperçu) avant sa création dans le projet.</span></span>
                </label>
              )}
            </CardContent>
          </Card>
          {genesis.isPending && <GenerationProgress />}
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" variant="outline" asChild><Link to="/projects">Annuler</Link></Button>
            <Button type="submit" disabled={!canCreate || genesis.isPending}>
              {genesis.isPending ? <><Loader2 className="animate-spin" />Génération en cours…</> : <><Sparkles />Générer le projet</>}
            </Button>
          </div>
        </form>
      )}

      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Info className="size-4 text-info" aria-hidden="true" />Ce que DevFlow Genesis va générer</CardTitle></CardHeader>
        <CardContent>
          <ul className="space-y-1.5 text-sm text-muted-foreground">
            {GENERATED.map(([k, v]) => <li key={k}><strong className="text-foreground">{k}</strong> — {v}</li>)}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
