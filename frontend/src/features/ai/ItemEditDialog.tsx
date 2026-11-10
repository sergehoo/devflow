import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useForm, type FieldValues } from "react-hook-form";
import { toast } from "sonner";
import { ErrorState } from "@/components/feedback/states";
import { toFormData, type FormFieldSchema } from "@/components/forms/schema";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { ApiError, api } from "@/services/api";
import { AI_KEY, useItemForm, type ProposalItem } from "./api";
import { ITEM_VISIBLE_FIELDS } from "./constants";

const valueOf = (f: FormFieldSchema) => (f.value == null ? "" : String(f.value));

/** Édition d'un élément de proposition (ProjectAIProposalItemEditForm via le pont Django). */
export function ItemEditDialog({ proposalId, item, refs, onClose }: {
  proposalId: number;
  item: ProposalItem;
  /** Références de sprints / jalons de la proposition (listes de choix). */
  refs: { sprint: { value: string; label: string }[]; milestone: { value: string; label: string }[] };
  onClose: () => void;
}) {
  const schema = useItemForm(proposalId, item.id);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={`Modifier — ${item.kind_label}`}
      description={item.local_ref ? `Référence ${item.local_ref}` : undefined} className="sm:max-w-2xl">
      {schema.isPending ? <Skeleton className="h-64" />
        : schema.isError ? <ErrorState message={schema.error.message} onRetry={() => void schema.refetch()} />
          : <ItemForm proposalId={proposalId} item={item} fields={schema.data.fields} refs={refs} onClose={onClose} />}
    </Dialog>
  );
}

function ItemForm({ proposalId, item, fields, refs, onClose }: {
  proposalId: number; item: ProposalItem; fields: FormFieldSchema[];
  refs: { sprint: { value: string; label: string }[]; milestone: { value: string; label: string }[] }; onClose: () => void;
}) {
  const qc = useQueryClient();
  const visible = useMemo(() => {
    const names = ITEM_VISIBLE_FIELDS[item.kind] ?? ["title", "description"];
    return names.map((n) => fields.find((f) => f.name === n)).filter((f): f is FormFieldSchema => !!f);
  }, [fields, item.kind]);
  const form = useForm<FieldValues>({ defaultValues: Object.fromEntries(fields.map((f) => [f.name, valueOf(f)])) });
  const [globalError, setGlobalError] = useState<string | null>(null);

  const submit = form.handleSubmit(async (values) => {
    setGlobalError(null);
    try {
      const res = await api<{ messages: string[] }>(`ai-proposals/${proposalId}/items/${item.id}/form/`, {
        method: "POST", body: toFormData(fields.filter((f) => !f.disabled), values),
      });
      (res.messages.length ? res.messages : ["Élément mis à jour."]).forEach((m) => toast.success(m));
      await qc.invalidateQueries({ queryKey: [...AI_KEY, "proposals"] });
      onClose();
    } catch (e) {
      if (e instanceof ApiError && e.status === 400 && e.data && typeof e.data === "object") {
        const others: string[] = [];
        Object.entries(e.data as Record<string, string[] | string>).forEach(([k, v]) => {
          const msg = [v].flat().join(" ");
          if (visible.some((f) => f.name === k)) form.setError(k, { message: msg }); else others.push(msg);
        });
        setGlobalError(others.join(" ") || null);
      } else setGlobalError((e as Error).message);
    }
  });

  const refOptions = (name: string, current: string) => {
    const list = name === "sprint_ref" ? refs.sprint : refs.milestone;
    return current && !list.some((o) => o.value === current) ? [{ value: current, label: current }, ...list] : list;
  };

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      {globalError && <p role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{globalError}</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        {visible.map((f) => {
          const id = `item-${f.name}`;
          const error = form.formState.errors[f.name]?.message as string | undefined;
          const aria = { id, "aria-invalid": !!error, "aria-describedby": error ? `${id}-error` : undefined };
          const reg = form.register(f.name);
          let control;
          if (f.name === "sprint_ref" || f.name === "milestone_ref") {
            control = (
              <Select {...aria} {...reg}>
                <option value="">—</option>
                {refOptions(f.name, valueOf(f)).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </Select>
            );
          } else if (f.type === "select") {
            control = <Select {...aria} {...reg}>{f.choices?.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</Select>;
          } else if (f.type === "textarea") {
            control = <Textarea rows={4} {...aria} {...reg} />;
          } else {
            control = <Input type={f.type === "number" || f.type === "date" ? f.type : "text"} step={f.type === "number" ? "any" : undefined} min={f.type === "number" ? 0 : undefined} {...aria} {...reg} />;
          }
          return (
            <div key={f.name} className={f.type === "textarea" || f.name === "title" ? "sm:col-span-2" : undefined}>
              <Field id={id} label={f.label} error={error}>{control}</Field>
            </div>
          );
        })}
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onClose}>Annuler</Button>
        <Button type="submit" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? "Enregistrement…" : "Enregistrer"}</Button>
      </div>
    </form>
  );
}
