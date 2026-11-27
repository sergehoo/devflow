import { QueryClient, QueryClientProvider, type QueryKey } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RealtimeBridge } from "@/features/realtime/RealtimeBridge";
import { invalidateTaskViews } from "@/features/tasks/sync";
import { realtime, type RealtimeHandler } from "@/lib/realtime";

/** Écrans qui montrent une tâche (même `dm.Task` côté Django) … */
const TASK_VIEWS: QueryKey[] = [
  ["tasks", "list", {}], ["tasks", 5, "overview"], ["timesheet", "week", "2026-10-06", "me"], ["projet", 7, "detail", "tasks"],
  ["projects", "list", {}], ["dashboard", "summary"], ["me", "today"], ["tracking", "board", {}], ["tracking", "project", 7],
];
/** … et ceux qu'une écriture sur une tâche ne concerne pas. */
const OTHERS: QueryKey[] = [["tracking", "imports", 3], ["tracking", "imports", "list"], ["notifications", "list"], ["me"]];

function seeded() {
  const qc = new QueryClient();
  [...TASK_VIEWS, ...OTHERS].forEach((key) => qc.setQueryData(key, {}));
  return qc;
}
const invalidated = (qc: QueryClient, key: QueryKey) => !!qc.getQueryState(key)?.isInvalidated;

afterEach(() => vi.restoreAllMocks());

describe("Synchronisation des écrans de tâches", () => {
  it("invalidates tasks, timesheet, project page and the Suivi together, never the import wizard", async () => {
    const qc = seeded();
    await invalidateTaskViews(qc);
    TASK_VIEWS.forEach((key) => expect(invalidated(qc, key), JSON.stringify(key)).toBe(true));
    OTHERS.forEach((key) => expect(invalidated(qc, key), JSON.stringify(key)).toBe(false));
  });

  it("refreshes every task screen when the server pushes task.changed (and after a reconnection)", async () => {
    let handler: RealtimeHandler = () => {};
    vi.spyOn(realtime, "subscribe").mockImplementation((_path, h) => { handler = h; return () => {}; });
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
    const qc = seeded();
    const router = createMemoryRouter([{ path: "*", element: <RealtimeBridge /> }]);
    render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>);
    await waitFor(() => expect(realtime.subscribe).toHaveBeenCalledWith("/ws/me/", expect.any(Function), { heartbeat: true }));

    act(() => handler({ type: "chat.read" }));
    expect(invalidated(qc, ["tracking", "board", {}])).toBe(false);

    act(() => handler({ type: "task.changed" }));
    await waitFor(() => TASK_VIEWS.forEach((key) => expect(invalidated(qc, key)).toBe(true)));
    expect(invalidated(qc, ["notifications", "list"])).toBe(false);

    const fresh = seeded();
    const again = createMemoryRouter([{ path: "*", element: <RealtimeBridge /> }]);
    render(<QueryClientProvider client={fresh}><RouterProvider router={again} /></QueryClientProvider>);
    act(() => handler({ type: "socket.open", reconnected: true }));
    await waitFor(() => expect(invalidated(fresh, ["timesheet", "week", "2026-10-06", "me"])).toBe(true));
  });
});
