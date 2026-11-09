import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { ME, mockApi, renderPage } from "./utils";

const SUMMARY = {
  workspace: { id: 1, name: "Alpha", quarter_label: "T4 2026" },
  stats: { active_projects_count: 3, projects_total: 4, delayed_projects_count: 1, completed_projects_count: 1, project_completion_percent: 25,
    done_ratio_percent: 50, done_tasks_count: 5, pending_tasks_count: 5, blocked_tasks_count: 2, open_risks_count: 1, critical_risks_count: 0,
    active_members_count: 6, remote_members_count: 2 },
  finance: { currency: "XOF", approved_budget_total: 1000000, actual_expenses_total: 250000, expected_revenue_total: 0,
    received_revenue_total: 0, logged_hours_total: 12.5, budget_usage_percent: 25, actual_margin: -5000 },
  task_distribution: { todo: 3, in_progress: 2, review: 0, done: 5, blocked: 2, cancelled: 0 },
  analysis_cards: [{ severity: "high", title: "1 projet(s) en retard", text: "…", action: "Réviser les deadlines" }],
  projects: [], due_soon_tasks: [], active_sprint: null, team_load: [], top_cost_members: [],
  activities: [{ id: 1, title: "a terminé « Maquette »", actor: "Sarah K.", created_at: "2026-11-09T08:00:00Z" }],
};

const heatmap = Array.from({ length: 105 }, (_, i) => ({ date: new Date(Date.UTC(2026, 7, 1) + i * 86_400_000).toISOString().slice(0, 10), count: i % 9 === 0 ? 3 : 0 }));

const INSIGHTS = {
  workspace: { id: 1, name: "Alpha" }, today: "2026-11-09",
  day: { planned: 6, done: 3, completed_today: 3 },
  health: { active: 6, on_track: 4, at_risk: 1, delayed: 1, healthy_percent: 67 },
  overdue_tasks: 2, weeks: 15, heatmap, completed_in_period: 36,
  focus: [{ id: 11, title: "Finaliser l'onboarding", status: "TODO", status_label: "À faire", priority: "HIGH", priority_label: "High",
    due_date: "2026-11-09", estimate_hours: 2, project: "Portail A", assignee: "Ana B.", overdue: false }],
  focus_total: 4,
  upcoming: [
    { kind: "meeting", id: 5, title: "Comité de pilotage", subtitle: "Portail A", date: "2026-11-09", time: "16:00", url: "/meetings/5" },
    { kind: "milestone", id: 8, title: "Recette", subtitle: "Portail A", date: "2026-11-10", time: null, url: "/m/milestone/8" },
  ],
  projects: [{ id: 7, name: "Portail A", status_label: "En cours", progress_percent: 70, health: "on_track", target_date: "2026-12-01",
    members: ["Ana B.", "Yao K."], members_count: 2 }],
};

afterEach(() => vi.restoreAllMocks());

describe("DashboardPage", () => {
  it("compose la grille de référence à partir des données réelles de l'API", async () => {
    mockApi({ "auth/me/": ME, "dashboard/summary/": SUMMARY, "dashboard/insights/": INSIGHTS });
    renderPage(<DashboardPage />);
    expect(await screen.findByRole("heading", { name: "Tableau de bord" })).toBeInTheDocument();
    // Ma journée : ratio réel (3/6), pas de score inventé.
    expect(screen.getByRole("img", { name: "50 % des tâches du jour terminées" })).toBeInTheDocument();
    // Santé des projets.
    expect(screen.getByRole("img", { name: "67 % des projets actifs dans les délais" })).toBeInTheDocument();
    // Priorités, à venir, projets, activité.
    expect(screen.getByRole("link", { name: "Finaliser l'onboarding" })).toHaveAttribute("href", "/tasks/11");
    expect(screen.getByRole("link", { name: /Comité de pilotage/ })).toHaveAttribute("href", "/meetings/5");
    expect(screen.getByRole("link", { name: "Portail A" })).toHaveAttribute("href", "/projects/7");
    expect(screen.getByRole("progressbar", { name: "Avancement de Portail A" })).toHaveAttribute("aria-valuenow", "70");
    expect(screen.getByText("Sarah K.")).toBeInTheDocument();
    expect(screen.getByText(/36 tâche\(s\) terminée\(s\) sur les 15 dernières semaines/)).toBeInTheDocument();
    // Pilotage conservé (aucune perte fonctionnelle).
    expect(screen.getByText("1 projet(s) en retard")).toBeInTheDocument();
    expect(screen.getByText("Finances")).toBeInTheDocument();
  });

  it("change la période de la heatmap et recharge les indicateurs", async () => {
    const spy = mockApi({ "auth/me/": ME, "dashboard/summary/": SUMMARY, "dashboard/insights/": INSIGHTS });
    renderPage(<DashboardPage />);
    await userEvent.selectOptions(await screen.findByLabelText("Période"), "26");
    expect(spy.mock.calls.some(([u]) => String(u).includes("dashboard/insights/?weeks=26"))).toBe(true);
  });

  it("marque une tâche prioritaire terminée depuis le menu d'actions", async () => {
    const spy = mockApi({ "auth/me/": ME, "dashboard/summary/": SUMMARY, "dashboard/insights/": INSIGHTS, "POST tasks/11/toggle-complete/": {} });
    renderPage(<DashboardPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Actions pour « Finaliser l'onboarding »" }));
    await userEvent.click(within(await screen.findByRole("menu")).getByRole("menuitem", { name: /Marquer terminée/ }));
    expect(spy.mock.calls.some(([u, i]) => String(u).includes("tasks/11/toggle-complete/") && i?.method === "POST")).toBe(true);
  });

  it("shows an error state with retry when the API fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Erreur serveur" }), { status: 500 }));
    renderPage(<DashboardPage />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
