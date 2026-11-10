import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, TriangleAlert, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { AI_KEY, useGenerationStatus } from "./api";
import { MAX_POLL_MS } from "./constants";
import { ProgressBar } from "./shared";

const DONE = new Set(["READY", "PARTIALLY_VALIDATED", "VALIDATED", "APPLIED"]);

/**
 * Suivi d'une génération de proposition IA (miroir du bandeau de la fiche projet historique) :
 * interroge `projects/<id>/ai-proposals/status/` toutes les 3 s tant que la génération tourne.
 */
export function GenerationTracker({ projectId, active, onFinished, onDismiss }: {
  projectId: number;
  /** Suivi demandé (déclenchement ou génération en cours au chargement). */
  active: boolean;
  onFinished?: () => void;
  onDismiss?: () => void;
}) {
  const qc = useQueryClient();
  const [startedAt] = useState(() => Date.now());
  const [expired, setExpired] = useState(false);
  const polling = active && !expired;
  const { data } = useGenerationStatus(projectId, polling);
  const status = data?.status ?? null;
  const running = !!status && !data?.is_terminal && status !== "FAILED" && status !== "REJECTED";
  const finished = useRef(false);

  useEffect(() => {
    if (!polling) return;
    const remaining = MAX_POLL_MS - (Date.now() - startedAt);
    const id = setTimeout(() => setExpired(true), Math.max(0, remaining));
    return () => clearTimeout(id);
  }, [polling, startedAt]);

  useEffect(() => {
    if (!data) return;
    if (running) {
      finished.current = false; // nouvelle génération suivie
      return;
    }
    if (finished.current) return;
    finished.current = true;
    void qc.invalidateQueries({ queryKey: [...AI_KEY, "proposals"] });
    onFinished?.();
  }, [data, running, qc, onFinished]);

  if (!active || !data || !status) return null;
  const failed = status === "FAILED";
  const done = DONE.has(status);

  return (
    <section aria-live="polite" className="rounded-[22px] border border-transparent bg-card shadow-card dark:border-border p-4">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 shrink-0">
          {running && !expired ? <Loader2 className="size-5 animate-spin text-brand" aria-hidden="true" />
            : failed || expired ? <TriangleAlert className="size-5 text-destructive" aria-hidden="true" />
              : <CheckCircle2 className="size-5 text-success" aria-hidden="true" />}
        </span>
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold">
              {expired && running ? "La génération prend plus de temps que prévu"
                : running ? "Génération PMO en cours" : failed ? "Échec de la génération" : "Génération terminée"}
            </p>
            <span className="text-xs tabular-nums text-muted-foreground">
              {data.progress} %{running && data.eta_seconds > 0 ? ` · reste ≈ ${data.eta_seconds} s` : ""}
            </span>
          </div>
          <p className="text-xs text-muted-foreground">
            {expired && running
              ? "Le suivi automatique est suspendu. Actualisez l'historique dans quelques instants ou relancez une génération."
              : data.step_label}
          </p>
          <ProgressBar value={failed ? 0 : data.progress} label="Progression de la génération" />
          {(done || (expired && data.proposal_id)) && data.proposal_id && (
            <Button size="sm" asChild><Link to={`/ai-proposals/${data.proposal_id}`}>Ouvrir la proposition</Link></Button>
          )}
        </div>
        {!running && onDismiss && (
          <Button variant="ghost" size="icon" aria-label="Masquer le suivi" onClick={onDismiss}><X /></Button>
        )}
      </div>
    </section>
  );
}
