import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProjectDetailPage } from "@/features/projects/ProjectDetailPage";
import { ProjectFormPage } from "@/features/projects/ProjectFormPage";
import { ProjectsPage } from "@/features/projects/ProjectsPage";
import { ME, mockApi, renderPage } from "./utils";

const PROJECT = {
  id: 7, workspace: 1, team: 2, team_name: "Core", name: "Portail", code: "PRJ-7", description: "", tech_stack: "Django",
  owner: 1, owner_name: "Alice", product_manager: null, product_manager_name: "", status: "ACTIVE", status_label: "Actif",
  priority: "HIGH", priority_label: "Haute", health_status: "GREEN", health_status_label: "Vert", methodology: "AGILE",
  methodology_label: "Agile", progress_percent: 40, risk_score: 0, ai_risk_label: "", start_date: null, target_date: "2026-12-01",
  delivered_at: null, budget: null, members_count: 1, is_archived: false, updated_at: "",
};
const SCHEMA = {
  fields: [
    { name: "name", label: "Nom", type: "text", required: true, help_text: "", section: "Informations générales", value: "", max_length: 150, min: null, max: null },
    { name: "status", label: "Statut", type: "select", required: true, help_text: "", section: "Pilotage", value: "PLANNED", max_length: null, min: null, max: null,
      choices: [{ value: "PLANNED", label: "Planifié" }, { value: "ACTIVE", label: "Actif" }] },
    { name: "team", label: "Équipe", type: "select", required: false, help_text: "", section: "Informations générales", value: "", max_length: null, min: null, max: null,
      choices: [{ value: "", label: "---" }, { value: "2", label: "Core" }] },
  ],
};
const SUMMARY = { tasks_total: 3, tasks_overdue: 1, estimate_hours: 10, spent_hours: 4, tasks_by_status: [{ status: "TODO", label: "À faire", count: 3 }], members: [] };

afterEach(() => vi.restoreAllMocks());

describe("Projects", () => {
  it("lists projects with filters built from the Django form choices", async () => {
    mockApi({ "forms/project/": SCHEMA, "projects/": { count: 1, next: null, previous: null, results: [PROJECT] } });
    renderPage(<ProjectsPage />);
    expect(await screen.findByRole("link", { name: /Portail/ })).toHaveAttribute("href", "/projects/7");
    expect(await screen.findByRole("option", { name: "Core" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Planifié" })).toBeInTheDocument();
  });

  it("shows delete only with the project.delete permission", async () => {
    mockApi({ "auth/me/": { ...ME, permissions: ["project.view"] }, "projects/7/summary/": SUMMARY, "projects/7/": PROJECT });
    renderPage(<ProjectDetailPage />, "/projects/7", "/projects/:id");
    expect(await screen.findByRole("heading", { name: "Portail" })).toBeInTheDocument();
    expect(await screen.findByText("1 en retard")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Supprimer/ })).not.toBeInTheDocument();
  });

  it("validates required fields client-side then maps Django errors", async () => {
    const spy = mockApi({ "forms/project/": SCHEMA, "POST forms/project/": () => ({ id: 0 }) });
    spy.mockImplementation(async (input, init) => {
      const url = String(input);
      if ((init?.method ?? "GET") === "POST") {
        return new Response(JSON.stringify({ name: ["Un projet avec ce nom existe déjà."] }), { status: 400, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify(url.includes("forms/project/") ? SCHEMA : {}), { status: 200, headers: { "content-type": "application/json" } });
    });
    renderPage(<ProjectFormPage />, "/projects/new", "/projects/new");
    await userEvent.click(await screen.findByRole("button", { name: "Créer le projet" }));
    expect(await screen.findByText("Champ obligatoire.")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Nom *"), "Portail");
    await userEvent.click(screen.getByRole("button", { name: "Créer le projet" }));
    expect(await screen.findByText("Un projet avec ce nom existe déjà.")).toBeInTheDocument();
  });
});
