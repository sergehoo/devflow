import { QueryClient } from "@tanstack/react-query";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flattenMessages, messagesKey, upsertMessage } from "@/features/messenger/api";
import { Conversation } from "@/features/messenger/Conversation";
import { ConversationList } from "@/features/messenger/ConversationList";
import { FakeWebSocket } from "./fakeSocket";
import { ME, mockApi, renderPage } from "./utils";

const MSG = (id: number, author_id: number, body: string) => ({
  id, channel_id: 9, author_id, author_name: author_id === 1 ? "Alice" : "Bob", body, created_at: "2026-11-04T10:00:00Z",
  attachments: [], reactions: [],
});
const PAGE = { channel: { id: 9, display_name: "Bob", member_count: 2 }, messages: [MSG(1, 2, "Salut Alice"), MSG(2, 1, "Hello")],
  others_last_read_at: "2026-11-04T10:00:00Z" };

beforeEach(() => FakeWebSocket.reset());
afterEach(() => vi.restoreAllMocks());

describe("Messenger", () => {
  it("merges optimistic, HTTP and WebSocket copies of a message without duplicates", () => {
    const qc = new QueryClient();
    qc.setQueryData(messagesKey(9), { pages: [{ ...PAGE, messages: [] }], pageParams: [undefined] });
    upsertMessage(qc, 9, { client_id: "c1", author_id: 1, body: "x", attachments: [], reactions: [], pending: true });
    upsertMessage(qc, 9, { ...MSG(5, 1, "x"), client_id: "c1" }); // écho WebSocket (client_id)
    upsertMessage(qc, 9, MSG(5, 1, "x"));                          // réponse HTTP (id)
    const list = flattenMessages(qc.getQueryData(messagesKey(9)));
    expect(list).toHaveLength(1);
    expect(list[0]).toMatchObject({ id: 5, pending: false });
  });

  it("shows history with read receipt, sends with client_id and applies live events", async () => {
    const spy = mockApi({
      "auth/me/": ME,
      "POST me/chat/channels/9/mark-read/": { unread_count: 0 },
      "POST me/chat/channels/9/messages/": (init: RequestInit) => ({ ...MSG(3, 1, "Nouveau"), client_id: (init.body as FormData).get("client_id") }),
      "me/chat/channels/9/messages/": PAGE,
    });
    renderPage(<Conversation channelId={9} title="Bob" />);
    expect(await screen.findByText("Salut Alice")).toBeInTheDocument();
    expect(screen.getByText("Vu")).toBeInTheDocument();
    await waitFor(() => expect(FakeWebSocket.instances.some((s) => s.url.endsWith("/ws/channels/9/"))).toBe(true));
    // Un seul socket pour la conversation, même après le chargement de l'utilisateur courant.
    expect(FakeWebSocket.instances.filter((s) => s.url.endsWith("/ws/channels/9/"))).toHaveLength(1);
    const ws = FakeWebSocket.instances.find((s) => s.url.endsWith("/ws/channels/9/"))!;
    act(() => ws.open());

    await userEvent.type(screen.getByLabelText("Message"), "Nouveau{Enter}");
    await waitFor(() => expect(spy.mock.calls.some(([u, i]) => String(u).includes("channels/9/messages/") && i?.method === "POST")).toBe(true));
    const fd = spy.mock.calls.find(([u, i]) => String(u).includes("channels/9/messages/") && i?.method === "POST")![1]!.body as FormData;
    expect(fd.get("body")).toBe("Nouveau");
    expect(fd.get("client_id")).toMatch(/^c/);
    // Écho WebSocket du même message : pas de doublon.
    act(() => ws.receive({ type: "chat_message", message: { ...MSG(3, 1, "Nouveau"), client_id: fd.get("client_id") } }));
    await waitFor(() => expect(screen.getAllByText("Nouveau")).toHaveLength(1));

    act(() => ws.receive({ type: "typing", is_typing: true, display_name: "Bob", user_id: 2 }));
    expect(screen.getByText("Bob écrit…")).toBeInTheDocument();
    act(() => ws.receive({ type: "reaction", message_id: 1, reactions: [{ emoji: "👍", count: 1, mine: false }] }));
    expect(await screen.findByRole("button", { name: "👍 1" })).toBeInTheDocument();
  });

  it("groups conversations by section with unread badges", async () => {
    const conv = (id: number, section: string, title: string, unread = 0) => ({ id, kind: section === "direct" ? "DM" : "TEAM", section, title,
      other_user_id: section === "direct" ? 2 : null, member_count: 2, last_message_preview: "…", last_message_at: null,
      last_author_is_me: false, unread_count: unread, is_muted: false });
    mockApi({ "auth/me/": ME, "me/presence/": { statuses: [{ user_id: 2, status: "online" }] },
      "me/chat/conversations/": { workspace_id: 1, conversations: [conv(1, "direct", "Bob", 3), conv(2, "teams", "Core")] } });
    const onSelect = vi.fn();
    renderPage(<ConversationList onSelect={onSelect} />);
    expect(await screen.findByRole("region", { name: "Messages directs" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Équipes" })).toBeInTheDocument();
    expect(screen.getByLabelText("3 non lu(s)")).toBeInTheDocument();
    expect(await screen.findByLabelText("En ligne")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Core"));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }));
  });
});
