import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EmailChannelsPage } from "@/features/tickets/EmailChannelsPage";
import { ApplicationsPage } from "@/features/tickets/SupportAdminPages";
import { TicketDetailPage } from "@/features/tickets/TicketDetailPage";
import { TicketCenterPage, TicketsPage } from "@/features/tickets/TicketsPages";
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
  rights: { manage: true, assign: true, work: true, reply: true },
  source: "API", source_label: "API", created_by: null, mailbox: null, email_reply: false, emails: [],
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

const OPTIONS = {
  workspace: 1, applications: [{ id: 1, name: "Portail client", project: 7, default_team: 2 }],
  projects: [{ id: 7, name: "Refonte" }], teams: [{ id: 2, name: "Support N1" }],
  can_assign: true, can_set_priority: true, max_files: 5, max_attachment_mb: 20,
};
const DASHBOARD = {
  open: 0, unassigned: 0, mine: 0, breached: 0, due_24h: 0, created_7d: 0, resolved_7d: 0, sla_compliance: null,
  avg_first_response_minutes: null, by_status: {}, by_priority: {}, by_application: [], at_risk: [],
};

/** Ticket Center + fiche : vérifie l'ouverture automatique de la fiche après création. */
function renderCenter() {
  const router = createMemoryRouter([
    { path: "/tickets", element: <TicketCenterPage /> },
    { path: "/tickets/:id", element: <p>Fiche du ticket ouverte</p> },
  ], { initialEntries: ["/tickets"] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
}

describe("Création manuelle de ticket", () => {
  it("valide, envoie le formulaire au service Django puis ouvre la fiche", async () => {
    const spy = mockApi({
      "auth/me/": ME, "tickets/create-options/": OPTIONS, "tickets/agents/": [{ id: 9, name: "Ana B." }],
      "tickets/dashboard/": DASHBOARD, "POST tickets/": { ...DETAIL, id: 42, reference: "TCK-00042", source: "MANUAL" },
    });
    renderCenter();
    await userEvent.click(await screen.findByRole("button", { name: /Nouveau ticket/ }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByLabelText("Application source")).toHaveValue("1");  // application unique présélectionnée
    expect(within(dialog).getByLabelText("Projet")).toHaveValue("7");  // projet de l'application
    await userEvent.click(within(dialog).getByRole("button", { name: /Créer le ticket/ }));
    expect(within(dialog).getByText("Titre trop court (3 caractères minimum).")).toBeInTheDocument();
    expect(spy.mock.calls.some(([, i]) => i?.method === "POST")).toBe(false);
    await userEvent.type(within(dialog).getByLabelText("Titre"), "Export PDF en erreur");
    await userEvent.selectOptions(within(dialog).getByLabelText("Gravité"), "MAJOR");
    await userEvent.selectOptions(within(dialog).getByLabelText("Équipe"), "2");
    await userEvent.selectOptions(await within(dialog).findByRole("combobox", { name: "Responsable" }), "9");
    const file = new File(["%PDF-1.4"], "trace.pdf", { type: "application/pdf" });
    await userEvent.upload(dialog.querySelector("input[type=file]") as HTMLInputElement, file);
    expect(within(dialog).getByText("trace.pdf")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: /Créer le ticket/ }));
    expect(await screen.findByText("Fiche du ticket ouverte")).toBeInTheDocument();
    const call = spy.mock.calls.find(([u, i]) => String(u).endsWith("/api/v1/tickets/") && i?.method === "POST");
    const body = call?.[1]?.body as FormData;
    expect([body.get("application"), body.get("title"), body.get("severity"), body.get("team"), body.get("assignee"), body.get("project")])
      .toEqual(["1", "Export PDF en erreur", "MAJOR", "2", "9", "7"]);
    expect((body.get("attachments") as File).name).toBe("trace.pdf");
    expect(body.get("priority")).toBeNull();  // priorité dérivée de la gravité côté serveur
  });

  it("masque le bouton sans droit et propose le routage automatique sans droit d'affectation", async () => {
    mockApi({ "auth/me/": { ...ME, permissions: ["ticket.view_assigned"] }, "tickets/dashboard/": DASHBOARD });
    renderCenter();
    expect(await screen.findByRole("heading", { name: "Ticket Center" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Nouveau ticket/ })).not.toBeInTheDocument();
  });

  it("membre : ni équipe ni priorité imposables, affiche l'erreur serveur", async () => {
    mockApi({
      "auth/me/": { ...ME, permissions: ["ticket.create", "ticket.view_assigned"] }, "tickets/dashboard/": DASHBOARD,
      "tickets/create-options/": { ...OPTIONS, can_assign: false, can_set_priority: false },
    });
    renderCenter();
    await userEvent.click(await screen.findByRole("button", { name: /Nouveau ticket/ }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/attribués automatiquement selon les règles de routage/)).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Équipe")).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Priorité")).not.toBeInTheDocument();
  });
});

