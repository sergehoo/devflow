import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TaskDetailPage } from "@/features/tasks/TaskDetailPage";
import { TasksPage } from "@/features/tasks/TasksPage";
import { ME, mockApi, renderPage } from "./utils";

const TASK = {
  id: 5, project: 7, project_name: "Portail", sprint: null, sprint_name: "", title: "Écran login", description: "",
  status: "TODO", status_label: "À faire", priority: "HIGH", priority_label: "Haute", assignee: 1, assignee_name: "Alice",
  estimate_hours: "4", spent_hours: "1", due_date: "2020-01-01", start_date: null, progress_percent: 0, is_flagged: false, is_archived: false,
};
const STATE = {
  id: 5, title: "Écran login", status: "TODO", status_label: "À faire", progress_percent: 0, spent_hours: "1", estimate_hours: "4",
  assignee_id: 1, assignee_name: "Alice", can_update: true,
  statuses: [{ value: "TODO", label: "À faire" }, { value: "IN_PROGRESS", label: "En cours" }, { value: "DONE", label: "Terminé" }],
};
const OVERVIEW = { state: STATE, description: "", reporter: "Paul", can_arbitrate: false, can_edit: true, can_delete: true, comments: [], attachments: [], assignments: [], checklists: [], subtasks: [], dependencies: [], labels: [] };
const LIST = { count: 1, next: null, previous: null, results: [TASK] };

afterEach(() => vi.restoreAllMocks());

describe("Tasks", () => {
  it("lists tasks, flags overdue ones and switches to the board", async () => {
    mockApi({ "auth/me/": ME, "forms/task/": { fields: [] }, "tasks/": LIST });
    renderPage(<TasksPage />, "/tasks", "/tasks");
    expect(await screen.findByRole("link", { name: "Écran login" })).toHaveAttribute("href", "/tasks/5");
    expect(screen.getByText("01 janv. 2020")).toHaveClass("text-destructive");
    await userEvent.click(screen.getByRole("button", { name: /Kanban/ }));
    expect(await screen.findByRole("region", { name: "À faire" })).toHaveTextContent("Écran login");
    expect(screen.getByRole("region", { name: "Terminé" })).toHaveTextContent("0");
  });

  it("sends a one-click quick update for the assignee", async () => {
    const spy = mockApi({
      "auth/me/": ME, "tasks/5/overview/": OVERVIEW, "tasks/5/": TASK,
      "POST tasks/5/quick-update/": { ...STATE, status: "IN_PROGRESS", status_label: "En cours" },
    });
    renderPage(<TaskDetailPage />, "/tasks/5", "/tasks/:id");
    await userEvent.click(await screen.findByRole("button", { name: "Démarrer" }));
    const call = spy.mock.calls.find(([url, init]) => String(url).includes("quick-update") && init?.method === "POST");
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ status: "IN_PROGRESS" });
  });

  it("is read-only for non-assignees", async () => {
    mockApi({
      "auth/me/": { ...ME, id: 9 }, "tasks/5/overview/": { ...OVERVIEW, state: { ...STATE, can_update: false } }, "tasks/5/": TASK,
    });
    renderPage(<TaskDetailPage />, "/tasks/5", "/tasks/:id");
    expect(await screen.findByText(/Lecture seule/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Démarrer" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Nouveau commentaire")).not.toBeInTheDocument();
  });
});
