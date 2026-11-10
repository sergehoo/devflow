import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProjectDetailPage } from "@/features/projects/ProjectDetailPage";
import { ProjectFormPage } from "@/features/projects/ProjectFormPage";
import { resolveLegacyLink } from "@/lib/links";
import { ME, mockApi, renderPage } from "./utils";

const HEADER = {
  id: 7, name: "Portail", code: "PRJ-7", category: "Web", status: "ACTIVE", status_label: "Actif", priority: "HIGH",
  priority_label: "Haute", health_status: "GREEN", health_status_label: "Vert", methodology: "SCRUM", methodology_label: "Scrum",
  progress_percent: 40, risk_score: 12, ai_risk_label: "", description_html: "<p>Refonte du <strong>portail</strong></p>",
  owner: "Alice", product_manager: "", workspace: "Alpha", workspace_id: 1, start_date: "2026-09-01", target_date: "2026-12-01",
  delivered_at: null, team: "Core", team_id: 3, tech_stack: "Django / React", labels: [{ id: 1, name: "Prioritaire", color: "#ff0000" }], budget_id: null, budget_status_label: "",
};
const PLANNING = { key: "planification", label: "Planification", count: 2 };
const OTHER_TABS = [
  { key: "equipes", label: "Équipes", count: 1 },
  { key: "evolution", label: "Évolution", count: 0 }, { key: "taches", label: "Tâches", count: 1 },
  { key: "kpi_roi", label: "KPI & ROI", count: 0 }, { key: "documents", label: "Documents", count: 1 },
  { key: "meetings", label: "Réunions", count: 1 },
];
const BASE_TABS = [PLANNING, ...OTHER_TABS];
const FIN_TABS = [PLANNING, { key: "budget_estimatif", label: "Budget estimatif", count: 0 },
  { key: "budget_previsionnel", label: "Budget prévisionnel", count: 0 }, { key: "facturation_client", label: "Facturation client", count: 0 },
  { key: "depenses", label: "Dépenses", count: 1 }, ...OTHER_TABS];
const DEPS = { count: 0, blocking: 0, related: 0, items: [] };

