import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo, useState, type ReactNode } from "react";
import { useForm, type FieldValues, type Path } from "react-hook-form";
import { z } from "zod";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { ApiError, api } from "@/services/api";
import { toFormData, useFormSchema, type FormFieldSchema } from "./schema";

/**
 * Formulaire piloté par un formulaire Django existant (`/api/v1/forms/<nom>/`).
 * Champs, choix (déjà filtrés par workspace), validations et droits viennent
 * de Django ; React ajoute uniquement une prévalidation (requis, longueur, email).
 */
function initialValue(f: FormFieldSchema): unknown {
  if (f.type === "checkbox") return Boolean(f.value);
  if (f.type === "multiselect") return Array.isArray(f.value) ? f.value.map(String) : [];
  if (f.type === "file") return null;
  return f.value == null ? "" : String(f.value);
}

function buildZod(fields: FormFieldSchema[]) {
  const shape: Record<string, z.ZodType> = {};
  for (const f of fields) {
    if (f.type === "checkbox") shape[f.name] = z.boolean();
    else if (f.type === "multiselect") shape[f.name] = f.required ? z.array(z.string()).min(1, "Champ obligatoire.") : z.array(z.string());
    else if (f.type === "file") shape[f.name] = z.any();
    else {
      let s = z.string();
      if (f.max_length) s = s.max(f.max_length, `${f.max_length} caractères maximum.`);
      let t: z.ZodType = s;
      if (f.required && f.type !== "hidden") t = s.refine((v) => v.trim() !== "", "Champ obligatoire.");
      if (f.type === "email") t = t.refine((v) => !v || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(v)), "Adresse email invalide.");
      shape[f.name] = t;
    }
  }
  return z.object(shape);
}

