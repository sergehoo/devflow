import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "@/services/api";

/** Tarif (période) d'un collaborateur, montants ramenés à la journée côté Django. */
export interface Rate {
  id: number;
  worker_level: string; worker_level_label: string;
  unit: string; unit_label: string;
  cost_rate_amount: string; sale_rate_amount: string;
  daily_cost: string; daily_sale: string; margin_percent: number | null;
  currency: string;
  valid_from: string; valid_to: string | null;
  project: { id: number; name: string } | null;
  status: "current" | "past" | "future";
}

export interface RateMember {
  user_id: number; name: string; job_title: string; team: string;
  /** Espace principal du collaborateur : seul à gérer son TJM général (sinon tarifs par projet). */
  home: boolean;
  current: Rate | null; rates: Rate[];
  profile_cost_per_day: string | null;
  hours_30d: number; unvalued_entries: number;
}

export interface RatesBoard {
  workspace: { id: number; name: string };
  today: string; hours_window: number; currency: string; can_manage: boolean;
  levels: { value: string; label: string }[];
  units: { value: string; label: string }[];
  projects: { id: number; name: string }[];
  summary: { members: number; with_rate: number; without_rate: number; unvalued_entries: number };
  members: RateMember[];
}

export interface RatePayload {
  user?: number; worker_level: string; unit: string; currency: string;
  cost_rate_amount: string; sale_rate_amount: string;
  valid_from: string; valid_to: string | null; project: number | null; revalue: boolean;
}

export interface RateResult { id?: number; archived?: number; revalued: { entries: number; before: string; after: string } | null }

const KEY = ["finance", "rates"] as const;

/** Coût réel, budgets, cockpit financier, allocation et tableaux de bord dépendent des TJM. */
const invalidateCostViews = (qc: QueryClient) => Promise.all([
  qc.invalidateQueries({ queryKey: ["finance"] }),
  qc.invalidateQueries({ queryKey: ["projet"] }),
  qc.invalidateQueries({ queryKey: ["projects"] }),
  qc.invalidateQueries({ queryKey: ["dashboard"] }),
]);

export const useRates = (workspace?: number) =>
  useQuery({
    queryKey: [...KEY, workspace],
    queryFn: ({ signal }) => api<RatesBoard>("finance/rates/", { signal, params: { workspace } }),
    enabled: workspace != null,
  });

/** Nouvelle période (sans ``id``) ou correction d'un tarif existant. */
export function useSaveRate(workspace?: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id?: number; body: RatePayload }) =>
      api<RateResult>(id ? `finance/rates/${id}/` : "finance/rates/", { method: id ? "PATCH" : "POST", body, params: { workspace } }),
    onSuccess: () => void invalidateCostViews(qc),
  });
}

export function useArchiveRate(workspace?: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, revalue }: { id: number; revalue: boolean }) =>
      api<RateResult>(`finance/rates/${id}/`, { method: "DELETE", params: { workspace, revalue: revalue ? "1" : undefined } }),
    onSuccess: () => void invalidateCostViews(qc),
  });
}
