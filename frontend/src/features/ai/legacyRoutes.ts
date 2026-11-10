const ID = /^\d+$/;

/** Cible React d'une page générique `/m/ai-proposal…` ou `/m/project-import…` (pont en lecture seule). */
export function aiModuleTarget(pathname: string, search: string): string {
  const [, , resource = "", id = ""] = pathname.replace(/\/+$/, "").split("/");
  const query = new URLSearchParams(search);
  if (resource === "ai-proposal") {
    if (ID.test(id)) return `/ai-proposals/${id}`;
    const keep = new URLSearchParams([...query].filter(([k, v]) => (k === "status" || k === "project") && v));
    return keep.toString() ? `/ai-proposals?${keep}` : "/ai-proposals";
  }
  if (ID.test(id)) return `/imports/${id}`;
  if (id === "new") {
    const project = query.get("project") ?? "";
    return ID.test(project) ? `/imports?new=1&project=${project}` : "/imports?new=1";
  }
  const keep = new URLSearchParams([...query].filter(([k, v]) => ["q", "status", "project", "workspace", "page"].includes(k) && v));
  return keep.toString() ? `/imports?${keep}` : "/imports";
}
