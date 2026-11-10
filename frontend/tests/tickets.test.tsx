import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApplicationsPage } from "@/features/tickets/SupportAdminPages";
import { TicketDetailPage } from "@/features/tickets/TicketDetailPage";
import { TicketsPage } from "@/features/tickets/TicketsPages";
import { ReportProblemWidget } from "@/widget/ReportProblemWidget";
import { ME, mockApi, renderPage } from "./utils";

const ROW = {
  id: 3, reference: "TCK-00003", title: "Paiement bloqué", status: "ASSIGNED", status_label: "Assigné", priority: "P1",
  priority_label: "P1 — Urgente", severity: "MAJOR", severity_label: "Majeure", category: "BUG", category_label: "Anomalie",
  application: { id: 1, name: "Portail client" }, team: { id: 2, name: "Support N1" }, assignee: { id: 9, name: "Ana B." },
  project: null, task_id: null, reporter_name: "Awa", workspace: 1, created_at: "2026-11-09T08:00:00Z", updated_at: "2026-11-09T09:00:00Z",
  first_response_due: "2099-01-01T00:00:00Z", resolution_due: "2099-01-01T00:00:00Z", first_response_breached: false,
  resolution_breached: false, escalation_level: 0, sla_paused: false,
};
const DETAIL = {
  ...ROW, description: "Le bouton Payer ne répond plus.", environment: "PRODUCTION", app_version: "2.4.1", url: "https://app.test/pay",
  metadata: { browser: "Firefox" }, external_id: "EXT-3", reporter_email: "awa@client.test", reporter_external_id: "u-42", task: null,
  qualified_at: null, assigned_at: null, first_response_at: null, resolved_at: null, closed_at: null, reopened_count: 0,
  sla: { policy: "Délais par défaut", first_response_due: "2099-01-01T00:00:00Z", resolution_due: "2099-01-01T00:00:00Z",
    first_response_remaining_seconds: 1800, resolution_remaining_seconds: 14400, paused: false, first_response_breached: false,
    resolution_breached: false, escalation_level: 0 },
  comments: [{ id: 1, body: "Note : client VIP", visibility: "INTERNAL", created_at: "2026-11-09T09:00:00Z", author: "Ana B.", external: false }],
  attachments: [], events: [{ id: 1, action: "created", actor: "Portail client", origin: "API", old: null, new: { status: "NEW" }, public: true, created_at: "2026-11-09T08:00:00Z" }],
  allowed_transitions: [{ value: "IN_PROGRESS", label: "En cours" }, { value: "RESOLVED", label: "Résolu" }],
  rights: { manage: true, assign: true, work: true },
};
const page = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results });

afterEach(() => vi.restoreAllMocks());