const TABS: Record<string, object> = {
  planification: {
    key: "planification",
    stats: { milestones_count: 1, releases_count: 0, sprints_count: 1, backlog_count: 0, roadmap_items_count: 0, planning_items_count: 2 },
    milestones: [{ id: 3, name: "Go-live", due_date: "2026-12-01", owner: "Alice", status: "PLANNED", status_label: "Planifié", progress_percent: 20 }],
    sprints: [{ id: 4, name: "Sprint 1", start_date: "2026-11-02", end_date: "2026-11-13", status: "ACTIVE", status_label: "Actif", tasks_count: 3, backlog_count: 1, metrics_count: 0 }],
    releases: [], roadmap_items: [], backlog: [], dependencies: DEPS, ai_alerts: [],
  },
  taches: {
    key: "taches",
    stats: { total: 1, todo: 1, in_progress: 0, review: 0, done: 0, blocked: 0, cancelled: 0, overdue: 0, flagged: 0, total_estimate_hours: "8.00", total_spent_hours: "2.00" },
    has_board: false, board: [], dependencies: DEPS,
    tasks: [{ id: 12, title: "Maquettes", backlog_item: "", parent: "", parent_id: null, status: "TODO", status_label: "À faire", priority: "HIGH",
      priority_label: "Haute", assignee: "Bob", assignee_id: 2, estimate_hours: "8.00", spent_hours: "2.00", due_date: null }],
  },
  meetings: {
    key: "meetings", count: 1,
    meetings: [{ id: 5, title: "Comité de pilotage", scheduled_at: "2026-11-10T09:00:00Z", meeting_type_label: "Comité", status: "PLANNED",
      status_label: "Planifiée", status_color: "cyan", action_items_count: 2 }],
  },
  documents: {
    key: "documents", summary: { count: 2, completed: 1, processing: 0, failed: 0 },
    documents: [
      { id: 8, name: "cahier.pdf", url: "/media/devflow/project_imports/cahier.pdf", ext: "pdf", type_label: "PDF", has_text: true, status: "COMPLETED", status_label: "Terminé", uploaded_by: "Alice", created_at: "2026-11-01T10:00:00Z", error_message: "" },
      { id: 9, name: "notes.html", url: "/media/devflow/project_imports/notes.html", ext: "html", type_label: "HTML", has_text: false, status: "UPLOADED", status_label: "Uploadé", uploaded_by: "Alice", created_at: "2026-11-01T10:00:00Z", error_message: "" },
    ],
  },
  equipes: {
    key: "equipes", can_manage_members: false, member_costs_restricted: false, member_costs: null,
    members: [{ id: 41, user_id: 2, name: "Bob", team: "Core", role: "Développeur", allocation_percent: 50, is_primary: true }],
    team_summary: [{ team_id: 3, team: "Core", members_count: 1, primary_count: 1 }], primary_total: 1, allocation_average: 50,
    timesheet_stats: { total_entries: 0, total_hours: "0", approved_hours: "0", submitted_hours: "0" },
  },
  depenses: {
    key: "depenses", currency: "XOF",
    stats: { total_expenses: "1500.00", estimated_expenses: "0", forecast_expenses: "0", committed_expenses: "0", accrued_expenses: "0", paid_expenses: "0",
      rejected_expenses: "0", labor_cost: "0", direct_cost: "0", other_cost: "1500.00", validated_expenses: "0", draft_expenses: "1500.00" },
    expenses: [{ id: 21, expense_date: "2026-11-03", created_at: null, title: "Licence", description: "", reference: "F-1", is_direct_cost: false, is_labor_cost: false,
      status: "DRAFT", status_label: "Brouillon", approval_state: "PENDING", approval_state_label: "En attente", amount: "1500.00", currency: "XOF", can_be_edited: true }],
  },
  facturation_client: {
    key: "facturation_client", currency: "XOF", invoices: [], invoices_total: 0, revenues: [], can_generate_invoice: true,
    invoice_summary: { total_ttc: "0", total_paid: "0", total_due: "0", count_total: 0, count_overdue: 0, count_draft: 0, count_paid: 0 },
    billing: { planned_revenue: "0", invoiced_revenue: "0", received_revenue: "0", remaining_to_invoice: "0", remaining_to_collect: "0", collection_rate_percent: 0, invoicing_rate_percent: 0 },
  },
};

type Overrides = { tabs?: Record<string, object>; project?: Partial<typeof HEADER> };

function detail(url: string, financial: boolean, overrides: Overrides = {}) {
  const requested = new URL(url, "http://x").searchParams.get("tab") ?? "planification";
  const tabs = financial ? FIN_TABS : BASE_TABS;
  const data = { ...TABS, ...overrides.tabs };
  const key = tabs.some((t) => t.key === requested) && data[requested] ? requested : "planification";
  return {
    project: { ...HEADER, ...overrides.project }, can_view_financials: financial,
    kpis: { progress_percent: 40, risk_score: 12, tasks_total: 1, members_count: 1, actual_cost: financial ? "1500.00" : null, received_revenue: financial ? "0" : null, currency: "XOF" },
    band: { todo: 1, in_progress: 0, blocked: 0, overdue: 0, imports: 2, imports_completed: 1, insights_total: 0, insights_critical: 0,
      approved_budget: financial ? "50000.00" : null, actual_cost: financial ? "1500.00" : null, forecast_margin: financial ? "0" : null },
    mode: null, tabs, active_tab: key, tab: data[key],
  };
}

const IDLE = { status: null, label: "Aucune proposition", progress: 0, eta_seconds: 0, step_label: "—" };

function mockDetail({ financial = false, permissions = ["project.view"], extra = {}, ...overrides }: {
  financial?: boolean; permissions?: string[]; extra?: Record<string, unknown>;
} & Overrides = {}) {
  return mockApi({
    "auth/me/": { ...ME, permissions },
    "detail-tabs/ai-generation/": IDLE,
    ...extra,
    "projects/7/detail-tabs/": (_init: RequestInit | undefined, url: string) => detail(url, financial, overrides),
  });
}

const called = (spy: ReturnType<typeof mockApi>, fragment: string, method = "GET") =>
  spy.mock.calls.some(([u, i]) => String(u).includes(fragment) && (i?.method ?? "GET").toUpperCase() === method);