function FieldInput({ f, form, error }: { f: FormFieldSchema; form: ReturnType<typeof useForm<FieldValues>>; error?: string }) {
  const id = `f-${f.name}`;
  const aria = { id, "aria-invalid": !!error, "aria-describedby": error ? `${id}-error` : undefined };
  const reg = form.register(f.name as Path<FieldValues>, { disabled: f.disabled });
  if (f.type === "checkbox") {
    return (
      <label className="flex items-center gap-2 pt-6 text-sm">
        <input type="checkbox" className="size-4 accent-primary" {...aria} {...reg} /> {f.label}
      </label>
    );
  }
  let control: ReactNode;
  if (f.type === "select") control = <Select {...aria} {...reg}>{f.choices?.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</Select>;
  else if (f.type === "multiselect") {
    control = (
      <div {...aria} role="group" className="max-h-44 space-y-1 overflow-y-auto rounded-xl border bg-card p-2.5">
        {f.choices?.filter((c) => c.value).map((c) => (
          <label key={c.value} className="flex items-center gap-2 text-sm"><input type="checkbox" value={c.value} className="size-4 accent-primary" {...reg} />{c.label}</label>
        ))}
        {!f.choices?.some((c) => c.value) && <p className="text-xs text-muted-foreground">Aucun choix disponible.</p>}
      </div>
    );
  } else if (f.type === "textarea") control = <Textarea rows={4} {...aria} {...reg} />;
  else if (f.type === "file") {
    control = (
      <Input type="file" className="pt-2" {...aria}
        onChange={(e) => form.setValue(f.name as Path<FieldValues>, e.target.files?.[0] ?? null)} />
    );
  } else {
    control = <Input type={f.type} step={f.type === "number" ? "any" : undefined} min={f.min ?? undefined} max={f.max ?? undefined} {...aria} {...reg} />;
  }
  return (
    <Field id={id} label={`${f.label}${f.required ? " *" : ""}`} error={error} hint={f.type === "file" && f.value ? "Laisser vide pour conserver le fichier actuel." : f.help_text}>
      {control}
    </Field>
  );
}

export function LegacyForm({ name, id, query, submitLabel = "Enregistrer", onSuccess, onCancel, exclude = [], hidden = [], compact, endpoint }: {
  name: string;
  /** Vue dédiée au même contrat que `/api/v1/forms/<nom>/` (GET champs, POST → `{id, messages}` ou erreurs 400). */
  endpoint?: string;
  id?: number;
  /** Paramètres GET transmis à la vue Django (ex. `project` pour préremplir). */
  query?: Record<string, string>;
  submitLabel?: string;
  onSuccess: (result: { id: number; messages: string[] }) => void;
  onCancel?: () => void;
  exclude?: string[];
  /** Champs conservés (valeur préremplie envoyée) mais non affichés — ex. `task` dans la fiche tâche. */
  hidden?: string[];
  compact?: boolean;
}) {
  const schema = useFormSchema(name, id, query, endpoint);
  if (schema.isPending) return <PageSkeleton />;
  if (schema.isError) return <ErrorState message={schema.error.message} onRetry={() => void schema.refetch()} />;
  return (
    <LegacyFormBody key={`${name}-${id ?? "new"}`} name={name} id={id} query={query} compact={compact} endpoint={endpoint}
      fields={schema.data.fields.filter((f) => !exclude.includes(f.name)).map((f) => (hidden.includes(f.name) ? { ...f, type: "hidden" } : f))}
      submitLabel={submitLabel} onSuccess={onSuccess} onCancel={onCancel} />
  );
}

function LegacyFormBody({ name, id, query, fields, submitLabel, onSuccess, onCancel, compact, endpoint }: {
  name: string; id?: number; query?: Record<string, string>; fields: FormFieldSchema[]; submitLabel: string; compact?: boolean; endpoint?: string;
  onSuccess: (r: { id: number; messages: string[] }) => void; onCancel?: () => void;
}) {
  const resolver = useMemo(() => zodResolver(buildZod(fields)), [fields]);
  const defaults = useMemo(() => Object.fromEntries(fields.map((f) => [f.name, initialValue(f)])), [fields]);
  const form = useForm<FieldValues>({ resolver, defaultValues: defaults });
  const [globalErrors, setGlobalErrors] = useState<string[]>([]);

  const sections = useMemo(() => {
    const map = new Map<string, FormFieldSchema[]>();
    fields.filter((f) => f.type !== "hidden").forEach((f) => {
      const key = f.section ?? "Informations";
      map.set(key, [...(map.get(key) ?? []), f]);
    });
    return [...map.entries()];
  }, [fields]);

  const onSubmit = form.handleSubmit(async (values) => {
    setGlobalErrors([]);
    try {
      const res = await api<{ id: number; messages: string[] }>(endpoint ?? (id ? `forms/${name}/${id}/` : `forms/${name}/`), {
        method: "POST", body: toFormData(fields.filter((f) => !f.disabled), values), params: query,
      });
      onSuccess(res);
    } catch (e) {
      if (e instanceof ApiError && e.status === 400 && e.data && typeof e.data === "object") {
        const others: string[] = [];
        Object.entries(e.data as Record<string, string[] | string>).forEach(([k, v]) => {
          const msg = [v].flat().join(" ");
          if (fields.some((f) => f.name === k && f.type !== "hidden")) form.setError(k as Path<FieldValues>, { message: msg });
          else others.push(msg);
        });
        setGlobalErrors(others);
      } else {
        setGlobalErrors([(e as Error).message]);
      }
    }
  });

  return (
    <form onSubmit={onSubmit} noValidate className={compact ? "space-y-3" : "space-y-6"}>
      {globalErrors.length > 0 && (
        <div role="alert" className="rounded-2xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {globalErrors.map((m) => <p key={m}>{m}</p>)}
        </div>
      )}
      {compact ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {sections.flatMap(([, items]) => items).map((f) => (
            <div key={f.name} className={f.type === "textarea" ? "sm:col-span-2" : undefined}>
              <FieldInput f={f} form={form} error={form.formState.errors[f.name]?.message as string | undefined} />
            </div>
          ))}
        </div>
      ) : sections.map(([title, items]) => (
        <Card key={title}>
          <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            {items.map((f) => (
              <div key={f.name} className={f.type === "textarea" || f.type === "multiselect" ? "md:col-span-2" : undefined}>
                <FieldInput f={f} form={form} error={form.formState.errors[f.name]?.message as string | undefined} />
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
      <div className={compact ? "flex justify-end gap-2" : "sticky bottom-0 flex justify-end gap-2 border-t bg-background/90 py-3 pr-20 backdrop-blur"}>
        {onCancel && <Button type="button" variant="outline" onClick={onCancel}>Annuler</Button>}
        <Button type="submit" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? "Enregistrement…" : submitLabel}</Button>
      </div>
    </form>
  );
}