describe("Ticket Center", () => {
  it("liste les tickets avec filtres dans l'URL et bascule en Kanban", async () => {
    const spy = mockApi({ "auth/me/": ME, "tickets/": page([ROW]), "ticket-applications/": page([]) });
    renderPage(<TicketsPage />, "/tickets/list?priority=P1");
    expect(await screen.findByRole("link", { name: "Paiement bloqué" })).toHaveAttribute("href", "/tickets/3");
    expect(spy.mock.calls.some(([u]) => String(u).includes("priority=P1"))).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: /Kanban/ }));
    expect(await screen.findByRole("region", { name: "Assigné" })).toBeInTheDocument();
    expect(spy.mock.calls.some(([u]) => String(u).includes("status=NEW%2CQUALIFIED"))).toBe(true);
  });

  it("fiche : transition contrôlée par Django et note interne", async () => {
    const spy = mockApi({
      "auth/me/": ME, "tickets/3/": DETAIL,
      "POST tickets/3/transition/": { ...DETAIL, status: "IN_PROGRESS", status_label: "En cours" },
      "POST tickets/3/comment/": DETAIL,
    });
    renderPage(<TicketDetailPage />, "/tickets/3", "/tickets/:id");
    expect(await screen.findByRole("heading", { name: "Paiement bloqué" })).toBeInTheDocument();
    expect(screen.getByText("Note : client VIP")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "En cours" }));
    await waitFor(() => expect(spy.mock.calls.some(([u, i]) => String(u).includes("tickets/3/transition/") && i?.method === "POST")).toBe(true));
    await userEvent.click(screen.getByRole("radio", { name: "Note interne" }));
    await userEvent.type(screen.getByLabelText("Message"), "Vérifier les logs");
    await userEvent.click(screen.getByRole("button", { name: /Envoyer/ }));
    await waitFor(() => {
      const call = spy.mock.calls.find(([u, i]) => String(u).includes("tickets/3/comment/") && i?.method === "POST");
      expect((call?.[1]?.body as FormData).get("visibility")).toBe("INTERNAL");
    });
  });

  it("affiche le secret d'une nouvelle application une seule fois", async () => {
    mockApi({
      "auth/me/": { ...ME, permissions: ["ticket.*"] }, "ticket-applications/": page([]), "ticket-sla-policies/": page([]),
      "projects/": page([]), "teams/": page([]),
      "POST ticket-applications/": { id: 5, key_id: "app_123", secret: "dfs_secret", name: "Mobile" },
    });
    renderPage(<ApplicationsPage />);
    await userEvent.click(await screen.findByRole("button", { name: /Nouvelle application/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Nom"), "Mobile");
    await userEvent.type(within(dialog).getByLabelText("Code (slug)"), "mobile");
    await userEvent.click(within(dialog).getByRole("button", { name: "Créer l'application" }));
    expect(await screen.findByText("dfs_secret")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "J'ai enregistré le secret" }));
    await waitFor(() => expect(screen.queryByText("dfs_secret")).not.toBeInTheDocument());
  });
});

describe("Widget « Signaler un problème »", () => {
  it("envoie au backend hôte sans paramètre d'URL ni donnée sensible, avec Idempotency-Key", async () => {
    window.history.pushState({}, "", "/paiement?token=SECRET123&step=2#frag");
    document.cookie = "sessionid=SESSIONSECRET";
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify({ reference: "TCK-00042", external_id: "x", status_label: "Nouveau" }), { status: 201 }));
    renderPage(<ReportProblemWidget submitUrl="/support/report" appVersion="2.4.1" fetchImpl={fetchImpl as unknown as typeof fetch} />);
    await userEvent.click(screen.getByRole("button", { name: "Signaler un problème" }));
    await userEvent.type(screen.getByLabelText("Résumé"), "Le paiement échoue");
    await userEvent.click(screen.getByRole("button", { name: "Envoyer" }));
    expect(await screen.findByText("TCK-00042")).toBeInTheDocument();
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe("/support/report");
    const body = init.body as FormData;
    expect(body.get("url")).toBe(`${window.location.origin}/paiement`);
    const serialized = JSON.stringify([...body.entries()].map(([k, v]) => [k, typeof v === "string" ? v : "file"]));
    expect(serialized).not.toContain("SECRET123");
    expect(serialized).not.toContain("SESSIONSECRET");
    expect(init.headers["Idempotency-Key"]).toBe(body.get("external_id"));
  });

  it("n'envoie aucun contexte technique si l'utilisateur le décoche", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify({ reference: "TCK-1", external_id: "x", status_label: "Nouveau" }), { status: 201 }));
    renderPage(<ReportProblemWidget submitUrl="/support/report" fetchImpl={fetchImpl as unknown as typeof fetch} />);
    await userEvent.click(screen.getByRole("button", { name: "Signaler un problème" }));
    await userEvent.type(screen.getByLabelText("Résumé"), "Problème");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Envoyer" }));
    await screen.findByText("TCK-1");
    const body = fetchImpl.mock.calls[0]![1].body as FormData;
    expect(body.get("url")).toBeNull();
    expect(body.get("metadata")).toBeNull();
  });
});
