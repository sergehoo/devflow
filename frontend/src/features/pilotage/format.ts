/** Correspondances d'affichage du suivi (statuts du classeur, alertes) → couleurs du thème. */
import { severityTone, type Tone } from "@/features/projet/format";
import type { StatusKey, TrackingAlert } from "./api";

export const STATUS_TONE: Record<StatusKey, Tone> = { en_cours: "info", suspendu: "warning", realise: "success", annule: "muted" };

export const alertTone = (a: Pick<TrackingAlert, "kind" | "severity">): Tone =>
  a.kind === "DECISION" ? "primary" : a.kind === "BLOCKER" ? "danger" : a.kind === "DEPENDENCY" ? "warning" : severityTone(a.severity ?? "");