describe("Canal e-mail", () => {
  const EMAIL_DETAIL = {
    ...DETAIL, source: "EMAIL", source_label: "E-mail", mailbox: { id: 4, name: "Support", address: "support@alpha.test" }, email_reply: true,
    comments: [{ id: 11, body: "Toujours bloqué.", visibility: "PUBLIC", created_at: "2026-11-09T10:00:00Z", author: "Awa", external: true },
      { id: 12, body: "Réinitialisez le mot de passe.", visibility: "PUBLIC", created_at: "2026-11-09T11:00:00Z", author: "Ana B.", external: false }],
    emails: [
      { id: 1, direction: "IN", kind: "NEW_TICKET", kind_label: "Nouveau ticket", status: "PROCESSED", status_label: "Traité", from: "awa@client.test", to: "", subject: "Paiement", reason: "", comment_id: null, attempt: 1, created_at: "2026-11-09T08:00:00Z" },
      { id: 2, direction: "OUT", kind: "ACK", kind_label: "Accusé de réception", status: "DEAD", status_label: "Abandonné", from: "support@alpha.test", to: "awa@client.test", subject: "[TCK-00003] Paiement", reason: "SMTPRecipientsRefused", comment_id: null, attempt: 5, created_at: "2026-11-09T08:00:01Z" },
      { id: 3, direction: "IN", kind: "REPLY", kind_label: "Réponse", status: "PROCESSED", status_label: "Traité", from: "awa@client.test", to: "", subject: "Re: Paiement", reason: "", comment_id: 11, attempt: 1, created_at: "2026-11-09T10:00:00Z" },
      { id: 4, direction: "OUT", kind: "AGENT_REPLY", kind_label: "Réponse de l'équipe", status: "SENT", status_label: "Envoyé", from: "support@alpha.test", to: "awa@client.test", subject: "Re: Paiement", reason: "", comment_id: 12, attempt: 1, created_at: "2026-11-09T11:00:01Z" },
    ],
  };

  it("fiche : source, échanges e-mail, statuts de livraison et réponse par e-mail", async () => {
    mockApi({ "auth/me/": ME, "tickets/3/": EMAIL_DETAIL });
    renderPage(<TicketDetailPage />, "/tickets/3", "/tickets/:id");
    expect(await screen.findByRole("heading", { name: "Paiement bloqué" })).toBeInTheDocument();
    expect(screen.getAllByText("E-mail").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Reçu par e-mail").length).toBe(2);
    expect(screen.getByText("Envoyé par e-mail")).toBeInTheDocument();
    expect(screen.getByText("SMTPRecipientsRefused")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Répondre par e-mail" })).toBeInTheDocument();
    expect(screen.getByText("awa@client.test", { selector: "strong" })).toBeInTheDocument();
  });

  const BOX = {
    id: 4, workspace: 1, application: 1, project: null, name: "Support client", address: "support@alpha.test", from_name: "", is_active: true,
    inbound: "IMAP", imap_host: "imap.alpha.test", imap_port: 993, imap_security: "SSL", imap_username: "support", imap_folder: "INBOX",
    has_imap_password: true, smtp_host: "", smtp_port: 465, smtp_security: "SSL", smtp_username: "", has_smtp_password: false,
    auto_acknowledge: true, default_category: "QUESTION", allowed_domains: [], blocked_senders: [], max_attachment_mb: 10,
    inbound_key: "mbx_1", webhook_url: "https://x/api/v1/integrations/mail/mbx_1/", last_sync_at: "2026-11-10T08:00:00Z",
    last_success_at: "2026-11-09T08:00:00Z", last_error: "error: [AUTHENTICATIONFAILED] invalid ***", last_error_at: "2026-11-10T08:00:00Z",
    consecutive_failures: 3, stats: { PROCESSED: 4, REJECTED: 1 }, created_at: "2026-11-01T08:00:00Z",
  };

  it("administration : supervision, test de connexion et file des messages rejetés", async () => {
    const spy = mockApi({
      "auth/me/": ME, "ticket-applications/": page([{ id: 1, name: "Portail client" }]), "ticket-mailboxes/4/messages/": page([
        { id: 8, direction: "IN", kind: "UNKNOWN", kind_label: "Non reconnu", status: "REJECTED", status_label: "Rejeté", from: "x@evil.test",
          from_name: "", to: "", subject: "Re: [TCK-00001]", reason: "Expéditeur non autorisé pour TCK-00001.", size: 900, attempt: 1,
          created_at: "2026-11-10T08:00:00Z", processed_at: "2026-11-10T08:00:01Z", ticket: null, can_reprocess: true }]),
      "POST ticket-mailboxes/4/test/": { imap: { ok: false, detail: "error: [AUTHENTICATIONFAILED]" }, smtp: { ok: true, detail: "Messagerie DevFlow" } },
      "POST ticket-mailboxes/4/messages/8/reprocess/": { status: "RECEIVED" },
      "ticket-mailboxes/": page([BOX]), "projects/": page([]), "teams/": page([]),
    });
    renderPage(<EmailChannelsPage />);
    expect(await screen.findByRole("heading", { name: "Support client" })).toBeInTheDocument();
    expect(screen.getByText("En erreur")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("3 échec(s) consécutif(s)");
    expect(document.body.textContent).not.toContain("imap-pass");
    await userEvent.click(screen.getByRole("button", { name: /Tester la connexion/ }));
    expect(await screen.findByText(/AUTHENTICATIONFAILED\]$/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Messages/ }));
    expect(await screen.findByText("Expéditeur non autorisé pour TCK-00001.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Retraiter/ }));
    await waitFor(() => expect(spy.mock.calls.some(([u, i]) => String(u).includes("messages/8/reprocess/") && i?.method === "POST")).toBe(true));
  });

  it("réservé aux administrateurs du support", async () => {
    mockApi({ "auth/me/": { ...ME, permissions: ["ticket.view", "ticket.manage"] } });
    renderPage(<EmailChannelsPage />);
    expect(await screen.findByText("Réservé aux administrateurs du support")).toBeInTheDocument();
  });
});

describe("Export Excel et assistant IA", () => {
  const stubDownload = () => {
    Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  };
  const exportCall = (spy: ReturnType<typeof mockApi>) => spy.mock.calls.map(([u]) => String(u)).find((u) => u.includes("tickets/export/"));
  const posts = (spy: ReturnType<typeof mockApi>, part: string) =>
    spy.mock.calls.filter(([u, i]) => String(u).includes(part) && i?.method === "POST");
  const field = (value: string, label: string, current: string) => ({ value, label, current, changed: value !== current });

  it("exporte la liste avec les filtres actifs, sans pagination", async () => {
    stubDownload();
    const spy = mockApi({ "auth/me/": ME, "tickets/export/": {}, "tickets/": page([ROW]), "ticket-applications/": page([]) });
    renderPage(<TicketsPage />, "/tickets/list?priority=P1&q=pay&page=2");
    await screen.findByRole("link", { name: "Paiement bloqué" });
    await userEvent.click(screen.getByRole("button", { name: /Exporter Excel/ }));
    await waitFor(() => expect(exportCall(spy)).toBeDefined());
    const url = new URL(exportCall(spy)!, "http://devflow.local");
    expect([url.searchParams.get("priority"), url.searchParams.get("q"), url.searchParams.get("workspace")]).toEqual(["P1", "pay", "1"]);
    expect(url.searchParams.has("page") || url.searchParams.has("page_size")).toBe(false);
    expect(spy).toHaveBeenCalledWith(expect.stringContaining("tickets/export/"), expect.objectContaining({ redirect: "manual" }));
  });

  it("exporte depuis le Ticket Center pour le workspace courant", async () => {
    stubDownload();
    const spy = mockApi({ "auth/me/": ME, "tickets/export/": {}, "tickets/dashboard/": DASHBOARD });
    renderPage(<TicketCenterPage />, "/tickets");
    await userEvent.click(await screen.findByRole("button", { name: /Exporter Excel/ }));
    await waitFor(() => expect(exportCall(spy)).toContain("/api/v1/tickets/export/?workspace=1"));
  });

  it("suggère une qualification que l'agent applique lui-même", async () => {
    const triage = { category: field("INCIDENT", "Incident", "BUG"), severity: field("MAJOR", "Majeure", "MAJOR"),
      priority: field("P2", "P2 — Haute", "P1"), rationale: "Panne générale.", source: "ai", provider: "deepseek" };
    const spy = mockApi({ "auth/me/": ME, "POST tickets/3/ai/triage/": triage, "POST tickets/3/qualify/": DETAIL, "tickets/3/": DETAIL });
    renderPage(<TicketDetailPage />, "/tickets/3", "/tickets/:id");
    await userEvent.click(await screen.findByRole("button", { name: /Suggérer la qualification/ }));
    const box = await screen.findByRole("region", { name: "Qualification suggérée" });
    expect(within(box).getByText("Incident")).toBeInTheDocument();
    expect(within(box).getByText("Proposé par l'IA (deepseek)")).toBeInTheDocument();
    expect(posts(spy, "qualify/")).toHaveLength(0);  // rien d'appliqué sans clic
    await userEvent.click(within(box).getByRole("button", { name: /Appliquer/ }));
    await waitFor(() => expect(posts(spy, "qualify/")).toHaveLength(1));
    expect(JSON.parse(String(posts(spy, "qualify/")[0]![1]!.body))).toEqual({ category: "INCIDENT", priority: "P2" });
  });

  it("reprend une proposition de réponse sans l'envoyer et liste les doublons", async () => {
    const spy = mockApi({
      "auth/me/": ME, "POST tickets/3/ai/reply/": { reply: "Bonjour Awa, nous analysons.", source: "rules", provider: "" },
      "tickets/3/duplicates/": { results: [{ id: 8, reference: "TCK-00008", title: "Paiement refusé", status: "NEW", status_label: "Nouveau",
        application: "Portail client", created_at: "2026-11-08T08:00:00Z", score: 0.62, reasons: ["même application"] }] },
      "tickets/3/": DETAIL,
    });
    renderPage(<TicketDetailPage />, "/tickets/3", "/tickets/:id");
    await userEvent.click(await screen.findByRole("button", { name: /Proposer une réponse/ }));
    const box = await screen.findByRole("region", { name: "Proposition de réponse" });
    expect(within(box).getByText(/Règles DevFlow/)).toBeInTheDocument();
    await userEvent.click(within(box).getByRole("button", { name: "Reprendre dans la réponse" }));
    expect(screen.getByLabelText("Message")).toHaveValue("Bonjour Awa, nous analysons.");
    expect(posts(spy, "comment/")).toHaveLength(0);  // aucune réponse envoyée automatiquement
    await userEvent.click(screen.getByRole("button", { name: /Rechercher des doublons/ }));
    expect(await screen.findByRole("link", { name: "TCK-00008 · Paiement refusé" })).toHaveAttribute("href", "/tickets/8");
    expect(screen.getByText(/similarité 62 %/)).toBeInTheDocument();
  });

  it("n'affiche pas l'assistant à qui ne traite pas le ticket", async () => {
    mockApi({ "auth/me/": ME, "tickets/3/": { ...DETAIL, rights: { manage: false, assign: false, work: false, reply: true } } });
    renderPage(<TicketDetailPage />, "/tickets/3", "/tickets/:id");
    expect(await screen.findByRole("heading", { name: "Paiement bloqué" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Suggérer la qualification/ })).not.toBeInTheDocument();
  });
});

describe("Modes de collecte et tâche sans projet", () => {
  const APP = { id: 1, workspace: 1, name: "Boutique", code: "boutique", description: "", project: null, environment: "PRODUCTION", status: "ACTIVE",
    teams: [], default_team: null, sla_policy: null, key_id: "app_x", secret_last4: "abcd", secret_rotated_at: null, webhook_url: "",
    webhook_events: [], rate_limit_per_minute: 60, daily_ticket_quota: 500, max_attachment_mb: 10, retention_days: null, config: {},
    created_at: "2026-11-09T08:00:00Z", open_tickets: 0 };
  const channel = { enabled: false, label: "", count_30d: 0, last_ticket: null, last_error: null };
  const COLLECTION = { modes: { api: true, form: false, widget: false, hosted: true }, public_key: "dfp_PUBLIC", public_slug: "boutique-1",
    allowed_origins: ["https://app.boutique.test"], key_id: "app_x", hosted_path: "/support/app/boutique-1/",
    channels: { api: channel, form: channel, widget: channel, hosted: { ...channel, last_error: { reason: "origine refusée : https://evil.test" } }, email: { ...channel, mailboxes: [] } } };

  it("active un mode, affiche le code à copier sans secret et teste la configuration", async () => {
    const spy = mockApi({
      "auth/me/": ME, "PATCH ticket-applications/1/collection/": { ...COLLECTION, modes: { ...COLLECTION.modes, widget: true } },
      "POST ticket-applications/1/collection/test/": { mode: "hosted", ok: true, checks: [{ label: "Mode activé", ok: true }] },
      "ticket-applications/1/collection/": COLLECTION, "ticket-applications/": page([APP]), "ticket-routing-rules/": page([]), "ticket-sla-policies/": page([]),
    });
    renderPage(<ApplicationsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Modes de collecte" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByLabelText("Code Formulaire public hébergé")).toHaveTextContent("/support/app/boutique-1/");
    expect(within(dialog).getByText(/origine refusée/)).toBeInTheDocument();
    expect(dialog).not.toHaveTextContent("abcd");
    await userEvent.click(within(dialog).getByRole("switch", { name: "Activer : Widget intégré" }));
    await waitFor(() => expect(spy.mock.calls.some(([u, i]) => String(u).includes("collection/") && i?.method === "PATCH")).toBe(true));
    const patch = spy.mock.calls.find(([u, i]) => String(u).includes("collection/") && i?.method === "PATCH")![1]!;
    expect(JSON.parse(String(patch.body))).toEqual({ modes: { widget: true } });
    expect(await within(dialog).findByLabelText("Code Widget intégré")).toHaveTextContent('data-app="boutique-1"');
    await userEvent.click(within(within(dialog).getByRole("region", { name: "Formulaire public hébergé" })).getByRole("button", { name: "Tester la configuration" }));
    expect(await within(dialog).findByLabelText("Résultat du test Formulaire public hébergé")).toHaveTextContent("Mode activé");
  });

  it("demande le projet de la tâche quand le ticket n'en a pas", async () => {
    const spy = mockApi({
      "auth/me/": ME, "tickets/create-options/": { ...OPTIONS, projects: [{ id: 4, name: "Portail" }] },
      "POST tickets/3/create-task/": { ...DETAIL, task: { id: 9, name: "[TCK-00003] Paiement bloqué" } }, "tickets/3/": DETAIL,
    });
    renderPage(<TicketDetailPage />, "/tickets/3", "/tickets/:id");
    await userEvent.click(await screen.findByRole("button", { name: /Créer une tâche/ }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByRole("option", { name: "Portail" });
    await userEvent.selectOptions(within(dialog).getByLabelText("Projet"), "4");
    await userEvent.click(within(dialog).getByRole("button", { name: "Créer la tâche" }));
    await waitFor(() => {
      const call = spy.mock.calls.find(([u, i]) => String(u).includes("create-task") && i?.method === "POST");
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ project: 4 });
    });
  });
});