afterEach(() => vi.restoreAllMocks());

describe("Fiche projet complète", () => {
  it("affiche l'en-tête, les indicateurs et masque la finance sans droit financier", async () => {
    mockDetail();
    renderPage(<ProjectDetailPage />, "/projects/7", "/projects/:id");
    expect(await screen.findByRole("heading", { name: "Portail" })).toBeInTheDocument();
    expect(screen.getByText("portail", { selector: "strong" })).toBeInTheDocument(); // description HTML (nettoyée par Django)
    expect(screen.getByText("Prioritaire")).toBeInTheDocument();
    expect(screen.getAllByText("Accès restreint").length).toBe(2);
    expect(screen.queryByRole("tab", { name: /Dépenses/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Export Excel/ })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Planification/ })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("link", { name: "Go-live" })).toHaveAttribute("href", "/m/milestone/3");
    expect(screen.getAllByRole("link", { name: /Copilote IA/ })[0]).toHaveAttribute("href", "/projects/7/copilot");
    expect(screen.getByRole("link", { name: /Propositions IA/ })).toHaveAttribute("href", "/projects/7/ai-proposals");
    await userEvent.click(screen.getByRole("button", { name: /Actions/ }));
    expect(await screen.findByRole("menuitem", { name: /Archiver/ })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /Supprimer le projet/ })).not.toBeInTheDocument();
  });

  it("change d'onglet (URL ?tab=) et charge les tâches avec réaffectation / mise à jour rapide", async () => {
    const spy = mockDetail();
    renderPage(<ProjectDetailPage />, "/projects/7", "/projects/:id");
    await userEvent.click(await screen.findByRole("tab", { name: /Tâches/ }));
    expect(await screen.findByRole("link", { name: "Maquettes" })).toHaveAttribute("href", "/tasks/12");
    expect(screen.getByRole("tab", { name: /Tâches/ })).toHaveAttribute("aria-selected", "true");
    expect(spy.mock.calls.some(([u]) => String(u).includes("detail-tabs/?tab=taches"))).toBe(true);
    expect(screen.getByRole("button", { name: /Réaffecter « Maquettes »/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Voir le board/ })).toHaveAttribute("href", "/tasks?project=7&view=board");
  });

  it("onglet Réunions : liens vers le module Réunions", async () => {
    mockDetail();
    renderPage(<ProjectDetailPage />, "/projects/7?tab=meetings", "/projects/:id");
    expect(await screen.findByRole("link", { name: "Comité de pilotage" })).toHaveAttribute("href", "/meetings/5");
    expect(screen.getByRole("link", { name: /Nouvelle réunion/ })).toHaveAttribute("href", "/meetings?project=7");
    expect(screen.getByText("· 2 action(s)")).toBeInTheDocument();
  });

  it("onglet Documents : visionneuse intégrée, HTML isolé dans une iframe sandbox", async () => {
    mockDetail();
    renderPage(<ProjectDetailPage />, "/projects/7?tab=documents", "/projects/:id");
    await userEvent.click(await screen.findByRole("button", { name: "Lire cahier.pdf" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByTitle("cahier.pdf")).toHaveAttribute("src", "/media/devflow/project_imports/cahier.pdf");
    await userEvent.click(within(dialog).getByRole("button", { name: "Fermer" }));
    await userEvent.click(screen.getByRole("button", { name: "Lire notes.html" }));
    expect(within(await screen.findByRole("dialog")).getByTitle("notes.html")).toHaveAttribute("sandbox", "allow-same-origin"); // jamais allow-scripts
  });

  it("onglets financiers servis par Django : dépenses modifiables et export Excel", async () => {
    mockDetail({ financial: true, permissions: ["*"] });
    renderPage(<ProjectDetailPage />, "/projects/7?tab=depenses", "/projects/:id");
    expect(await screen.findByText("Licence")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Dépenses/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "Modifier la dépense Licence" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Voir la dépense Licence" })).toHaveAttribute("href", "/m/project-expense/21");
    expect(screen.getAllByRole("link", { name: /Export Excel/ })[0]).toHaveAttribute("href", expect.stringContaining("/projects/7/budget/export-excel/"));
  });

  it("onglet demandé sans droit : l'onglet retenu par Django est affiché", async () => {
    mockDetail();
    renderPage(<ProjectDetailPage />, "/projects/7?tab=depenses", "/projects/:id");
    expect(await screen.findByRole("link", { name: "Go-live" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Planification/ })).toHaveAttribute("aria-selected", "true");
  });

  it("génère une facture via le formulaire Django dédié", async () => {
    const schema = { fields: [{ name: "mode", label: "Mode", type: "select", required: true, help_text: "", section: null, value: "FIXED",
      max_length: null, min: null, max: null, choices: [{ value: "FIXED", label: "Forfait" }] }] };
    const spy = mockDetail({ financial: true, permissions: ["*"], extra: {
      "POST detail-tabs/invoice-generate/": { id: 31, link: "/m/invoice/31", messages: ["Brouillon de facture généré (2 lignes)."] },
      "detail-tabs/invoice-generate/": schema,
    } });
    const router = createMemoryRouter([
      { path: "/projects/:id", element: <ProjectDetailPage /> },
      { path: "/m/invoice/:id", element: <p>Fiche facture 31</p> },
    ], { initialEntries: ["/projects/7?tab=facturation_client"] });
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><RouterProvider router={router} /></QueryClientProvider>);
    await userEvent.click((await screen.findAllByRole("button", { name: /Générer une facture/ }))[0]!);
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByLabelText("Mode *")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Générer le brouillon" }));
    expect(await screen.findByText("Fiche facture 31")).toBeInTheDocument();
    expect(spy.mock.calls.some(([u, i]) => String(u).includes("projects/7/detail-tabs/invoice-generate/") && i?.method === "POST")).toBe(true);
  });

  it("lance la génération IA (sprints, jalons, tâches) et affiche la progression", async () => {
    let running = false;
    const spy = mockDetail({ extra: {
      "POST detail-tabs/ai-generation/": () => { running = true; return { success: true, proposal_id: 3, status: "PENDING" }; },
      "detail-tabs/ai-generation/": () => (running
        ? { proposal_id: 3, status: "PENDING", status_label: "En attente", progress: 15, step_label: "Lecture du contexte projet et des équipes", eta_seconds: 70, is_terminal: false }
        : IDLE),
    } });
    renderPage(<ProjectDetailPage />, "/projects/7", "/projects/:id");
    await userEvent.click(await screen.findByRole("button", { name: /Générer suggestions IA/ }));
    expect(await screen.findByText("Génération PMO en cours")).toBeInTheDocument();
    expect(screen.getByText("Lecture du contexte projet et des équipes")).toBeInTheDocument();
    expect(spy.mock.calls.some(([u, i]) => String(u).includes("projects/7/detail-tabs/ai-generation/") && i?.method === "POST")).toBe(true);
  });

  it("affiche l'issue de la génération même si le worker crée une proposition plus récente", async () => {
    let triggered = false;
    mockDetail({ extra: {
      "POST detail-tabs/ai-generation/": () => { triggered = true; return { success: true, proposal_id: 2, status: "PENDING" }; },
      "detail-tabs/ai-generation/": () => (triggered
        ? { proposal_id: 3, status: "READY", status_label: "Prête à validation", progress: 100, step_label: "Génération terminée", eta_seconds: 0, is_terminal: true }
        : { proposal_id: 1, status: "READY", progress: 100, step_label: "Génération terminée", eta_seconds: 0, is_terminal: true }),
    } });
    renderPage(<ProjectDetailPage />, "/projects/7", "/projects/:id");
    await screen.findByRole("heading", { name: "Portail" });
    expect(screen.queryByText("Génération terminée", { selector: "p.text-sm" })).not.toBeInTheDocument(); // ancienne proposition : pas de bandeau
    await userEvent.click(screen.getByRole("button", { name: /Générer suggestions IA/ }));
    expect(await screen.findByText("Génération terminée", { selector: "p.text-sm" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "voir la proposition" })).toHaveAttribute("href", "/projects/7/ai-proposals");
  });
});

