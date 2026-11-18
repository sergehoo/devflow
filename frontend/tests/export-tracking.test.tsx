import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ExportTrackingButton } from "@/features/pilotage/ExportTrackingButton";
import { ME, renderPage } from "./utils";

const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const P = (id: number, name: string, extra = {}) => ({
  id, name, code: "", workspace: { id: 1, name: "Alpha" }, status: "IN_PROGRESS", status_label: "En cours",
  start_date: "2024-01-08", target_date: "2026-12-31", progress: 40, is_activities: false, activity_count: 0, ...extra,
});
const PROJECTS = [P(1, "AFFLUX"), P(2, "Portail"), P(3, "Activités Pôle Développement", { is_activities: true, activity_count: 4 })];

let exportResponse: () => Response;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function mockFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes("auth/me/")) return json(ME);
    if (url.includes("tracking/export/projects/")) return json({ projects: PROJECTS, max: 500, scope: "tous les projets de Alpha" });
    if (url.includes("tracking/export/") && init?.method === "POST") return exportResponse();
    return json({ detail: `non mocké: ${url}` }, 404);
  });
}

const posted = (spy: ReturnType<typeof mockFetch>) => {
  const call = spy.mock.calls.find(([u, i]) => String(u).endsWith("/api/v1/tracking/export/") && i?.method === "POST");
  return call ? JSON.parse(String(call[1]!.body)) : null;
};

async function openDialog(preselect?: { count?: number; load: () => Promise<number[]> }) {
  renderPage(<ExportTrackingButton gated preselect={preselect} />);
  await userEvent.click(await screen.findByRole("button", { name: /Exporter le suivi Excel/ }));
  const dialog = await screen.findByRole("dialog", { name: "Exporter le suivi Excel" });
  await within(dialog).findByText("AFFLUX");
  return dialog;
}

beforeEach(() => {
  exportResponse = () => new Response(new Blob(["xlsx"]), {
    status: 200,
    headers: { "Content-Type": XLSX, "Content-Disposition": 'attachment; filename="Suivi_Pole_Developpement_2026-01-01_2026-03-31.xlsx"', "X-Export-Rows": "4" },
  });
  Object.assign(URL, { createObjectURL: vi.fn(() => "blob:export"), revokeObjectURL: vi.fn() });
});
afterEach(() => vi.restoreAllMocks());

describe("Export Excel configuré", () => {
  it("sends the checked projects, the period and the mode, then downloads the workbook", async () => {
    const spy = mockFetch();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const dialog = await openDialog();
    const download = within(dialog).getByRole("button", { name: /Télécharger l'Excel/ });
    expect(download).toBeDisabled(); // sélection vide

    // La recherche filtre l'affichage ; « Tout sélectionner » coche ce qui est affiché.
    await userEvent.type(within(dialog).getByLabelText("Rechercher un projet à exporter"), "portail");
    expect(within(dialog).queryByText("AFFLUX")).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Tout sélectionner (1)" }));
    await userEvent.clear(within(dialog).getByLabelText("Rechercher un projet à exporter"));
    await userEvent.click(within(dialog).getByRole("checkbox", { name: /Activités Pôle Développement/ }));
    expect(within(dialog).getByText(/projet\(s\) coché\(s\) sur 3/)).toHaveTextContent("2 projet(s) coché(s) sur 3");

    await userEvent.click(within(dialog).getByRole("radio", { name: "Trimestre" }));
    await userEvent.selectOptions(within(dialog).getByLabelText("Trimestre"), "1");
    await userEvent.selectOptions(within(dialog).getByLabelText("Année"), "2026");
    expect(within(dialog).getByText("Du 01 janv. 2026 au 31 mars 2026")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("radio", { name: /Activités de la période/ }));
    await userEvent.click(download);

    await waitFor(() => expect(posted(spy)).toEqual({
      projects: [2, 3], period: { kind: "quarter", year: 2026, quarter: 1 }, mode: "period",
    }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("offers the list filters as an optional preselection, distinct from what is displayed", async () => {
    mockFetch();
    const load = vi.fn(async () => [1, 99]);
    const dialog = await openDialog({ count: 2, load });
    expect(within(dialog).getByRole("checkbox", { name: /AFFLUX/ })).not.toBeChecked(); // rien de coché d'office
    await userEvent.click(within(dialog).getByRole("button", { name: "Reprendre les filtres de la liste (2)" }));
    await waitFor(() => expect(within(dialog).getByRole("checkbox", { name: /AFFLUX/ })).toBeChecked());
    expect(within(dialog).getByText(/1 hors export ignoré/)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText("Rechercher un projet à exporter"), "portail");
    expect(within(dialog).getByText(/dont 1 masqué\(s\) par la recherche/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Tout désélectionner" }));
    expect(within(dialog).getByText(/projet\(s\) coché\(s\) sur 3/)).toHaveTextContent("0 projet(s) coché(s) sur 3");
  });

  it("validates custom dates before calling the server", async () => {
    const spy = mockFetch();
    const dialog = await openDialog();
    await userEvent.click(within(dialog).getByRole("checkbox", { name: /AFFLUX/ }));
    await userEvent.click(within(dialog).getByRole("radio", { name: "Dates" }));
    fireEvent.change(within(dialog).getByLabelText("Début"), { target: { value: "2026-05-10" } });
    fireEvent.change(within(dialog).getByLabelText("Fin"), { target: { value: "2026-05-01" } });
    expect(within(dialog).getByText("La période se termine avant de commencer.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /Télécharger l'Excel/ })).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Fin"), { target: { value: "2026-05-31" } });
    expect(within(dialog).queryByText("La période se termine avant de commencer.")).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /Télécharger l'Excel/ })).toBeEnabled();
    expect(posted(spy)).toBeNull();
  });

  it("unchecks projects the server refuses and shows its message", async () => {
    mockFetch();
    exportResponse = () => json({ detail: "1 projet(s) coché(s) ne sont pas ou plus accessibles. Actualisez la sélection.", inaccessible: [2] }, 400);
    const dialog = await openDialog();
    await userEvent.click(within(dialog).getByRole("checkbox", { name: /AFFLUX/ }));
    await userEvent.click(within(dialog).getByRole("checkbox", { name: /Portail/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: /Télécharger l'Excel/ }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("ne sont pas ou plus accessibles");
    expect(within(dialog).getByRole("checkbox", { name: /Portail/ })).not.toBeChecked();
    expect(within(dialog).getByRole("checkbox", { name: /AFFLUX/ })).toBeChecked();
  });
});
