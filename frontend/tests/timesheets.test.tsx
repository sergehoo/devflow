import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HistoryPage } from "@/features/timesheets/HistoryPage";
import { SheetsPage } from "@/features/timesheets/SheetsPage";
import { ValidationPage } from "@/features/timesheets/ValidationPage";
import { WeekPage } from "@/features/timesheets/WeekPage";
import { ME, mockApi, renderPage } from "./utils";

const DAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"].map((label, i) => ({ date: `2026-10-${String(5 + i).padStart(2, "0")}`, label }));
const cells = (h: number[]) => DAYS.map((d, i) => ({ date: d.date, hours: h[i] ?? 0 }));
const WEEK = {
  user: { id: 1, name: "Alice" }, is_self: true, monday: "2026-10-05", iso_week: 41, year: 2026, days: DAYS, today: "2026-10-06",
  prev_week: "2026-09-28", next_week: "2026-10-12",
  rows: [{ kind: "task", row_id: "task-5", label: "API", task: { id: 5, title: "API", status_label: "En cours" }, project: { id: 7, name: "Portail" }, description: "", cells: cells([3]), total: 3 }],
  day_totals: Object.fromEntries(DAYS.map((d, i) => [d.date, i === 0 ? 3 : 0])), week_total: 3, week_status: "DRAFT", week_status_label: "Brouillon",
  is_locked: false, can_submit: true, can_review: false,
  summary: { status: "DRAFT", status_label: "Brouillon", total_hours: 3, planned_hours: 0, capacity: 40, expected: 16, missing_hours: 13, completion_percent: 19, last_log: null },
  history: [], projects: [{ id: 7, name: "Portail" }],
};

afterEach(() => vi.restoreAllMocks());

