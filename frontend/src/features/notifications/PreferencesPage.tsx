import { useState } from "react";
import { toast } from "sonner";
import { ErrorState } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { usePreferences, useUpdatePreferences, type NotificationPreferences } from "./api";

type Form = Omit<NotificationPreferences, "choices">;
const CHANNELS: [keyof Form, string, string][] = [
  ["channel_in_app", "Dans l'application", "Cloche, centre de notifications et alertes temps réel."],
  ["channel_email", "Par e-mail", "Envoi selon la fréquence et hors heures de calme."],
  ["channel_digest", "Digest récapitulatif", "Cumul des notifications sur la période."],
];
const HOURS = Array.from({ length: 24 }, (_, h) => h);

/** Préférences existantes (NotificationPreference) de l'utilisateur connecté. */
export function PreferencesPage() {
  const { data, isPending, isError, error, refetch } = usePreferences();
  const save = useUpdatePreferences();
  const [draft, setDraft] = useState<Partial<Form>>({});
  if (isPending) return <Skeleton className="h-96" />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;
  const v: Form = { ...data, ...draft };
  const set = (patch: Partial<Form>) => setDraft((d) => ({ ...d, ...patch }));
  const togglePriority = (value: string) =>
    set({ priority_types: v.priority_types.includes(value) ? v.priority_types.filter((t) => t !== value) : [...v.priority_types, value] });

  return (
    <form className="space-y-6" onSubmit={(e) => {
      e.preventDefault();
      save.mutate(draft, { onSuccess: () => { setDraft({}); toast.success("Préférences enregistrées."); }, onError: (err) => toast.error(err.message) });
    }}>
      <PageHeader eyebrow="Notifications" title="Préférences de notification" description="Ces réglages ne concernent que votre compte." />
      <Card>
        <CardHeader><CardTitle>Canaux</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {CHANNELS.map(([key, label, hint]) => (
            <label key={key} className="flex cursor-pointer items-start gap-3 rounded-xl border p-3 hover:bg-muted/40">
              <input type="checkbox" className="mt-1 size-4 accent-primary" checked={Boolean(v[key])} onChange={(e) => set({ [key]: e.target.checked })} />
              <span><span className="block text-sm font-medium">{label}</span><span className="block text-xs text-muted-foreground">{hint}</span></span>
            </label>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Fréquence et heures de calme</CardTitle></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-3">
          <Field id="notify_frequency" label="Fréquence des e-mails">
            <Select id="notify_frequency" value={v.notify_frequency} onChange={(e) => set({ notify_frequency: e.target.value })}>
              {data.choices.notify_frequency.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </Select>
          </Field>
          {(["quiet_hours_start", "quiet_hours_end"] as const).map((key) => (
            <Field key={key} id={key} label={key === "quiet_hours_start" ? "Début du silence" : "Fin du silence"} hint="Identiques = aucun silence.">
              <Select id={key} value={v[key]} onChange={(e) => set({ [key]: Number(e.target.value) })}>
                {HOURS.map((h) => <option key={h} value={h}>{String(h).padStart(2, "0")} h</option>)}
              </Select>
            </Field>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Types urgents (envoi immédiat, même pendant le silence)</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {data.choices.priority_types.map((c) => (
            <Button key={c.value} type="button" size="sm" variant={v.priority_types.includes(c.value) ? "default" : "outline"}
              aria-pressed={v.priority_types.includes(c.value)} onClick={() => togglePriority(c.value)}>{c.label}</Button>
          ))}
        </CardContent>
      </Card>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" disabled={!Object.keys(draft).length} onClick={() => setDraft({})}>Annuler</Button>
        <Button type="submit" disabled={!Object.keys(draft).length || save.isPending}>Enregistrer</Button>
      </div>
    </form>
  );
}
