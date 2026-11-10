/** Panneau du mode métier (port de templates/project/modes/*.html) : phases, rapports terrain, lots, dossiers. */
import { AlertTriangle, CalendarClock, MapPin, User, Users } from "lucide-react";
import { formatDate, formatDateTime } from "@/lib/format";
import type { ModeData } from "./api";
import type { Tone } from "./format";
import { EmptyLine, Pill, ProgressBar, Section, Table, Td } from "./ui";

const phaseTone = (s: string): Tone => ({ DONE: "success", IN_PROGRESS: "warning", REVIEW: "info", BLOCKED: "danger" } as Record<string, Tone>)[s] ?? "primary";
const lotTone = (s: string): Tone =>
  ({ SOLD: "success", DELIVERED: "success", RESERVED: "warning", OPTION: "warning", WITHDRAWN: "danger" } as Record<string, Tone>)[s] ?? "info";
const caseTone = (s: string): Tone =>
  ({ APPROVED: "success", REJECTED: "danger", AWAITING_INFO: "warning", UNDER_REVIEW: "info", SUBMITTED: "primary" } as Record<string, Tone>)[s] ?? "muted";

export function ModePanel({ mode }: { mode: ModeData }) {
  if (mode.kind === "waterfall") {
    return (
      <Section title="Phases du projet" description="Pilotage séquentiel — validations (gates) aux étapes critiques" actions={<Pill tone="info">Waterfall</Pill>}>
        {mode.phases.length ? (
          <ol className="space-y-3">
            {mode.phases.map((p, i) => (
              <li key={p.id} className="flex items-start gap-3">
                <span aria-hidden="true" className="flex size-8 shrink-0 items-center justify-center rounded-full border bg-muted text-xs font-semibold">{i + 1}</span>
                <div className="min-w-0 flex-1 rounded-xl border bg-muted/30 p-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="font-semibold">{p.name}{p.gate_required && <Pill tone="warning" className="ml-2">Gate</Pill>}</p>
                      {p.description && <p className="text-xs text-muted-foreground">{p.description}</p>}
                    </div>
                    <Pill tone={phaseTone(p.status)}>{p.status_label}</Pill>
                  </div>
                  <p className="mt-1 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
                    {p.start_date && <span className="inline-flex items-center gap-1"><CalendarClock className="size-3" aria-hidden="true" />{formatDate(p.start_date)}{p.end_date ? ` → ${formatDate(p.end_date)}` : ""}</span>}
                    {p.owner && <span className="inline-flex items-center gap-1"><User className="size-3" aria-hidden="true" />{p.owner}</span>}
                  </p>
                  <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground"><span>Avancement</span><span>{p.progress_percent} %</span></div>
                  <ProgressBar value={p.progress_percent} label={`Avancement de la phase ${p.name}`} className="mt-1"
                    barClassName={p.progress_percent >= 100 ? "bg-success" : p.progress_percent >= 50 ? "bg-warning" : undefined} />
                </div>
              </li>
            ))}
          </ol>
        ) : <EmptyLine>Aucune phase définie pour ce projet Waterfall (ajout via l'API des phases ou génération IA).</EmptyLine>}
      </Section>
    );
  }
  if (mode.kind === "field") {
    return (
      <Section title="Rapports de chantier" description={`Suivi journalier · ${mode.reports.length} affiché(s)`} actions={<Pill tone="warning">Terrain</Pill>}>
        {mode.reports.length ? (
          <ul className="space-y-3">
            {mode.reports.map((r) => (
              <li key={r.id} className="rounded-xl border bg-muted/30 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold">{formatDate(r.report_date)}</p>
                    {r.location_name && <p className="inline-flex items-center gap-1 text-xs text-muted-foreground"><MapPin className="size-3" aria-hidden="true" />{r.location_name}{r.location ? ` · ${r.location}` : ""}</p>}
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    {r.weather_label && <Pill>{r.weather_label}</Pill>}
                    {r.workforce_count > 0 && <span className="inline-flex items-center gap-1 text-muted-foreground"><Users className="size-3" aria-hidden="true" />{r.workforce_count}</span>}
                  </div>
                </div>
                {r.notes && <p className="mt-2 text-xs text-muted-foreground">{r.notes}</p>}
                {r.incidents && <p className="mt-2 flex items-start gap-1.5 rounded-lg border border-destructive/20 bg-destructive/10 px-2 py-1.5 text-xs text-destructive"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />{r.incidents}</p>}
                {r.photos.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {r.photos.map((ph) => ph.url && (
                      <a key={ph.id} href={ph.url} target="_blank" rel="noopener noreferrer" className="block size-16 overflow-hidden rounded-lg border hover:border-primary">
                        <img src={ph.url} alt={ph.caption || "Photo de chantier"} className="size-full object-cover" />
                      </a>
                    ))}
                    {r.photos_count > r.photos.length && <span className="flex size-16 items-center justify-center rounded-lg border bg-muted text-xs text-muted-foreground">+{r.photos_count - r.photos.length}</span>}
                  </div>
                )}
                <p className="mt-2 flex justify-between text-[11px] text-muted-foreground"><span>{r.reporter || "—"}</span><span>{formatDateTime(r.created_at)}</span></p>
              </li>
            ))}
          </ul>
        ) : <EmptyLine>Aucun rapport de chantier.</EmptyLine>}
      </Section>
    );
  }
  if (mode.kind === "real_estate") {
    return (
      <Section title="Lots du programme" description={`${mode.lots.length} lot(s)`} actions={<Pill tone="success">Immobilier</Pill>}>
        {mode.lots.length ? (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">{mode.groups.map((g) => <Pill key={g.status} tone={lotTone(g.status)}>{g.label} · {g.count}</Pill>)}</div>
            <Table caption="Lots" minWidth="min-w-[640px]" head={["Lot", "Étage", "Surface", "Pièces", "Prix", "Statut", "Acquéreur"]}>
              {mode.lots.map((l) => (
                <tr key={l.id} className="hover:bg-muted/40">
                  <Td className="font-semibold">{l.lot_number}</Td>
                  <Td className="text-muted-foreground">{l.floor || "—"}</Td>
                  <Td className="text-right tabular-nums">{Number(l.surface_m2)} m²</Td>
                  <Td className="text-right tabular-nums">{l.bedrooms}</Td>
                  <Td className="text-right tabular-nums">{l.price ? `${Number(l.price).toLocaleString("fr-FR")} ${l.currency}` : "—"}</Td>
                  <Td><Pill tone={lotTone(l.status)}>{l.status_label}</Pill></Td>
                  <Td className="text-muted-foreground">{l.buyer_name || "—"}</Td>
                </tr>
              ))}
            </Table>
          </div>
        ) : <EmptyLine>Aucun lot défini.</EmptyLine>}
      </Section>
    );
  }
  return (
    <Section title="Dossiers administratifs" description={`${mode.cases.length} dossier(s)`} actions={<Pill tone="primary">Administratif</Pill>}>
      {mode.cases.length ? (
        <Table caption="Dossiers" minWidth="min-w-[700px]" head={["Référence", "Objet", "Type de document", "Statut", "Échéance", "Responsable"]}>
          {mode.cases.map((c) => (
            <tr key={c.id} className="hover:bg-muted/40">
              <Td className="font-semibold">{c.reference}</Td>
              <Td><span className="font-medium">{c.title}</span>{c.applicant && <span className="block text-xs text-muted-foreground">{c.applicant}</span>}</Td>
              <Td className="text-muted-foreground">{c.document_type || "—"}</Td>
              <Td><Pill tone={caseTone(c.status)}>{c.status_label}</Pill></Td>
              <Td className={c.is_overdue ? "font-semibold text-destructive" : "text-muted-foreground"}>
                {formatDate(c.deadline)}{c.sla_days ? <span className="block text-[11px] text-muted-foreground">SLA {c.sla_days} j</span> : null}
              </Td>
              <Td className="text-muted-foreground">{c.assignee || "Non affecté"}</Td>
            </tr>
          ))}
        </Table>
      ) : <EmptyLine>Aucun dossier administratif.</EmptyLine>}
    </Section>
  );
}
