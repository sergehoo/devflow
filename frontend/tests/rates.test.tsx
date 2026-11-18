import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RatesPage } from "@/features/finance/RatesPage";
import type { RatesBoard } from "@/features/finance/rates";
import { ME, mockApi, renderPage } from "./utils";

const RATE = {
  id: 5, worker_level: "SENIOR", worker_level_label: "Senior", unit: "DAILY", unit_label: "Journalier",
  cost_rate_amount: "75000.00", sale_rate_amount: "175000.00", daily_cost: "75000.00", daily_sale: "175000.00",
  margin_percent: 133.3, currency: "XOF", valid_from: "2026-01-01", valid_to: null, project: null, status: "current" as const,
};
const BOARD: RatesBoard = {
  workspace: { id: 1, name: "Alpha" }, today: "2026-11-15", hours_window: 30, currency: "XOF", can_manage: true,
  levels: [{ value: "SENIOR", label: "Senior" }, { value: "MID", label: "Intermédiaire" }, { value: "OTHER", label: "Autre" }],
  units: [{ value: "DAILY", label: "Journalier" }, { value: "HOURLY", label: "Horaire" }],
  projects: [{ id: 7, name: "ANALYTICS HUB" }],
  summary: { members: 2, with_rate: 1, without_rate: 1, unvalued_entries: 3 },
  members: [
    { user_id: 9, name: "Loïc Demanou", job_title: "Senior Developper", team: "Backend", home: true, current: RATE, rates: [RATE],
      profile_cost_per_day: null, hours_30d: 37, unvalued_entries: 0 },
    { user_id: 13, name: "Innocent Azo", job_title: "", team: "", home: true, current: null, rates: [],
      profile_cost_per_day: null, hours_30d: 12, unvalued_entries: 3 },
  ],
};

const body = (init?: RequestInit) => JSON.parse(String(init?.body ?? "{}"));

afterEach(() => vi.restoreAllMocks());

describe("TJM des collaborateurs", () => {
  it("liste les TJM en vigueur et signale les collaborateurs sans TJM", async () => {
    mockApi({ "auth/me/": ME, "finance/rates/": BOARD });
    renderPage(<RatesPage />);
    const row = (await screen.findByText("Loïc Demanou")).closest("tr")!;
    expect(within(row).getByText("Senior")).toBeInTheDocument();
    expect(within(row).getByText(/^75\s000/)).toBeInTheDocument();
    expect(within(row).getByText("133,3 %")).toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: /Afficher l'historique des tarifs de Loïc Demanou/ }));
    const history = screen.getByRole("list", { name: "Tarifs de Loïc Demanou" });
    expect(within(history).getByText(/^Coût 75\s000 XOF \/ jour$/)).toBeInTheDocument();
    expect(within(history).getByText(/^Vente 175\s000 XOF \/ jour$/)).toBeInTheDocument();
    const missing = screen.getByText("Innocent Azo").closest("tr")!;
    expect(within(missing).getByText(/Aucun TJM : heures valorisées à 0/)).toBeInTheDocument();
    expect(within(missing).getByText("3 à 0")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Sans TJM uniquement"));
    expect(screen.queryByText("Loïc Demanou")).not.toBeInTheDocument();
  });

  it("définit un premier TJM depuis le début de l'année et revalorise les heures déjà saisies", async () => {
    const spy = mockApi({ "auth/me/": ME, "POST finance/rates/": { id: 6, revalued: { entries: 3, before: "0", after: "93750" } }, "finance/rates/": BOARD });
    renderPage(<RatesPage />);
    const missing = (await screen.findByText("Innocent Azo")).closest("tr")!;
    await userEvent.click(within(missing).getByRole("button", { name: "Définir le TJM pour Innocent Azo" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Coût interne/), "50000");
    await userEvent.type(within(dialog).getByLabelText(/Tarif de vente/), "120000");
    expect(within(dialog).getByLabelText(/À partir du/)).toHaveValue("2026-01-01");
    expect(within(dialog).getByRole("checkbox", { name: /Revaloriser les heures déjà saisies/ })).toBeChecked();
    await userEvent.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
    await waitFor(() => expect(spy.mock.calls.some(([, i]) => i?.method === "POST")).toBe(true));
    const [url, init] = spy.mock.calls.find(([, i]) => i?.method === "POST")!;
    expect(String(url)).toContain("workspace=1");
    expect(body(init)).toEqual({ user: 13, worker_level: "OTHER", unit: "DAILY", currency: "XOF", cost_rate_amount: "50000",
      sale_rate_amount: "120000", valid_from: "2026-01-01", valid_to: null, project: null, revalue: true });
  });

  it("affiche l'erreur renvoyée par Django sous le champ concerné", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method === "POST") {
        return new Response(JSON.stringify({ sale_rate_amount: ["Le tarif de vente ne peut pas être inférieur au coût interne."] }),
          { status: 400, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify(url.includes("auth/me/") ? ME : BOARD), { status: 200, headers: { "content-type": "application/json" } });
    });
    renderPage(<RatesPage />);
    const row = (await screen.findByText("Loïc Demanou")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: /Nouveau tarif/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/À partir du/)).toHaveValue("2026-11-15");
    await userEvent.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
    expect(await within(dialog).findByText("Le tarif de vente ne peut pas être inférieur au coût interne.")).toBeInTheDocument();
  });

  it("collaborateur rattaché à un autre espace : tarifs propres aux projets d'ici uniquement", async () => {
    const shared = { user_id: 21, name: "Free Lance", job_title: "", team: "", home: false, current: null, rates: [],
      profile_cost_per_day: null, hours_30d: 4, unvalued_entries: 0 };
    mockApi({ "auth/me/": ME, "finance/rates/": { ...BOARD, members: [shared] } });
    renderPage(<RatesPage />);
    const row = (await screen.findByText("Free Lance")).closest("tr")!;
    expect(within(row).getByText(/TJM général géré par son espace principal/)).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: /Tarif projet/ }));
    const dialog = await screen.findByRole("dialog");
    const scope = within(dialog).getByLabelText(/S'applique à/);
    expect(scope).toHaveValue("7");
    expect(within(scope).queryByRole("option", { name: /Tous les projets/ })).not.toBeInTheDocument();
  });

  it("consultation seule sans le droit de gérer les tarifs", async () => {
    mockApi({ "auth/me/": { ...ME, permissions: ["billing.view"] }, "finance/rates/": { ...BOARD, can_manage: false } });
    renderPage(<RatesPage />);
    await screen.findByText("Loïc Demanou");
    expect(screen.queryByRole("button", { name: /Définir le TJM|Nouveau tarif/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Consultation seule/)).toBeInTheDocument();
  });
});
