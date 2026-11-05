import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { ME, mockApi, renderPage } from "./utils";

const SUMMARY = {
  workspace: { id: 1, name: "Alpha", quarter_label: "T4 2026" },
  stats: { active_projects_count: 3, projects_total: 4, delayed_projects_count: 1, done_ratio_percent: 50, done_tasks_count: 5,
    pending_tasks_count: 5, blocked_tasks_count: 2, open_risks_count: 1, critical_risks_count: 0, active_members_count: 6, remote_members_count: 2 },
  finance: { currency: "XOF", approved_budget_total: 1000000, actual_expenses_total: 250000, expected_revenue_total: 0,
    received_revenue_total: 0, logged_hours_total: 12.5, budget_usage_percent: 25, actual_margin: -5000 },
  task_distribution: { todo: 3, in_progress: 2, review: 0, done: 5, blocked: 2, cancelled: 0 },
  analysis_cards: [{ severity: "high", title: "1 projet(s) en retard", text: "…", action: "Réviser les deadlines" }],
  projects: [{ id: 7, name: "Portail A", status: "ACTIVE", status_label: "Actif", progress_percent: 40, risk_score: 80,
    target_date: "2026-12-01", team: "Core", tech_stack: "" }],
  due_soon_tasks: [], active_sprint: null, team_load: [], top_cost_members: [], activities: [],
};

afterEach(() => vi.restoreAllMocks());

describe("DashboardPage", () => {
  it("renders the workspace KPIs, analysis and projects from the API", async () => {
    mockApi({ "auth/me/": ME, "dashboard/summary/": SUMMARY });
    renderPage(<DashboardPage />);
    expect(await screen.findByText("Portail A")).toBeInTheDocument();
    expect(screen.getByText("Alpha · T4 2026")).toBeInTheDocument();
    expect(screen.getByText("1 projet(s) en retard")).toBeInTheDocument();
    expect(screen.getByText("Risque 80")).toBeInTheDocument();
    expect(screen.getByText("Aucune échéance proche.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Portail A/ })).toHaveAttribute("href", expect.stringContaining("/projects/7"));
  });

  it("shows an error state with retry when the API fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Erreur serveur" }), { status: 500 }));
    renderPage(<DashboardPage />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