describe("Fiche projet : droits et workspace du projet", () => {
  it("en-tête : dates, équipe et stack technique ; modification dans le workspace du projet", async () => {
    mockDetail();
    renderPage(<ProjectDetailPage />, "/projects/7", "/projects/:id");
    expect(await screen.findByText("Django / React")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Core" })).toHaveAttribute("href", "/teams/3");
    await userEvent.click(screen.getByRole("button", { name: /Actions/ }));
    expect(await screen.findByRole("menuitem", { name: /Modifier le projet/ })).toHaveAttribute("href", "/projects/7/edit?workspace=1");
  });

  it("onglet Équipes sans droit de gestion : ni ajout, ni modification, ni retrait ; TJM restreints", async () => {
    mockDetail({ financial: true, tabs: { equipes: { ...TABS.equipes, member_costs_restricted: true } } });
    renderPage(<ProjectDetailPage />, "/projects/7?tab=equipes", "/projects/:id");
    expect(await screen.findByRole("table", { name: "Membres du projet" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Ajouter un membre/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retirer Bob du projet" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Modifier l'affectation de Bob" })).not.toBeInTheDocument();
    expect(screen.getByText(/réservés aux rôles habilités à consulter la facturation/)).toBeInTheDocument();
    expect(screen.queryByText("TJM coût")).not.toBeInTheDocument();
  });

  it("onglet Équipes avec droit de gestion : le retrait cible le workspace du projet", async () => {
    const spy = mockDetail({
      tabs: { equipes: { ...TABS.equipes, can_manage_members: true } },
      extra: { "POST resources/project-member/41/delete/": { messages: ["Membre projet supprimé avec succès."] } },
    });
    renderPage(<ProjectDetailPage />, "/projects/7?tab=equipes", "/projects/:id");
    await userEvent.click(await screen.findByRole("button", { name: "Retirer Bob du projet" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Retirer" }));
    await waitFor(() => expect(called(spy, "resources/project-member/41/delete/?workspace=1", "POST")).toBe(true));
    expect(screen.getByRole("link", { name: /Modifier les affectations/ })).toHaveAttribute("href", "/projects/7/edit?workspace=1");
  });

  it("formulaire en dialogue : workspace du projet transmis et champ workspace masqué", async () => {
    const field = (name: string, label: string, type: string, value: unknown) =>
      ({ name, label, type, value, required: name === "name", help_text: "", section: null, disabled: false, max_length: null, min: null, max: null, choices: [] });
    const spy = mockDetail({ extra: { "forms/sprint/": { fields: [field("workspace", "Workspace", "select", 1), field("project", "Projet", "select", 7), field("name", "Nom", "text", "")] } } });
    renderPage(<ProjectDetailPage />, "/projects/7", "/projects/:id");
    await userEvent.click(await screen.findByRole("button", { name: /Actions/ }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /Nouveau sprint/ }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByLabelText("Nom *")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/Workspace/)).not.toBeInTheDocument();
    expect(called(spy, "forms/sprint/?project=7&workspace=1")).toBe(true);
  });

  it("facturation sans invoice.create : pas de génération de facture", async () => {
    mockDetail({ financial: true, tabs: { facturation_client: { ...TABS.facturation_client, can_generate_invoice: false } } });
    renderPage(<ProjectDetailPage />, "/projects/7?tab=facturation_client", "/projects/:id");
    expect(await screen.findByText("Aucune facture émise pour ce projet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Générer une facture|Générer maintenant/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Facture manuelle/ })).not.toBeInTheDocument();
  });

  it("modification du projet : ?workspace= transmis au formulaire Django", async () => {
    const spy = mockApi({ "forms/project/7/": { fields: [] } });
    renderPage(<ProjectFormPage />, "/projects/7/edit?workspace=2", "/projects/:id/edit");
    await screen.findByRole("heading", { name: "Modifier le projet" });
    await waitFor(() => expect(called(spy, "forms/project/7/?workspace=2")).toBe(true));
  });
});

const SPACE = {
  kind: "scrum", methodology: { name: "Scrum", code: "scrum" }, dashboard: [],
  kpis: {
    velocity: { value: 13, label: "Vélocité moyenne (1 sprints)", unit: "story_points", series: [{ x: "S1", y: 8 }, { x: "S2", y: 13 }], extra: {} },
    burndown_sprint: { value: 8, label: "Burndown — Sprint 1", unit: "story_points", series: [], extra: { total: 21, remaining: 8 } },
  },
  active_sprint: { id: 4, name: "Portail · Sprint 1", status_label: "Actif", start_date: "2026-11-02", end_date: "2026-11-13", goal: "MVP",
    tasks: [{ id: 12, title: "Maquettes", status: "IN_PROGRESS", status_label: "En cours", priority_label: "Haute", assignee: "Bob" }] },
  backlog: [{ id: 6, title: "Connexion", status_label: "User story", story_points: 5, rank: 1 }],
  sprints: [{ id: 4, name: "Portail · Sprint 1", status_label: "Actif", total_story_points: 21, completed_story_points: 13, velocity_completed: 13 }],
};

describe("Fiche projet : méthodologie et board", () => {
  it("ouvre l'espace Scrum intégré (sprint actif, backlog, historique) puis le tableau de bord", async () => {
    const spy = mockDetail({ extra: { "projects/7/space/": SPACE } });
    renderPage(<ProjectDetailPage />, "/projects/7", "/projects/:id");
    await userEvent.click(await screen.findByRole("button", { name: /Espace Scrum/ }));
    expect(await screen.findByText("Sprint actif · Portail · Sprint 1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Maquettes" })).toHaveAttribute("href", "/tasks/12");
    expect(screen.getByRole("link", { name: "Connexion" })).toHaveAttribute("href", "/m/backlog-item/6");
    expect(screen.getByRole("table", { name: "Sprints récents" })).toHaveTextContent("21");
    expect(screen.getByRole("button", { name: /Espace Scrum/ })).toHaveAttribute("aria-expanded", "true");
    expect(called(spy, "projects/7/space/")).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: /Tableau de bord/ }));
    expect(await screen.findByText("Tableau de bord · Scrum")).toBeInTheDocument();
    expect(screen.getAllByText("Vélocité moyenne (1 sprints)").length).toBeGreaterThan(0); // carte + histogramme
    expect(screen.getByRole("img", { name: /Vélocité moyenne \(1 sprints\) : S1 8, S2 13/ })).toBeInTheDocument();
  });

  it("lien ?space=workspace : espace ouvert directement", async () => {
    mockDetail({ extra: { "projects/7/space/": SPACE } });
    renderPage(<ProjectDetailPage />, "/projects/7?space=workspace", "/projects/:id");
    expect(await screen.findByText("Sprint actif · Portail · Sprint 1")).toBeInTheDocument();
  });

  it("onglet Tâches : board Kanban du projet quand des colonnes existent", async () => {
    const board = [{ id: 1, name: "En cours", mapped_status: "TODO", color: "", wip_limit: 1, is_done_column: false, count: 1, over_wip: false, task_ids: [12] }];
    mockDetail({ tabs: { taches: { ...TABS.taches, has_board: true, board } } });
    renderPage(<ProjectDetailPage />, "/projects/7?tab=taches", "/projects/:id");
    expect(await screen.findByText("Board Kanban")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Maquettes" })).toHaveLength(2); // board + liste
    expect(screen.getByText("1 / 1")).toBeInTheDocument();
  });
});

describe("Liens historiques de la fiche projet", () => {
  it("conserve l'onglet et redirige la modification", () => {
    expect(resolveLegacyLink("/projects/7/?tab=depenses")).toEqual({ kind: "app", to: "/projects/7?tab=depenses" });
    expect(resolveLegacyLink("/projects/7/")).toEqual({ kind: "app", to: "/projects/7" });
    expect(resolveLegacyLink("/projects/7/update/")).toEqual({ kind: "app", to: "/projects/7/edit" });
  });

  it("tableau de bord et espaces méthodologie → fiche projet intégrée", () => {
    expect(resolveLegacyLink("/projects/7/dashboard/")).toEqual({ kind: "app", to: "/projects/7?space=dashboard" });
    expect(resolveLegacyLink("/projects/7/scrum/")).toEqual({ kind: "app", to: "/projects/7?space=workspace" });
    expect(resolveLegacyLink("/projects/7/waterfall/")).toEqual({ kind: "app", to: "/projects/7?space=workspace" });
  });
});
