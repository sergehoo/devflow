import { Download } from "lucide-react";
import { Link } from "react-router";
import { Badge } from "@/components/ui/misc";
import { formatDate, formatDateTime } from "@/lib/format";
import type { CellValue } from "./api";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const ISO_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

function RefLink({ label, link }: { label: string; link: string | null }) {
  return link ? <Link className="font-medium text-brand hover:underline" to={link}>{label}</Link> : <span>{label}</span>;
}

/** Rendu d'une valeur sérialisée par le pont ressources (relation, choix, fichier, date…). */
export function Cell({ value }: { value: CellValue }) {
  if (value === null || value === undefined || value === "") return <span className="text-subtle-foreground">—</span>;
  if (typeof value === "boolean") return <span>{value ? "Oui" : "Non"}</span>;
  if (typeof value === "number") return <span className="tabular-nums">{value}</span>;
  if (typeof value === "string") {
    if (ISO_DATE.test(value)) return <span>{formatDate(value)}</span>;
    if (ISO_DATETIME.test(value)) return <span>{formatDateTime(value)}</span>;
    return <span className="whitespace-pre-line">{value}</span>;
  }
  switch (value.kind) {
    case "ref": return <RefLink label={value.label} link={value.link} />;
    case "choice": return <Badge>{value.label}</Badge>;
    case "file": return <a className="inline-flex items-center gap-1 text-brand hover:underline" href={value.url} target="_blank" rel="noreferrer"><Download className="size-3.5" />{value.label}</a>;
    case "list": return value.items.length ? <span className="flex flex-wrap gap-1">{value.items.map((i) => <Badge key={i.label}><RefLink {...i} /></Badge>)}</span> : <span className="text-subtle-foreground">—</span>;
  }
}
