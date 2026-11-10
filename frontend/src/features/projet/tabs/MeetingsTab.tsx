import { ArrowRight, CalendarPlus, Clock } from "lucide-react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";
import type { MeetingsTab as Data } from "../api";
import { colorTone } from "../format";
import { Pill, Section } from "../ui";

/** Onglet Réunions : réunions du projet (pages réunions servies par le module Réunions React). */
export function MeetingsTab({ projectId, data }: { projectId: number; data: Data }) {
  const newMeeting = `/meetings?project=${projectId}`;
  return (
    <Section title="Réunions du projet" description="Notes, décisions et actions tracées par DevFlow." count={data.count}
      actions={<Button size="sm" asChild><Link to={newMeeting}><CalendarPlus />Nouvelle réunion</Link></Button>}>
      {data.meetings.length ? (
        <>
          <ul className="divide-y rounded-xl border">
            {data.meetings.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <Link to={`/meetings/${m.id}`} className="font-medium hover:text-brand">{m.title}</Link>
                  <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1"><Clock className="size-3" aria-hidden="true" />{formatDateTime(m.scheduled_at)}</span>
                    <Pill tone="info">{m.meeting_type_label}</Pill>
                    <Pill tone={colorTone(m.status_color)}>{m.status_label}</Pill>
                    {m.action_items_count > 0 && <span>· {m.action_items_count} action(s)</span>}
                  </p>
                </div>
                <Button size="icon" variant="ghost" asChild><Link to={`/meetings/${m.id}`} aria-label={`Ouvrir la réunion ${m.title}`}><ArrowRight /></Link></Button>
              </li>
            ))}
          </ul>
          {data.count > data.meetings.length && (
            <p className="pt-3 text-center text-xs"><Link to={`/meetings?project=${projectId}`} className="font-semibold text-brand hover:underline">Voir les {data.count} réunions →</Link></p>
          )}
        </>
      ) : (
        <div className="flex flex-col items-center gap-3 py-10 text-center text-muted-foreground">
          <p>Aucune réunion enregistrée pour ce projet.</p>
          <Button size="sm" asChild><Link to={newMeeting}><CalendarPlus />Planifier la première réunion</Link></Button>
        </div>
      )}
    </Section>
  );
}
