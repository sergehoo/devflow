import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResourceDetailPage, ResourceListPage } from "@/features/resources/ResourcePages";
import { TaskStructure } from "@/features/tasks/TaskStructure";
import type { TaskOverview } from "@/features/tasks/api";
import { ME, mockApi, renderPage } from "./utils";

const REGISTRY = { resources: [{ name: "risk", title: "Risques", singular: "Risque", group: "Projets", permission: "", superuser: false,
  legacy_list: "/risks/", can_create: true, has_detail: true, can_update: true, can_delete: true }] };
const LIST = {
  columns: [{ name: "project", label: "Projet" }, { name: "severity", label: "Gravité" }],
  results: [{ id: 3, label: "Fuite de données", link: "/m/risk/3", cells: {
    project: { kind: "ref", label: "Portail", link: "/projects/7" }, severity: { kind: "choice", value: "HIGH", label: "Élevé" } } }],
  count: 1, page: 1, num_pages: 1,
};
const DETAIL = {
  id: 3, label: "Fuite de données", legacy_url: "/risks/3/",
  fields: [{ name: "due_date", label: "Échéance", value: "2026-11-30" }, { name: "owner", label: "Responsable", value: null }],
  actions: [{ code: "archive", label: "Archiver" }], downloads: [{ label: "PDF", href: "/risks/3/pdf/" }],
};

afterEach(() => vi.restoreAllMocks());

describe("Modules génériques (pont ressources)", () => {
  it("affiche la liste servie par la ListView Django", async () => {
    mockApi({ "auth/me/": ME, "resources/risk/": LIST, "resources/": REGISTRY });
    renderPage(<ResourceListPage />, "/m/risk", "/m/:resource");
    expect(await screen.findByRole("heading", { name: "Risques" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Fuite de données" })).toHaveAttribute("href", "/m/risk/3");
    expect(screen.getByRole("link", { name: "Portail" })).toHaveAttribute("href", "/projects/7");
    expect(screen.getByText("Élevé")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ajouter/ })).toHaveAttribute("href", "/m/risk/new");
  });

  it("exécute une action métier de la fiche après confirmation", async () => {
    const spy = mockApi({ "auth/me/": ME, "POST resources/risk/3/actions/archive/": { messages: ["Risque archivé avec succès."] },
      "resources/risk/3/": DETAIL, "resources/": REGISTRY });
    renderPage(<ResourceDetailPage />, "/m/risk/3", "/m/:resource/:id");
    expect(await screen.findByText("30 nov. 2026")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /PDF/ })).toHaveAttribute("href", expect.stringContaining("/risks/3/pdf/"));
    await userEvent.click(screen.getByRole("button", { name: "Archiver" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Archiver" }));
    await vi.waitFor(() => expect(spy.mock.calls.some(([u, i]) => String(u).includes("resources/risk/3/actions/archive/") && i?.method === "POST")).toBe(true));
  });
});

const OVERVIEW = {
  can_edit: true,
  checklists: [{ id: 2, title: "Recette", items: [{ id: 9, text: "Tester le login", is_checked: false }] }],
  dependencies: [{ id: 5, direction: "out", type: "Bloque", task_id: 8, title: "Déploiement" },
    { id: 6, direction: "in", type: "Bloque", task_id: 4, title: "Maquettes" }],
  labels: [{ id: 4, name: "Urgent", color: "#f00" }],
} as unknown as TaskOverview;

describe("Structure de tâche", () => {
  it("coche un élément via le formulaire Django et retire un label", async () => {
    const spy = mockApi({
      "auth/me/": ME,
      "POST forms/checklist-item/9/": { id: 9, messages: [] },
      "forms/checklist-item/9/": { fields: [
        { name: "checklist", type: "select", value: 2 }, { name: "text", type: "text", value: "Tester le login" },
        { name: "is_checked", type: "checkbox", value: false }, { name: "checked_by", type: "select", value: null, disabled: true }] },
      "POST resources/task-label/4/delete/": { messages: [] },
    });
    renderPage(<TaskStructure taskId={1} o={OVERVIEW} />);
    expect(screen.getByText(/Cette tâche/)).toHaveTextContent("Cette tâche bloque Déploiement");
    expect(screen.getByRole("link", { name: "Maquettes" })).toHaveAttribute("href", "/tasks/4");
    await userEvent.click(screen.getByRole("checkbox", { name: "Tester le login" }));
    await vi.waitFor(() => {
      const post = spy.mock.calls.find(([u, i]) => String(u).includes("forms/checklist-item/9/") && i?.method === "POST");
      expect(post).toBeTruthy();
      const body = post![1]!.body as FormData;
      expect(body.get("is_checked")).toBe("on");
      expect(body.has("checked_by")).toBe(false); // champ verrouillé non renvoyé
    });
    await userEvent.click(screen.getByRole("button", { name: "Retirer le label Urgent" }));
    await vi.waitFor(() => expect(spy.mock.calls.some(([u]) => String(u).includes("resources/task-label/4/delete/"))).toBe(true));
  });
});
