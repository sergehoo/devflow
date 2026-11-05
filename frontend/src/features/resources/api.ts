import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, actionBody } from "@/services/api";

export interface ResourceMeta {
  name: string; title: string; singular: string; group: string; permission: string; superuser: boolean;
  legacy_list: string; can_create: boolean; has_detail: boolean; can_update: boolean; can_delete: boolean;
}
export type CellValue =
  | string | number | boolean | null
  | { kind: "ref"; label: string; link: string | null }
  | { kind: "choice"; value: string; label: string }
  | { kind: "file"; label: string; url: string }
  | { kind: "list"; items: { label: string; link: string | null }[] };
export interface ResourceRow { id: number; label: string; link: string | null; cells: Record<string, CellValue> }
export interface ResourceList { columns: { name: string; label: string }[]; results: ResourceRow[]; count: number; page: number; num_pages: number }
export interface ResourceDetail {
  id: number; label: string; legacy_url: string;
  fields: { name: string; label: string; value: CellValue }[];
  actions: { code: string; label: string }[];
  downloads: { label: string; href: string }[];
}

export const RESOURCES_KEY = ["resources"] as const;

export function useRegistry() {
  return useQuery({
    queryKey: [...RESOURCES_KEY, "registry"],
    queryFn: ({ signal }) => api<{ resources: ResourceMeta[] }>("resources/", { signal }),
    staleTime: Infinity,
    select: (d) => Object.fromEntries(d.resources.map((r) => [r.name, r])) as Record<string, ResourceMeta>,
  });
}

export function useResourceList(name: string, params: Record<string, string>) {
  return useQuery({
    queryKey: [...RESOURCES_KEY, name, "list", params],
    queryFn: ({ signal }) => api<ResourceList>(`resources/${name}/`, { signal, params }),
    placeholderData: (prev) => prev,
  });
}

export function useResourceDetail(name: string, id: number) {
  return useQuery({
    queryKey: [...RESOURCES_KEY, name, id],
    queryFn: ({ signal }) => api<ResourceDetail>(`resources/${name}/${id}/`, { signal }),
  });
}

/** Suppression / action : exécutées par les vues Django (messages renvoyés). */
export function useResourceMutation(name: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: string }) =>
      api<{ messages?: string[] }>(action === "delete" ? `resources/${name}/${id}/delete/` : `resources/${name}/${id}/actions/${action}/`,
        { method: "POST", body: actionBody() }),
    onSuccess: () => qc.invalidateQueries({ queryKey: RESOURCES_KEY }),
  });
}

/** Modification ponctuelle via le formulaire Django (relit le formulaire, applique `patch`, renvoie). */
export async function patchThroughForm(name: string, id: number, patch: Record<string, string | boolean>) {
  const schema = await api<{ fields: { name: string; type: string; value: unknown; disabled?: boolean }[] }>(`forms/${name}/${id}/`);
  const fd = new FormData();
  for (const f of schema.fields) {
    if (f.disabled || f.type === "file") continue;
    const v = f.name in patch ? patch[f.name] : f.value;
    if (f.type === "checkbox") { if (v) fd.append(f.name, "on"); }
    else if (Array.isArray(v)) v.forEach((x) => fd.append(f.name, String(x)));
    else fd.append(f.name, v == null ? "" : String(v));
  }
  return api<{ id: number; messages: string[] }>(`forms/${name}/${id}/`, { method: "POST", body: fd });
}
