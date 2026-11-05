import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm, type Path } from "react-hook-form";
import { useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { z } from "zod";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Textarea } from "@/components/ui/input";
import { ApiError } from "@/services/api";
import { useSaveWorkspace, useWorkspace, type Workspace } from "./api";

const schema = z.object({
  name: z.string().trim().min(1, "Le nom est obligatoire.").max(150, "150 caractères maximum."),
  description: z.string(),
  quarter_label: z.string().max(30, "30 caractères maximum."),
  timezone: z.string().trim().min(1, "Fuseau horaire requis."),
  is_active: z.boolean(),
  accent_color: z.string(),
  legal_name: z.string(), tagline: z.string(), legal_rccm: z.string(), legal_cc: z.string(), legal_tax_id: z.string(),
  address_line1: z.string(), address_line2: z.string(), postal_code: z.string(), city: z.string(), country: z.string(),
  phone: z.string(), website: z.string(),
  email: z.string().trim().refine((v) => !v || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v), "Adresse email invalide."),
  bank_details: z.string(), invoice_footer_text: z.string(),
});
type Values = z.infer<typeof schema>;
const FIELDS = Object.keys(schema.shape) as (keyof Values)[];

const EMPTY: Values = {
  name: "", description: "", quarter_label: "", timezone: "Africa/Abidjan", is_active: true, accent_color: "#F4722B",
  legal_name: "", tagline: "", legal_rccm: "", legal_cc: "", legal_tax_id: "", address_line1: "", address_line2: "",
  postal_code: "", city: "", country: "", phone: "", website: "", email: "", bank_details: "", invoice_footer_text: "",
};

const pick = (ws: Workspace): Values => Object.fromEntries(FIELDS.map((k) => [k, ws[k] ?? EMPTY[k]])) as Values;

type TextKey = Exclude<keyof Values, "is_active">;
const GROUPS: { title: string; fields: [TextKey, string, ("textarea" | "color")?][] }[] = [
  { title: "Général", fields: [["name", "Nom *"], ["description", "Description", "textarea"], ["quarter_label", "Trimestre en cours (ex. T4 2026)"], ["timezone", "Fuseau horaire"], ["accent_color", "Couleur d'accent", "color"]] },
  { title: "Identité légale", fields: [["legal_name", "Raison sociale"], ["tagline", "Slogan"], ["legal_rccm", "RCCM"], ["legal_cc", "Compte contribuable"], ["legal_tax_id", "N° fiscal"]] },
  { title: "Coordonnées", fields: [["address_line1", "Adresse"], ["address_line2", "Complément d'adresse"], ["postal_code", "Code postal"], ["city", "Ville"], ["country", "Pays"], ["phone", "Téléphone"], ["website", "Site web"], ["email", "Email"]] },
  { title: "Facturation", fields: [["bank_details", "Coordonnées bancaires", "textarea"], ["invoice_footer_text", "Pied de page des factures", "textarea"]] },
];

export function WorkspaceFormPage() {
  const params = useParams();
  const id = params.id ? Number(params.id) : undefined;
  const navigate = useNavigate();
  const existing = useWorkspace(id ?? 0);
  const save = useSaveWorkspace(id);
  const [logo, setLogo] = useState<File | null>(null);
  const { register, handleSubmit, reset, setError, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(schema), defaultValues: EMPTY,
  });

  useEffect(() => { if (existing.data) reset(pick(existing.data)); }, [existing.data, reset]);

  if (id && existing.isPending) return <PageSkeleton />;
  if (id && existing.isError) return <ErrorState message={existing.error.message} onRetry={() => void existing.refetch()} />;
  if (id && existing.data && !existing.data.can_manage) {
    return <ErrorState message="Modification du workspace réservée à ses administrateurs." />;
  }

  const onSubmit = handleSubmit(async (values) => {
    const file = logo;
    let body: FormData | Values = values;
    if (file) {
      const fd = new FormData();
      Object.entries(values).forEach(([k, v]) => fd.append(k, String(v)));
      fd.append("logo", file);
      body = fd;
    }
    try {
      const ws = await save.mutateAsync(body);
      toast.success(id ? "Workspace mis à jour." : "Workspace créé.");
      navigate(`/workspaces/${ws.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.data && typeof e.data === "object") {
        Object.entries(e.data as Record<string, string[]>).forEach(([k, v]) => {
          if ((FIELDS as string[]).includes(k)) setError(k as Path<Values>, { message: [v].flat().join(" ") });
        });
      }
      toast.error((e as Error).message);
    }
  });

  return (
    <form onSubmit={onSubmit} className="space-y-6" noValidate>
      <PageHeader
        eyebrow="Workspaces"
        title={id ? `Modifier ${existing.data?.name ?? ""}` : "Nouveau workspace"}
        actions={
          <>
            <Button type="button" variant="outline" onClick={() => navigate(-1)}>Annuler</Button>
            <Button type="submit" disabled={isSubmitting}>{isSubmitting ? "Enregistrement…" : "Enregistrer"}</Button>
          </>
        }
      />
      {GROUPS.map((group) => (
        <Card key={group.title}>
          <CardHeader><CardTitle>{group.title}</CardTitle></CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            {group.fields.map(([name, label, kind]) => {
              const err = errors[name]?.message;
              const common = { id: `ws-${name}`, "aria-invalid": !!err, "aria-describedby": err ? `ws-${name}-error` : undefined, ...register(name) };
              return (
                <div key={name} className={kind === "textarea" ? "md:col-span-2" : undefined}>
                  <Field id={`ws-${name}`} label={label} error={err}>
                    {kind === "textarea" ? <Textarea rows={3} {...common} /> : kind === "color" ? <Input type="color" className="h-11 w-24 p-1" {...common} /> : <Input {...common} />}
                  </Field>
                </div>
              );
            })}
            {group.title === "Général" && (
              <>
                <Field id="ws-logo" label="Logo" hint={existing.data?.logo ? "Laisser vide pour conserver le logo actuel." : undefined}>
                  <Input id="ws-logo" onChange={(e) => setLogo(e.target.files?.[0] ?? null)} type="file" accept="image/*" className="pt-2" />
                </Field>
                <label className="flex items-center gap-2 self-end pb-3 text-sm">
                  <input type="checkbox" className="size-4 accent-primary" {...register("is_active")} /> Workspace actif
                </label>
              </>
            )}
          </CardContent>
        </Card>
      ))}
    </form>
  );
}
