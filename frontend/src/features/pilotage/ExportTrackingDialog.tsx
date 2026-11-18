import { FileSpreadsheet, ListFilter, Loader2, Search } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { ErrorState } from "@/components/feedback/states";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input, Label, Select } from "@/components/ui/input";
import { Badge, Skeleton } from "@/components/ui/misc";
import { useMe } from "@/features/auth/api";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ApiError } from "@/services/api";
import { EXPORT_ERROR, downloadSelectionExport, useExportProjects, type ExportMode, type ExportPeriod } from "./api";

/** Présélection facultative : les projets filtrés de la liste d'origine (jamais cochés d'office). */
export interface Preselection { count?: number; load: () => Promise<number[]> }

type Kind = ExportPeriod["kind"];
const KINDS: [Kind, string][] = [["month", "Mois"], ["quarter", "Trimestre"], ["year", "Année"], ["custom", "Dates"]];
const MONTHS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"];
const MODES: [ExportMode, string, string][] = [
  ["full", "Suivi complet", "Toutes les lignes des projets cochés, même anciens, dans l'état connu à la fin de la période."],
  ["period", "Activités de la période", "Uniquement les lignes ayant une action menée pendant la période, limitées à ces actions."],
];
const MAX_YEARS = 5;

const pad = (n: number) => String(n).padStart(2, "0");
const iso = (y: number, m: number, d: number) => `${y}-${pad(m)}-${pad(d)}`;
const lastDay = (y: number, m: number) => new Date(y, m, 0).getDate();
const fold = (text: string) => text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

/** Bornes de la période (AAAA-MM-JJ), mêmes règles que Django. */
function periodRange(p: ExportPeriod): { start: string; end: string } {
  if (p.kind === "custom") return { start: p.start, end: p.end };
  if (p.kind === "year") return { start: iso(p.year, 1, 1), end: iso(p.year, 12, 31) };
  if (p.kind === "quarter") return { start: iso(p.year, 3 * p.quarter - 2, 1), end: iso(p.year, 3 * p.quarter, lastDay(p.year, 3 * p.quarter)) };
  return { start: iso(p.year, p.month, 1), end: iso(p.year, p.month, lastDay(p.year, p.month)) };
}

function periodError(p: ExportPeriod): string | null {
  if (p.kind !== "custom") return null;
  if (!p.start || !p.end) return "Indiquez une date de début et une date de fin.";
  const valid = /^\d{4}-\d{2}-\d{2}$/;
  if (!valid.test(p.start) || !valid.test(p.end) || Number.isNaN(Date.parse(p.start)) || Number.isNaN(Date.parse(p.end))) {
    return "Date invalide.";
  }
  const [y1, y2] = [Number(p.start.slice(0, 4)), Number(p.end.slice(0, 4))];
  if (y1 < 2000 || y1 > 2100 || y2 < 2000 || y2 > 2100) return "Les dates doivent être comprises entre 2000 et 2100.";
  if (p.end < p.start) return "La période se termine avant de commencer.";
  if (p.end > `${y1 + MAX_YEARS}-${p.start.slice(5, 7)}-01`) return `La période ne peut pas dépasser ${MAX_YEARS} ans.`;
  return null;
}

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-3" aria-label={title}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

/**
 * Fenêtre « Exporter le suivi Excel » : projets cochés, période et mode. Le classeur garde le
 * modèle de la Direction ; Django applique le périmètre et refuse tout projet non accessible.
 */