describe("Timesheets", () => {
  it("saves an edited cell through the Django calendar endpoint and submits the week", async () => {
    const spy = mockApi({ "timesheet/week/": WEEK, "POST actions/timesheet-cell/": { success: true }, "POST actions/timesheet-week/": { messages: ["Semaine soumise."] } });
    renderPage(<WeekPage />, "/timesheets?date=2026-10-06", "/timesheets");
    const input = await screen.findByLabelText("API — Mar : heures");
    await userEvent.type(input, "2.5");
    fireEvent.blur(input);
    await waitFor(() => expect(spy.mock.calls.some(([u, i]) => String(u).includes("timesheet-cell") && i?.method === "POST")).toBe(true));
    const body = spy.mock.calls.find(([u]) => String(u).includes("timesheet-cell"))![1]!.body as FormData;
    expect(Object.fromEntries(body.entries())).toEqual({ task_id: "5", date: "2026-10-06", hours: "2.5" });
    expect(screen.getByText("19 %")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Soumettre la semaine/ }));
    const submit = spy.mock.calls.find(([u]) => String(u).includes("timesheet-week"))![1]!.body as FormData;
    expect(submit.get("action")).toBe("submit");
    expect(submit.get("monday")).toBe("2026-10-05");
  });

  it("is read-only when the week is locked", async () => {
    mockApi({ "timesheet/week/": { ...WEEK, is_locked: true, can_submit: false, week_status: "SUBMITTED", week_status_label: "Soumis" } });
    renderPage(<WeekPage />, "/timesheets", "/timesheets");
    expect(await screen.findByText(/n'est plus modifiable/)).toBeInTheDocument();
    expect(screen.queryByLabelText("API — Mar : heures")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Soumettre/ })).not.toBeInTheDocument();
  });

  it("requires a comment to reject and approves in one click for the N+1", async () => {
    const group = { user: { id: 2, name: "Dan" }, monday: "2026-10-05", sunday: "2026-10-11", iso_week: 41, year: 2026, total_hours: 38, entry_count: 9, status: "SUBMITTED", status_label: "Soumis", can_review: true, is_mine: false };
    const spy = mockApi({ "timesheet/weeks/": { count: 1, next: null, previous: null, results: [group] }, "POST actions/timesheet-week/": { messages: [] } });
    renderPage(<ValidationPage />, "/timesheets/validation", "/timesheets/validation");
    expect(await screen.findByRole("link", { name: /Semaines validées/ })).toHaveAttribute("href", "/timesheets/sheets?status=APPROVED");
    await userEvent.click(await screen.findByRole("button", { name: /Rejeter/ }));
    expect(screen.getByRole("button", { name: "Rejeter" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Annuler" }));
    await userEvent.click(screen.getByRole("button", { name: /Valider/ }));
    const fd = spy.mock.calls.find(([u]) => String(u).includes("timesheet-week"))![1]!.body as FormData;
    expect([fd.get("user"), fd.get("action")]).toEqual(["2", "approve"]);
  });

  it("shows billable totals and edit actions only on editable entries", async () => {
    const entry = { id: 1, entry_date: "2026-10-05", user: { id: 1, name: "Alice" }, project: { id: 7, name: "Portail" }, task: null, hours: 2, planned_hours: null,
      description: "Réunion", is_billable: false, approval_status: "DRAFT", approval_status_label: "Brouillon", can_edit: true };
    mockApi({ "auth/me/": ME, "timesheet/entries/": {
      count: 2, next: null, previous: null, results: [entry, { ...entry, id: 2, user: { id: 2, name: "Dan" }, can_edit: false }],
      collaborators: [{ id: 1, name: "Alice" }, { id: 2, name: "Dan" }], projects: [{ id: 7, name: "Portail" }],
      totals: { hours: 4, billable_hours: 0, non_billable_hours: 4, by_user: [], by_project: [] },
    } });
    renderPage(<HistoryPage />, "/timesheets/history", "/timesheets/history");
    expect(await screen.findAllByRole("button", { name: "Modifier la saisie" })).toHaveLength(1);
    expect(screen.getByRole("option", { name: "Dan" })).toBeInTheDocument();
    expect(screen.getAllByText("4 h").length).toBeGreaterThan(0);
  });
});

describe("Feuilles de temps des collaborateurs", () => {
  const APPROVED = { user: { id: 2, name: "Dan" }, monday: "2026-10-05", sunday: "2026-10-11", iso_week: 41, year: 2026, total_hours: 38, entry_count: 9,
    status: "APPROVED", status_label: "Approuvé", can_review: true, is_mine: false };
  const exports = (spy: ReturnType<typeof mockApi>) => spy.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/export/"));
  const stubDownload = () => {
    Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  };

  it("keeps validated weeks reachable and exports them to Excel", async () => {
    stubDownload();
    const spy = mockApi({ "timesheet/week/export/": {}, "timesheet/export/": {},
      "timesheet/weeks/": { count: 1, next: null, previous: null, results: [APPROVED], collaborators: [{ id: 2, name: "Dan" }] } });
    renderPage(<SheetsPage />, "/timesheets/sheets?status=APPROVED", "/timesheets/sheets");
    expect(await screen.findByRole("link", { name: "Voir la semaine 41 de Dan" })).toHaveAttribute("href", "/timesheets?user=2&date=2026-10-05");
    expect(screen.getByRole("table", { name: "Feuilles de temps hebdomadaires" })).toHaveTextContent("Validée");
    expect(spy.mock.calls.map(([u]) => String(u)).find((u) => u.includes("timesheet/weeks/"))).toMatch(/status=APPROVED/);
    expect(screen.getByRole("option", { name: "Dan" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Exporter la semaine 41 de Dan en Excel" }));
    await waitFor(() => expect(exports(spy)).toHaveLength(1));
    expect(exports(spy)[0]).toContain("/api/v1/timesheet/week/export/?date=2026-10-05&user=2");
    expect(spy).toHaveBeenCalledWith(expect.stringContaining("timesheet/week/export/"), expect.objectContaining({ redirect: "manual" }));

    await userEvent.click(screen.getByRole("button", { name: /^Exporter en Excel$/ }));
    await waitFor(() => expect(exports(spy)).toHaveLength(2));
    const url = new URL(exports(spy)[1]!, "http://devflow.local");
    expect(url.pathname).toBe("/api/v1/timesheet/export/");
    expect(url.searchParams.get("approval_status")).toBe("APPROVED");
    expect(url.searchParams.has("page")).toBe(false);
  });

  it("opens a collaborator's validated week read-only with its Excel export", async () => {
    stubDownload();
    const spy = mockApi({ "timesheet/week/export/": {}, "timesheet/week/": {
      ...WEEK, user: { id: 2, name: "Dan" }, is_self: false, is_locked: true, can_submit: false, can_review: true,
      week_status: "APPROVED", week_status_label: "Approuvé",
      history: [{ action: "APPROVED", action_label: "Validée", actor: "Alice", comment: "", created_at: "2026-10-12T09:00:00Z" }],
    } });
    renderPage(<WeekPage />, "/timesheets?user=2&date=2026-10-05", "/timesheets");
    expect(await screen.findByRole("heading", { name: "Semaine de Dan" })).toBeInTheDocument();
    expect(screen.getByText("Validée — verrouillée")).toBeInTheDocument();
    expect(screen.queryByLabelText("API — Mar : heures")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Feuilles de Dan/ })).toHaveAttribute("href", "/timesheets/sheets?user=2");
    await userEvent.click(screen.getByRole("button", { name: /Exporter en Excel/ }));
    await waitFor(() => expect(exports(spy)).toEqual([expect.stringContaining("/api/v1/timesheet/week/export/?date=2026-10-05&user=2")]));
  });

  it("exports the history with its active filters and links each entry to the week", async () => {
    stubDownload();
    const entry = { id: 1, entry_date: "2026-10-06", user: { id: 2, name: "Dan" }, project: { id: 7, name: "Portail" }, task: null, hours: 2, planned_hours: null,
      description: "Réunion", is_billable: true, approval_status: "APPROVED", approval_status_label: "Approuvé", can_edit: false };
    const spy = mockApi({ "timesheet/export/": {}, "timesheet/entries/": {
      count: 1, next: null, previous: null, results: [entry], collaborators: [{ id: 2, name: "Dan" }], projects: [{ id: 7, name: "Portail" }],
      totals: { hours: 2, billable_hours: 2, non_billable_hours: 0, by_user: [], by_project: [] },
    } });
    renderPage(<HistoryPage />, "/timesheets/history", "/timesheets/history");
    expect(await screen.findByRole("link", { name: "Dan" })).toHaveAttribute("href", "/timesheets?user=2&date=2026-10-06");
    fireEvent.change(screen.getByLabelText("Collaborateur"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Statut"), { target: { value: "APPROVED" } });
    await userEvent.click(screen.getByRole("button", { name: /Exporter en Excel/ }));
    await waitFor(() => expect(exports(spy)).toHaveLength(1));
    const url = new URL(exports(spy)[0]!, "http://devflow.local");
    expect([url.searchParams.get("user"), url.searchParams.get("approval_status"), url.searchParams.has("page")]).toEqual(["2", "APPROVED", false]);
  });
});

describe("Timesheet ↔ tâches du projet", () => {
  const TASK = { id: 5, title: "API", status: "IN_PROGRESS", status_label: "En cours", progress_percent: 40, start_date: null,
    due_date: "2026-10-01", is_late: true, can_update: true };
  const ACTIVITY = { kind: "activity", row_id: "activity-7-1", label: "Réunion client", task: null, project: { id: 7, name: "Portail" },
    description: "Réunion client", cells: cells([0, 1]), total: 1 };
  const LIVE_WEEK = { ...WEEK, rows: [{ ...WEEK.rows[0], task: TASK }, ACTIVITY] };
  const posted = (spy: ReturnType<typeof mockApi>, path: string) =>
    JSON.parse(String(spy.mock.calls.find(([u, i]) => String(u).includes(path) && i?.method === "POST")![1]!.body));

  it("creates a real project task (not a timesheet-only line) with the day's hours", async () => {
    const spy = mockApi({ "timesheet/week/": LIVE_WEEK, "POST timesheet/tasks/": {
      task: { ...TASK, id: 9, title: "Recette API", status: "IN_PROGRESS", progress_percent: 0, is_late: false }, project: { id: 7, name: "Portail" }, hours: 2 } });
    renderPage(<WeekPage />, "/timesheets?date=2026-10-06", "/timesheets");
    await userEvent.click(await screen.findByRole("button", { name: "Tâche" }));
    await userEvent.selectOptions(screen.getByLabelText("Projet *"), "7");
    await userEvent.type(screen.getByLabelText("Intitulé *"), "Recette API");
    await userEvent.type(screen.getByLabelText("Heures"), "2");
    await userEvent.click(screen.getByRole("button", { name: "Créer la tâche" }));
    await waitFor(() => expect(spy.mock.calls.some(([u]) => String(u).includes("timesheet/tasks/"))).toBe(true));
    expect(posted(spy, "timesheet/tasks/")).toEqual({ project_id: 7, title: "Recette API", date: "2026-10-06", hours: "2" });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Créer la tâche" })).not.toBeInTheDocument());
  });

  it("shows the task's live state and updates it with the same quick update as /tasks", async () => {
    const state = { id: 5, title: "API", status: "IN_PROGRESS", status_label: "En cours", progress_percent: 40, spent_hours: "3", estimate_hours: null,
      assignee_id: 1, assignee_name: "Alice", can_update: true, statuses: [{ value: "IN_PROGRESS", label: "En cours" }, { value: "DONE", label: "Terminé" }] };
    const spy = mockApi({ "timesheet/week/": LIVE_WEEK, "tasks/5/overview/": { state }, "POST tasks/5/quick-update/": { ...state, status: "DONE", progress_percent: 100 } });
    renderPage(<WeekPage />, "/timesheets?date=2026-10-06", "/timesheets");
    expect(await screen.findByText("40 %")).toBeInTheDocument();
    expect(screen.getByText(/^éch\./)).toHaveClass("text-destructive");
    await userEvent.click(screen.getByRole("button", { name: "Mettre à jour la tâche API" }));
    await userEvent.click(await screen.findByRole("button", { name: /Terminer/ }));
    await waitFor(() => expect(posted(spy, "tasks/5/quick-update/")).toEqual({ status: "DONE" }));
  });

  it("converts a free activity into a project task", async () => {
    const spy = mockApi({ "timesheet/week/": LIVE_WEEK, "POST timesheet/activities/convert/": {
      task: { ...TASK, id: 11, title: "Réunion client" }, linked_entries: 1, created: true } });
    renderPage(<WeekPage />, "/timesheets?date=2026-10-06", "/timesheets");
    expect(await screen.findByText(/activité hors tâche/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Convertir en tâche/ }));
    await userEvent.click(screen.getByRole("button", { name: "Convertir" }));
    await waitFor(() => expect(posted(spy, "timesheet/activities/convert/")).toEqual({ project_id: 7, description: "Réunion client" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Convertir" })).not.toBeInTheDocument());
  });

  it("keeps a collaborator's week read-only: no task creation, conversion or quick update", async () => {
    mockApi({ "timesheet/week/": { ...LIVE_WEEK, is_self: false, is_locked: true, user: { id: 2, name: "Dan" },
      rows: [{ ...LIVE_WEEK.rows[0], task: { ...TASK, can_update: false } }, ACTIVITY] } });
    renderPage(<WeekPage />, "/timesheets?user=2&date=2026-10-06", "/timesheets");
    expect(await screen.findByText("40 %")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tâche" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Convertir en tâche/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Mettre à jour la tâche/ })).not.toBeInTheDocument();
  });
});
