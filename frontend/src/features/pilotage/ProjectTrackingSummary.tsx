/**
 * Fiche projet › synthèse de suivi : vue consolidée des tâches, risques, décisions et du
 * journal existants (aucune donnée propre). Masquée si le projet n'est pas visible dans le suivi.
 */
import type { ReactNode } from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Pill, Section } from "@/features/projet/ui";
import { formatDate, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useProjectTracking } from "./api";
import { STATUS_TONE } from "./format";
import { Progress, RowDetail } from "./ui";

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-1 break-words text-sm">{children}</dd>
    </div>
  );
}

export function ProjectTrackingSummary({ projectId }: { projectId: number }) {
  const { data } = useProjectTracking(projectId);
  if (!data || (!data.row && data.activities.length === 0 && data.recent.length === 0)) return null;
  const { row, activities, recent } = data;
  return (
    <Section
      title="Synthèse de suivi"
      description="Vue consolidée des tâches, risques, décisions et du journal du projet."
      actions={<Button variant="outline" size="sm" asChild><Link to={`/pilotage/suivi?project=${projectId}`}>Ouvrir dans le suivi</Link></Button>}
    >
      <div className="space-y-6">
        {row && (
          <>
            <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Fact label="Progression">
                <Progress value={row.progress} label="Progression du projet" className="max-w-56" />
                <Pill tone={STATUS_TONE[row.status_key]} className="mt-2">{row.sheet_status}</Pill>
              </Fact>
              <Fact label="Échéance">
                <span className={cn(row.late && "font-semibold text-destructive")}>{formatDate(row.end)}</span>
                {row.late && <Pill tone="danger" className="ml-2">{row.days_late} j de retard</Pill>}
                {!row.late && row.due_soon && <Pill tone="warning" className="ml-2">Proche</Pill>}
              </Fact>
              <Fact label="Porteur">{row.owners.map((o) => o.name).join(", ") || "Non attribué"}</Fact>
              <Fact label="Interlocuteurs">{row.contacts.join(", ") || "—"}</Fact>
            </dl>
            <RowDetail row={row} />
          </>
        )}
        {activities.length > 0 && (
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Activités suivies · {activities.length}</h4>
            <ul className="divide-y text-sm">
              {activities.map((a) => (
                <li key={a.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2">
                  <Link to={a.url} className="min-w-0 flex-1 basis-56 font-medium hover:text-brand">{a.title}</Link>
                  <span className="text-muted-foreground">{a.owners.map((o) => o.name).join(", ") || "Non attribué"}</span>
                  <Progress value={a.progress} label={`Avancement de ${a.title}`} className="w-32" />
                  <Pill tone={STATUS_TONE[a.status_key]}>{a.sheet_status}</Pill>
                  {a.late && <Pill tone="danger">{a.days_late} j</Pill>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {recent.length > 0 && (
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Dernières activités</h4>
            <ul className="space-y-1.5 text-sm">
              {recent.map((r) => (
                <li key={r.id} className="flex flex-wrap gap-x-2">
                  <span className="min-w-0 break-words">{r.title}</span>
                  <span className="text-xs text-muted-foreground">{[r.actor, formatDateTime(r.created_at)].filter(Boolean).join(" · ")}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Section>
  );
}
