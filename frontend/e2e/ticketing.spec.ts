import { expect, test } from "@playwright/test";
import { assignTo, fixtures, hookReceiver, inboundMail, integration, login, manage, openTicket, rawMail, reply, sentMails, validHookSignature, type Hook } from "./helpers";

/**
 * Parcours du ticketing de bout en bout (navigateur réel + Django + base E2E jetable).
 * Les tests s'enchaînent sur la même base : ordre significatif.
 */
test.describe.configure({ mode: "serial" });

let receiver: { hooks: Hook[]; close: () => Promise<void> };
let manualTicketPath = "";
const apiTicket = { reference: "", path: "" };

test.beforeAll(async () => { receiver = await hookReceiver(); });
test.afterAll(async () => { await receiver.close(); });

test("création manuelle → affectation → résolution, export Excel et assistant", async ({ page }) => {
  await login(page, "pm");
  await page.goto("/app/tickets/list");
  await page.getByRole("button", { name: /Nouveau ticket/ }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Application source").selectOption({ label: "Portail client E2E" });
  await dialog.getByLabel("Titre").fill("Export comptable en erreur");
  await dialog.getByLabel("Description").fill("Erreur 500 lors de l'export comptable mensuel.");
  await dialog.getByRole("button", { name: /Créer le ticket/ }).click();
  await expect(page.getByRole("heading", { name: "Export comptable en erreur" })).toBeVisible();
  manualTicketPath = new URL(page.url()).pathname;

  // Assistant IA : simple suggestion (IA désactivée en E2E → règles), rien d'appliqué.
  await page.getByRole("button", { name: /Suggérer la qualification/ }).click();
  await expect(page.getByRole("region", { name: "Qualification suggérée" })).toContainText("Règles DevFlow");

  await assignTo(page, "Ana E2E");

  // Export Excel de la liste (fichier .xlsx généré par Django, filtres actifs).
  await page.goto("/app/tickets/list?q=Export");
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: /Exporter Excel/ }).click()]);
  expect(download.suggestedFilename()).toMatch(/^Tickets.*\.xlsx$/);

  // L'agent est notifié, prend le ticket et le résout.
  await login(page, "agent");
  await page.goto("/app/notifications");
  await expect(page.getByText(/Export comptable en erreur|TCK-/).first()).toBeVisible();
  await page.goto(manualTicketPath);
  await page.getByRole("button", { name: "En cours", exact: true }).click();
  await expect(page.getByRole("button", { name: "Résolu", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Résolu", exact: true }).click();
  await page.getByRole("dialog").getByLabel("Message au déclarant").fill("Correctif déployé.");
  await page.getByRole("dialog").getByRole("button", { name: "Confirmer" }).click();
  await expect(page.getByText("Résolu").first()).toBeVisible();
});

test("création par API externe → webhooks signés en retour", async ({ page, request }) => {
  const created = await integration(request, "POST", "/api/v1/integrations/tickets/", {
    external_id: "E2E-API-1", title: "Paiement mobile refusé", description: "Le paiement échoue à la validation.",
    category: "BUG", severity: "MAJOR", reporter: { id: "u-1", name: "Awa", email: "awa@client.test" },
  });
  expect(created.status()).toBe(201);
  apiTicket.reference = (await created.json() as { reference: string }).reference;
  await expect.poll(() => receiver.hooks.find((h) => h.event === "ticket.created" && JSON.stringify(h.payload).includes(apiTicket.reference))).toBeTruthy();
  expect(receiver.hooks.every(validHookSignature)).toBe(true);

  const forged = await request.post("http://127.0.0.1:8010/api/v1/integrations/tickets/", {
    data: "{}", headers: { "Content-Type": "application/json", "X-DevFlow-App": fixtures().app.key_id, "X-DevFlow-Timestamp": "1", "X-DevFlow-Signature": "sha256=00" },
  });
  expect(forged.status()).toBe(401);

  await login(page, "pm");
  apiTicket.path = await openTicket(page, apiTicket.reference, "Paiement mobile refusé");
  await reply(page, "Nous analysons le paiement.");
  await reply(page, "Note interne : voir le prestataire.", true);
  await expect.poll(() => receiver.hooks.some((h) => h.event === "ticket.commented")).toBe(true);

  const history = await (await integration(request, "GET", "/api/v1/integrations/tickets/E2E-API-1/")).text();
  expect(history).toContain("Nous analysons le paiement.");
  expect(history).not.toContain("Note interne");
});

test("création par e-mail → réponse agent → réponse client", async ({ page, request }) => {
  const received = await inboundMail(request, rawMail({ from: "client@acme.test", subject: "Facture introuvable", body: "Je ne trouve pas la facture d'octobre." }));
  expect(received.status()).toBe(202);
  expect(sentMails().some((m) => /Subject: .*\[TCK-\d+\]/.test(m))).toBe(true);  // accusé de réception

  await login(page, "pm");
  const ticketPath = await openTicket(page, "Facture introuvable", "Facture introuvable");
  await reply(page, "Voici votre facture en piece jointe du portail.");
  await expect(page.getByText(/Envoyé par e-mail|Envoi en cours/).first()).toBeVisible();
  const outgoing = sentMails().find((m) => m.includes("Voici votre facture"));
  expect(outgoing).toBeTruthy();
  const messageId = /^Message-ID: (<[^>]+>)/im.exec(outgoing!)?.[1];
  expect(messageId).toBeTruthy();

  const answer = await inboundMail(request, rawMail({ from: "client@acme.test", subject: "Re: Facture introuvable", body: "Merci, bien recu.", inReplyTo: messageId }));
  expect(answer.status()).toBe(202);
  await page.goto(ticketPath);
  await expect(page.getByText("Merci, bien recu.")).toBeVisible();
});

test("ticket → tâche DevFlow → résolution synchronisée", async ({ page }) => {
  await login(page, "pm");
  await page.goto(apiTicket.path);
  await assignTo(page, "Ana E2E");
  await page.getByRole("button", { name: /Créer une tâche/ }).click();  // la tâche reprend l'agent du ticket
  const task = page.getByRole("link", { name: /Paiement mobile refusé|TCK-/ }).last();
  await expect(task).toBeVisible();
  const taskPath = (await task.getAttribute("href"))!;
  await login(page, "agent");  // seule la personne assignée met à jour la tâche
  await page.goto(taskPath);
  await page.getByRole("button", { name: "Démarrer" }).click();
  await page.getByRole("button", { name: "Terminer" }).click();
  await expect(page.getByRole("button", { name: "Rouvrir" })).toBeVisible();
  await page.goto(apiTicket.path);
  await expect(page.getByText("Résolu").first()).toBeVisible();
});

test("SLA dépassé → escalade et notifications", async ({ page, request }) => {
  const created = await integration(request, "POST", "/api/v1/integrations/tickets/", {
    external_id: "E2E-SLA-1", title: "Connexion impossible", category: "ACCESS", severity: "CRITICAL", reporter: { id: "u-2", name: "Koffi" },
  });
  const { reference } = await created.json() as { reference: string };
  expect(JSON.parse(manage("breach", "--reference", reference))).toMatchObject({ breached: 1 });

  await login(page, "pm");
  await openTicket(page, reference, "Connexion impossible");
  await expect(page.getByText("Dépassé").first()).toBeVisible();
  await expect(page.getByText(/Escalade niv\. 1/)).toBeVisible();
  await page.goto("/app/notifications");
  await expect(page.getByText(`Escalade niveau 1 : ${reference}`).first()).toBeVisible();  // dépassement + escalade auto
});

test("accès refusé entre workspaces", async ({ page }) => {
  await login(page, "bob");
  await page.goto(manualTicketPath);
  await expect(page.getByText("Ticket introuvable.")).toBeVisible();
  const id = manualTicketPath.split("/").pop();
  expect((await page.request.get(`/api/v1/tickets/${id}/`)).status()).toBe(404);
  expect((await page.request.get(`/api/v1/tickets/${id}/duplicates/`)).status()).toBe(404);
  const list = await (await page.request.get("/api/v1/tickets/")).json() as { results: { title: string }[] };
  expect(list.results.map((t) => t.title)).not.toContain("Export comptable en erreur");
});