export function ExportTrackingDialog({ open, onOpenChange, preselect }: {
  open: boolean; onOpenChange: (open: boolean) => void; preselect?: Preselection;
}) {
  const { data: me } = useMe();
  const projects = useExportProjects(me?.workspace?.id, open && Boolean(me));
  const now = new Date();
  const [q, setQ] = useState("");
  const [checked, setChecked] = useState<Set<number>>(() => new Set());
  const [kind, setKind] = useState<Kind>("month");
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [quarter, setQuarter] = useState(Math.floor(now.getMonth() / 3) + 1);
  const [start, setStart] = useState(iso(now.getFullYear(), now.getMonth() + 1, 1));
  const [end, setEnd] = useState(iso(now.getFullYear(), now.getMonth() + 1, now.getDate()));
  const [mode, setMode] = useState<ExportMode>("full");
  const [pending, setPending] = useState(false);
  const [presetting, setPresetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const all = useMemo(() => projects.data?.projects ?? [], [projects.data]);
  const known = useMemo(() => new Set(all.map((p) => p.id)), [all]);
  const visible = useMemo(() => {
    const tokens = fold(q).split(/\s+/).filter(Boolean);
    return all.filter((p) => tokens.every((t) => fold(`${p.name} ${p.code} ${p.workspace.name}`).includes(t)));
  }, [all, q]);
  // Les cases cochées comptent seules : un projet masqué par la recherche reste coché.
  const selected = all.filter((p) => checked.has(p.id));
  const hidden = selected.filter((p) => !visible.includes(p)).length;
  const max = projects.data?.max ?? 500;
  const years = Array.from({ length: 8 }, (_, i) => now.getFullYear() - 6 + i);

  const period: ExportPeriod = kind === "custom" ? { kind, start, end }
    : kind === "year" ? { kind, year } : kind === "quarter" ? { kind, year, quarter } : { kind, year, month };
  const invalidPeriod = periodError(period);
  const range = periodRange(period);
  const tooMany = selected.length > max;

  const toggle = (id: number) => setChecked((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const selectVisible = () => setChecked((prev) => new Set([...prev, ...visible.map((p) => p.id)]));
  const clear = () => { setChecked(new Set()); setNotice(null); };

  const applyPreselection = async () => {
    if (!preselect) return;
    setPresetting(true);
    setError(null);
    try {
      const ids = await preselect.load();
      const kept = ids.filter((id) => known.has(id));
      setChecked(new Set(kept));
      const ignored = ids.length - kept.length;
      setNotice(`${kept.length} projet(s) coché(s) d'après les filtres de la liste${ignored ? ` · ${ignored} hors export ignoré(s)` : ""}.`);
    } catch {
      setError("Impossible de reprendre les filtres de la liste.");
    } finally {
      setPresetting(false);
    }
  };

  const submit = async () => {
    setError(null);
    if (!selected.length) return setError("Sélectionnez au moins un projet.");
    if (invalidPeriod) return setError(invalidPeriod);
    setPending(true);
    try {
      const { rows } = await downloadSelectionExport({ projects: selected.map((p) => p.id), period, mode });
      toast.success(rows ? `Suivi Excel téléchargé (${rows} ligne(s)).` : "Suivi Excel téléchargé : aucune ligne pour cette période.");
      onOpenChange(false);
    } catch (e) {
      const refused = e instanceof ApiError ? (e.data as { inaccessible?: number[] } | null)?.inaccessible ?? [] : [];
      if (refused.length) {
        setChecked((prev) => new Set([...prev].filter((id) => !refused.includes(id))));
        void projects.refetch();
      }
      setError(e instanceof ApiError ? e.message : EXPORT_ERROR);
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Exporter le suivi Excel" className="sm:max-w-3xl"
      description="Classeur de suivi de la Direction (même modèle), limité aux projets cochés et à la période choisie.">
      <div className="space-y-6">
        <Section title="Projets" aside={
          <div className="flex flex-wrap gap-1.5">
            {preselect && (
              <Button size="sm" variant="outline" disabled={presetting || !all.length} onClick={() => void applyPreselection()}>
                {presetting ? <Loader2 className="animate-spin" aria-hidden="true" /> : <ListFilter aria-hidden="true" />}
                Reprendre les filtres de la liste{preselect.count !== undefined ? ` (${preselect.count})` : ""}
              </Button>
            )}
            <Button size="sm" variant="ghost" disabled={!visible.length} onClick={selectVisible}>
              Tout sélectionner{q ? ` (${visible.length})` : ""}
            </Button>
            <Button size="sm" variant="ghost" disabled={!checked.size} onClick={clear}>Tout désélectionner</Button>
          </div>
        }>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden="true" />
            <Input type="search" className="pl-9" placeholder="Rechercher un projet (nom, code)…" aria-label="Rechercher un projet à exporter"
              value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {projects.isPending ? <Skeleton className="h-56" /> : projects.isError ? (
            <ErrorState message={projects.error.message} onRetry={() => void projects.refetch()} />
          ) : !all.length ? (
            <p className="rounded-2xl bg-hover px-4 py-6 text-center text-sm text-muted-foreground">Aucun projet exportable dans cet espace.</p>
          ) : (
            <ul aria-label="Projets à exporter" className="max-h-64 divide-y overflow-y-auto rounded-2xl border bg-card">
              {visible.length ? visible.map((p) => {
                const on = checked.has(p.id);
                return (
                  <li key={p.id}>
                    <label className={cn("flex cursor-pointer items-center gap-3 px-3 py-2.5 transition-colors hover:bg-hover", on && "bg-primary-faint")}>
                      <input type="checkbox" checked={on} onChange={() => toggle(p.id)} className="size-4 shrink-0 accent-[var(--primary-strong)]" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">
                          {p.name}{p.code && <span className="ml-1.5 text-xs font-normal text-muted-foreground">{p.code}</span>}
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {p.is_activities ? `${p.activity_count} activité(s) du suivi`
                            : `${p.start_date || p.target_date ? `${formatDate(p.start_date)} → ${formatDate(p.target_date)}` : "Dates non renseignées"} · ${p.progress} %`}
                        </span>
                      </span>
                      {p.is_activities ? <Badge className="bg-primary-soft text-foreground">Activités</Badge> : <Badge>{p.status_label}</Badge>}
                    </label>
                  </li>
                );
              }) : <li className="px-3 py-6 text-center text-sm text-muted-foreground">Aucun projet pour « {q} ».</li>}
            </ul>
          )}
          <p className="text-xs text-muted-foreground" aria-live="polite">
            <strong className="font-semibold text-foreground">{selected.length}</strong> projet(s) coché(s) sur {all.length}
            {hidden ? ` · dont ${hidden} masqué(s) par la recherche` : ""}{notice ? ` · ${notice}` : ""}
          </p>
          {tooMany && <p className="text-xs font-medium text-destructive">{max} projets au maximum par fichier : répartissez la sélection.</p>}
        </Section>

        <Section title="Période" aside={<span className="text-xs text-muted-foreground">Du {formatDate(range.start)} au {formatDate(range.end)}</span>}>
          <div className="flex rounded-full bg-hover p-1 text-xs font-semibold" role="radiogroup" aria-label="Type de période">
            {KINDS.map(([value, label]) => (
              <button key={value} type="button" role="radio" aria-checked={kind === value} onClick={() => setKind(value)}
                className={cn("flex-1 rounded-full px-3 py-1.5", kind === value ? "bg-card shadow-card" : "text-muted-foreground")}>
                {label}
              </button>
            ))}
          </div>
          {kind === "custom" ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5"><Label htmlFor="export-start">Début</Label>
                <Input id="export-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} aria-invalid={Boolean(invalidPeriod)} /></div>
              <div className="space-y-1.5"><Label htmlFor="export-end">Fin</Label>
                <Input id="export-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} aria-invalid={Boolean(invalidPeriod)} /></div>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {kind === "month" && (
                <Select aria-label="Mois" value={month} onChange={(e) => setMonth(Number(e.target.value))}>
                  {MONTHS.map((label, i) => <option key={label} value={i + 1}>{label}</option>)}
                </Select>
              )}
              {kind === "quarter" && (
                <Select aria-label="Trimestre" value={quarter} onChange={(e) => setQuarter(Number(e.target.value))}>
                  {[1, 2, 3, 4].map((t) => <option key={t} value={t}>{`T${t} (${MONTHS[3 * t - 3]} – ${MONTHS[3 * t - 1]})`}</option>)}
                </Select>
              )}
              <Select aria-label="Année" value={year} onChange={(e) => setYear(Number(e.target.value))}>
                {years.map((y) => <option key={y} value={y}>{y}</option>)}
              </Select>
            </div>
          )}
          {invalidPeriod && <p className="text-xs font-medium text-destructive">{invalidPeriod}</p>}
        </Section>

        <Section title="Contenu">
          <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Contenu du fichier">
            {MODES.map(([value, label, hint]) => (
              <label key={value} className={cn("flex cursor-pointer gap-3 rounded-2xl border p-3 transition-colors hover:bg-hover",
                mode === value && "border-primary-strong bg-primary-faint")}>
                <input type="radio" name="export-mode" value={value} checked={mode === value} onChange={() => setMode(value)}
                  className="mt-0.5 size-4 shrink-0 accent-[var(--primary-strong)]" />
                <span><span className="block text-sm font-semibold">{label}</span><span className="block text-xs text-muted-foreground">{hint}</span></span>
              </label>
            ))}
          </div>
        </Section>

        {error && <p role="alert" className="rounded-2xl bg-destructive/10 px-4 py-3 text-sm text-destructive">{error}</p>}

        <div className="flex flex-col-reverse gap-2 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">
            {selected.length} projet(s) · {formatDate(range.start)} → {formatDate(range.end)} · {MODES.find(([v]) => v === mode)?.[1]}
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
            <Button disabled={pending || !selected.length || Boolean(invalidPeriod) || tooMany} aria-busy={pending} onClick={() => void submit()}>
              {pending ? <Loader2 className="animate-spin" aria-hidden="true" /> : <FileSpreadsheet aria-hidden="true" />}
              {pending ? "Génération…" : "Télécharger l'Excel"}
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}
