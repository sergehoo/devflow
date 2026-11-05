import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NotificationsPage } from "@/features/notifications/NotificationsPage";
import { PreferencesPage } from "@/features/notifications/PreferencesPage";
import { mockApi, renderPage } from "./utils";

const N = (id: number, extra = {}) => ({
  id, type: "TASK", type_label: "Tâche", title: `Notif ${id}`, body: "Corps", url: `/tasks/${id}/`, is_read: false,
  read_at: null, created_at: "2026-11-04T09:00:00Z", workspace: { id: 1, name: "Alpha" }, ...extra,
});
const LIST = { count: 2, next: null, previous: null, results: [N(1), N(2, { is_read: true, url: "/risks/9/" })],
  unread_count: 1, read_count: 1, total_count: 2, types: [{ value: "TASK", label: "Tâche" }] };

afterEach(() => vi.restoreAllMocks());

describe("Notifications", () => {
  it("lists, filters unread, marks all as read and opens the React route", async () => {
    const spy = mockApi({ "POST me/notifications/read-all/": { updated: 1 }, "POST me/notifications/1/read/": N(1, { is_read: true }), "me/notifications/": LIST });
    renderPage(<NotificationsPage />, "/notifications");
    expect(await screen.findByText("Notif 1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Non lues/ }));
    await waitFor(() => expect(spy.mock.calls.some(([u]) => String(u).includes("status=unread"))).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: /Tout marquer comme lu/ }));
    await waitFor(() => expect(spy.mock.calls.some(([u, i]) => String(u).includes("read-all") && i?.method === "POST")).toBe(true));
    await userEvent.click(screen.getByText("Notif 1"));
    await waitFor(() => expect(spy.mock.calls.some(([u, i]) => String(u).includes("me/notifications/1/read/") && i?.method === "POST")).toBe(true));
  });

  it("saves only changed preferences", async () => {
    const prefs = { channel_in_app: true, channel_email: true, channel_digest: true, notify_frequency: "IMMEDIATE",
      quiet_hours_start: 22, quiet_hours_end: 7, priority_types: [],
      choices: { notify_frequency: [{ value: "IMMEDIATE", label: "Immédiat" }, { value: "DAILY", label: "Quotidien" }], priority_types: [{ value: "RISK", label: "Risque" }] } };
    const spy = mockApi({ "PATCH me/notification-preferences/": prefs, "me/notification-preferences/": prefs });
    renderPage(<PreferencesPage />, "/", "/");
    await userEvent.click(await screen.findByLabelText(/Par e-mail/));
    await userEvent.click(screen.getByRole("button", { name: "Risque" }));
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    await waitFor(() => expect(spy.mock.calls.some(([, i]) => i?.method === "PATCH")).toBe(true));
    const body = JSON.parse(String(spy.mock.calls.find(([, i]) => i?.method === "PATCH")![1]!.body));
    expect(body).toEqual({ channel_email: false, priority_types: ["RISK"] });
  });
});
