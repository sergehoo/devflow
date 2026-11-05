import { useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";

export interface FormFieldSchema {
  name: string;
  label: string;
  type: string;
  required: boolean;
  disabled?: boolean;
  help_text: string;
  section: string | null;
  value: unknown;
  max_length: number | null;
  min: number | null;
  max: number | null;
  choices?: { value: string; label: string }[];
}

export const formSchemaKey = (name: string, id?: number, query?: Record<string, string>) => ["forms", name, id ?? "new", query ?? {}] as const;

export function useFormSchema(name: string, id?: number, query?: Record<string, string>) {
  return useQuery({
    queryKey: formSchemaKey(name, id, query),
    queryFn: ({ signal }) => api<{ fields: FormFieldSchema[] }>(id ? `forms/${name}/${id}/` : `forms/${name}/`, { signal, params: query }),
    staleTime: 0,
  });
}

export type Values = Record<string, unknown>;

export function toFormData(fields: FormFieldSchema[], values: Values): FormData {
  const fd = new FormData();
  for (const f of fields) {
    const v = values[f.name];
    if (f.type === "checkbox") { if (v) fd.append(f.name, "on"); }
    else if (f.type === "multiselect") (v as string[]).forEach((x) => fd.append(f.name, x));
    else if (f.type === "file") { if (v instanceof File) fd.append(f.name, v); }
    else fd.append(f.name, String(v ?? ""));
  }
  return fd;
}

