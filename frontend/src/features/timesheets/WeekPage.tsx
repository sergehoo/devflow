import { ArrowLeft, Check, FileSpreadsheet, Lock, Plus, RotateCcw, Send, X } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { toast } from "sonner";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/misc";
import { DownloadButton } from "@/features/meetings/DownloadButton";
import { formatDateTime, formatHours, parseISODate, toISODate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useSaveCell, useWeek, useWeekAction, weekExportUrl, type Week, type WeekRow } from "./api";
import { STATUS_TONE, WEEK_BANNER } from "./constants";
import { PeriodNav, TimesheetTabs } from "./TimesheetNav";

function HoursCell({ row, date, hours, editable, label }: { row: WeekRow; date: string; hours: number; editable: boolean; label: string }) {
  const save = useSaveCell();
  const [value, setValue] = useState(hours ? String(hours) : "");
  if (!editable) return <span className={cn("tabular-nums", !hours && "text-subtle-foreground")}>{hours ? hours : "—"}</span>;
  const commit = () => {
    const normalized = value.replace(",", ".").trim() || "0";
    if (Number(normalized) === hours) return;
    const target = row.task ? { task_id: row.task.id } : { project_id: row.project?.id, description: row.description || row.label };
    save.mutate({ ...target, date, hours: normalized }, {
      onError: (e) => { toast.error(e.message); setValue(hours ? String(hours) : ""); },
    });
  };
  return (
    <input
      type="number" inputMode="decimal" min={0} max={24} step={0.25} value={value} aria-label={label}
      onChange={(e) => setValue(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
      className={cn("h-9 w-16 rounded-lg border bg-card px-2 text-right text-sm tabular-nums focus:border-ring focus:outline-none focus:ring-2 focus:ring-primary/20",
        save.isPending && "opacity-60")}
    />
  );
}

function ActivityDialog({ week, open, onOpenChange }: { week: Week; open: boolean; onOpenChange: (o: boolean) => void }) {
  const save = useSaveCell();
  const [form, setForm] = useState({ project_id: "", description: "", date: week.today >= week.monday && week.today <= week.days[6]!.date ? week.today : week.monday, hours: "" });
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    save.mutate({ project_id: Number(form.project_id), description: form.description.trim(), date: form.date, hours: form.hours }, {
      onSuccess: () => { toast.success("Activité enregistrée."); onOpenChange(false); setForm((f) => ({ ...f, description: "", hours: "" })); },
      onError: (err) => toast.error(err.message),
    });
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Nouvelle activité" description="Temps passé hors tâche (réunion, support…) sur un projet.">
      <form className="space-y-4" onSubmit={submit}>
        <div><Label htmlFor="act-project">Projet *</Label>
          <Select id="act-project" required value={form.project_id} onChange={(e) => setForm({ ...form, project_id: e.target.value })}>
            <option value="">Sélectionner…</option>{week.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select></div>
        <div><Label htmlFor="act-desc">Libellé *</Label><Input id="act-desc" required maxLength={200} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label htmlFor="act-date">Jour</Label>
            <Select id="act-date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })}>
              {week.days.map((d) => <option key={d.date} value={d.date}>{d.label} {parseISODate(d.date).getDate()}</option>)}
            </Select></div>
          <div><Label htmlFor="act-hours">Heures *</Label><Input id="act-hours" type="number" required min={0.25} max={24} step={0.25} value={form.hours} onChange={(e) => setForm({ ...form, hours: e.target.value })} /></div>
        </div>
        <div className="flex justify-end gap-2"><Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button><Button type="submit" disabled={save.isPending}>Enregistrer</Button></div>
      </form>
    </Dialog>
  );
}

export function WeekPage() {
  const [params, setParams] = useSearchParams();
  const date = params.get("date") ?? toISODate(new Date());
  const userId = params.get("user");
  const { data: week, isPending, isError, error, refetch } = useWeek(date, userId);
  const action = useWeekAction();
  const [dialog, setDialog] = useState<"activity" | "reject" | "reopen" | null>(null);
  const [comment, setComment] = useState("");

  const go = (d: string) => setParams((p) => { p.set("date", d); return p; });
  const run = (kind: "submit" | "approve" | "reject" | "reopen") => week && action.mutate(
    { user: week.user.id, monday: week.monday, action: kind, comment },
    {
      onSuccess: (r) => { (r.messages?.length ? r.messages : ["Semaine mise à jour."]).forEach((m) => toast.success(m)); setDialog(null); setComment(""); },
      onError: (e) => toast.error(e.message),
    },
  );

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Timesheets" title={week && !week.is_self ? `Semaine de ${week.user.name}` : "Mes heures"}
        actions={week && !week.is_self ? (
          <Button variant="outline" asChild><Link to={`/timesheets/sheets?user=${week.user.id}`}><ArrowLeft />Feuilles de {week.user.name}</Link></Button>
        ) : undefined} />
      <TimesheetTabs />
      {isPending ? <PageSkeleton /> : isError ? <ErrorState message={error.message} onRetry={() => void refetch()} /> : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <PeriodNav label={`Semaine ${week.iso_week} · ${week.year}`} date={week.monday} prev={week.prev_week} next={week.next_week} onChange={go} />
            <div className="flex flex-wrap items-center gap-2">
              <Badge className={STATUS_TONE[week.week_status]}>{WEEK_BANNER[week.week_status] ?? (week.rows.length ? week.week_status_label : "Aucune saisie")}</Badge>
              {week.is_self && !week.is_locked && <Button variant="outline" onClick={() => setDialog("activity")}><Plus />Activité</Button>}
              {week.is_self && week.can_submit && <Button disabled={action.isPending || !week.week_total} onClick={() => run("submit")}><Send />Soumettre la semaine</Button>}
              {week.can_review && week.week_status === "SUBMITTED" && (
                <>
                  <Button disabled={action.isPending} onClick={() => run("approve")}><Check />Valider</Button>
                  <Button variant="destructive" onClick={() => setDialog("reject")}><X />Rejeter</Button>
                </>
              )}
              {week.can_review && ["SUBMITTED", "APPROVED"].includes(week.week_status) && <Button variant="outline" onClick={() => setDialog("reopen")}><RotateCcw />Rouvrir</Button>}
              <DownloadButton href={weekExportUrl(week.monday, week.is_self ? null : week.user.id)} filename={`Timesheet_S${week.iso_week}.xlsx`}>
                <FileSpreadsheet aria-hidden="true" />Exporter en Excel
              </DownloadButton>
            </div>
          </div>

          {week.is_self && week.is_locked && (
            <p className="flex items-center gap-2 rounded-2xl bg-muted px-4 py-3 text-sm text-muted-foreground"><Lock className="size-4" aria-hidden="true" />Semaine soumise ou validée : elle n'est plus modifiable.</p>
          )}

          {week.summary && (
            <section aria-label="Indicateurs de la semaine" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              {([
                ["Saisi", formatHours(week.summary.total_hours)], ["Attendu", formatHours(week.summary.expected)],
                ["Capacité", formatHours(week.summary.capacity)], ["Manquant", formatHours(week.summary.missing_hours)],
                ["Complétion", `${week.summary.completion_percent} %`],
              ] as const).map(([k, v]) => (
                <Card key={k}><CardContent className="py-4"><p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{k}</p><p className="mt-1 font-serif text-xl font-semibold tabular-nums">{v}</p></CardContent></Card>
              ))}
            </section>
          )}

          <div className="overflow-x-auto rounded-[22px] border border-transparent bg-card shadow-card dark:border-border">
            <table className="w-full min-w-[820px] text-sm">
              <caption className="sr-only">Heures de la semaine {week.iso_week}</caption>
              <thead className="border-b bg-muted/50 text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Tâche / activité</th>
                  {week.days.map((d) => (
                    <th key={d.date} scope="col" className={cn("px-2 py-3 text-center font-semibold", d.date === week.today && "text-brand")}>
                      {d.label}<span className="block text-[11px] font-normal">{parseISODate(d.date).getDate()}/{parseISODate(d.date).getMonth() + 1}</span>
                    </th>
                  ))}
                  <th scope="col" className="px-4 py-3 text-right font-semibold">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {week.rows.map((row) => (
                  <tr key={row.row_id}>
                    <th scope="row" className="max-w-72 px-4 py-2 text-left font-normal">
                      {row.task ? <Link to={`/tasks/${row.task.id}`} className="font-medium hover:text-brand">{row.task.title}</Link> : <span className="font-medium">{row.label}</span>}
                      <span className="block truncate text-xs text-muted-foreground">{row.project?.name ?? "—"}{row.kind === "activity" && " · activité"}</span>
                    </th>
                    {row.cells.map((c, i) => (
                      <td key={c.date} className="px-2 py-2 text-center">
                        <HoursCell key={`${row.row_id}-${c.date}-${c.hours}`} row={row} date={c.date} hours={c.hours}
                          editable={week.is_self && !week.is_locked} label={`${row.label} — ${week.days[i]?.label} : heures`} />
                      </td>
                    ))}
                    <td className="px-4 py-2 text-right font-semibold tabular-nums">{row.total || "—"}</td>
                  </tr>
                ))}
                {!week.rows.length && (
                  <tr><td colSpan={9} className="px-4 py-10 text-center text-muted-foreground">Aucune tâche active ni saisie cette semaine.</td></tr>
                )}
              </tbody>
              <tfoot className="border-t bg-muted/40 font-semibold">
                <tr>
                  <th scope="row" className="px-4 py-3 text-left">Total jour</th>
                  {week.days.map((d) => <td key={d.date} className="px-2 py-3 text-center tabular-nums">{week.day_totals[d.date] || "—"}</td>)}
                  <td className="px-4 py-3 text-right tabular-nums">{formatHours(week.week_total)}</td>
                </tr>
              </tfoot>
            </table>
          </div>

          {week.history.length > 0 && (
            <Card>
              <CardHeader><CardTitle>Historique de validation</CardTitle></CardHeader>
              <CardContent>
                <ol className="space-y-2 text-sm">
                  {week.history.map((h) => (
                    <li key={h.created_at}><span className="font-semibold">{h.action_label}</span> par {h.actor || "—"} · {formatDateTime(h.created_at)}{h.comment && <span className="block text-muted-foreground">« {h.comment} »</span>}</li>
                  ))}
                </ol>
              </CardContent>
            </Card>
          )}

          {week.is_self && <ActivityDialog key={week.monday} week={week} open={dialog === "activity"} onOpenChange={(o) => setDialog(o ? "activity" : null)} />}
          <Dialog open={dialog === "reject" || dialog === "reopen"} onOpenChange={(o) => !o && setDialog(null)}
            title={dialog === "reject" ? "Rejeter la semaine" : "Rouvrir la semaine"}
            description={dialog === "reject" ? "Le commentaire est transmis au collaborateur (obligatoire)." : "Déverrouillage exceptionnel, tracé dans l'historique."}>
            <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); run(dialog === "reject" ? "reject" : "reopen"); }}>
              <div><Label htmlFor="ts-comment">Commentaire{dialog === "reject" && " *"}</Label>
                <Textarea id="ts-comment" rows={3} required={dialog === "reject"} value={comment} onChange={(e) => setComment(e.target.value)} /></div>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="outline" onClick={() => setDialog(null)}>Annuler</Button>
                <Button type="submit" variant={dialog === "reject" ? "destructive" : "default"} disabled={action.isPending || (dialog === "reject" && !comment.trim())}>
                  {dialog === "reject" ? "Rejeter" : "Rouvrir"}
                </Button>
              </div>
            </form>
          </Dialog>
        </>
      )}
    </div>
  );
}
