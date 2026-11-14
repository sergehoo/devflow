import { mkdirSync } from "node:fs";
import { createServer, type Server } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { assignTo, DJANGO, fixtures, login, openTicket, reply } from "./helpers";

/**
 * Application SANS API : ajout, modes de collecte, formulaire public hébergé, widget,
 * formulaire existant (SDK), puis traitement complet du ticket jusqu'à sa clôture.
 * Base E2E locale ; captures dans e2e/.state/screens.
 */
test.describe.configure({ mode: "serial" });

const HOST = "http://127.0.0.1:8098";  // site « client » qui intègre le widget et le SDK
const SHOTS = path.join(path.dirname(fileURLToPath(import.meta.url)), ".state", "screens");
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8AAAAMBAQAYoT0WAAAAAElFTkSuQmCC", "base64");
const pages: Record<string, string> = {};
let site: Server;
const cfg = { key: "", slug: "", hosted: "" };
const portal = { reference: "", code: "", path: "" };

const shot = (page: Page, name: string) => page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });

test.beforeAll(async () => {
  mkdirSync(SHOTS, { recursive: true });
  site = createServer((req, res) => {
    const html = pages[(req.url ?? "/").split("?")[0]!];
    res.writeHead(html ? 200 : 404, { "Content-Type": "text/html; charset=utf-8" }).end(html ?? "introuvable");
  });
  await new Promise<void>((resolve) => site.listen(8098, "127.0.0.1", () => resolve()));
});
test.afterAll(async () => { await new Promise((done) => site.close(done)); });

async function fillReport(scope: Page | ReturnType<Page["frameLocator"]>, title: string, email = "client@boutique.test") {
  await scope.locator("#f-email").fill(email);
  await scope.locator("#f-title").fill(title);
  await scope.locator("#f-description").fill("Le panier se vide au moment du paiement.");
}

test("1-2 · ajout d'une application sans API et activation de ses modes de collecte", async ({ page }) => {
  await login(page, "owner");
  await page.goto("/app/tickets/applications");
  await page.getByRole("button", { name: "Nouvelle application" }).click();
  const form = page.getByRole("dialog");
  await form.getByLabel("Nom", { exact: true }).fill("Boutique sans API");
  await form.getByLabel("Code (slug)").fill("boutique");
  await form.getByLabel("Équipe par défaut").selectOption({ label: "Support N1" });
  await form.getByRole("button", { name: "Créer l'application" }).click();
  await page.getByRole("button", { name: "J'ai enregistré le secret" }).click();

  const card = page.getByRole("heading", { name: "Boutique sans API" }).locator("xpath=ancestor::div[contains(@class,'p-5')][1]");
  await card.getByRole("button", { name: "Modes de collecte" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator("#allowed-origins").fill(HOST);
  await dialog.getByRole("button", { name: "Enregistrer les domaines" }).click();
  for (const mode of ["Formulaire public hébergé", "Widget intégré", "Formulaire existant"]) {
    const toggle = dialog.getByRole("switch", { name: `Activer : ${mode}` });
    await toggle.check();
    await expect(toggle).toBeChecked();
    await expect(toggle).toBeEnabled();
  }
  cfg.hosted = (await dialog.getByLabel("Code Formulaire public hébergé").textContent())!.trim();
  cfg.slug = cfg.hosted.split("/support/app/")[1]!.replace(/\/$/, "");
  cfg.key = /dfp_[\w-]+/.exec((await dialog.locator("code").first().textContent())!)![0];
  await expect(dialog.getByLabel("Code Widget intégré")).toContainText(`data-app="${cfg.slug}"`);
  await expect(dialog.getByLabel("Code Formulaire existant")).toContainText(cfg.key);
  await expect(dialog).not.toContainText(fixtures().app.secret);  // aucun secret dans le code à copier
  await dialog.getByRole("region", { name: "Formulaire public hébergé" }).getByRole("button", { name: "Tester la configuration" }).click();
  await expect(dialog.getByLabel("Résultat du test Formulaire public hébergé")).not.toContainText("✕");
  await expect(dialog.getByLabel("Résultat du test Formulaire public hébergé").locator(".text-destructive")).toHaveCount(0);
  await shot(page, "01-modes-de-collecte");
});

test("3-5 · incident déclaré sur le formulaire public, reçu dans la bonne application et le bon workspace", async ({ browser, page }) => {
  const visitor = await (await browser.newContext()).newPage();  // utilisateur externe, sans compte
  await visitor.goto(cfg.hosted);
  await expect(visitor.getByRole("heading", { name: "Signaler un problème" })).toBeVisible();
  await shot(visitor, "02-formulaire-public");
  await fillReport(visitor, "Panier vidé au paiement");
  await visitor.locator("#f-files").setInputFiles({ name: "capture.png", mimeType: "image/png", buffer: PNG });
  await visitor.locator("#submit").click();
  await expect(visitor.locator("#report-error")).toContainText("trop rapide");  // anti-robot : délai minimal
  await visitor.waitForTimeout(3_200);
  await visitor.locator("#submit").click();
  await expect(visitor.locator("#report-ok")).toContainText("Signalement enregistré");
  portal.reference = (await visitor.locator("#report-ok strong").textContent())!.trim();
  portal.code = (await visitor.locator("#report-ok .code").textContent())!.trim();
  await shot(visitor, "03-confirmation");

  await visitor.goto(cfg.hosted);  // doublon : même déclarant, même objet → même référence
  await fillReport(visitor, "Panier vidé au paiement");
  await visitor.waitForTimeout(3_200);
  await visitor.locator("#submit").click();
  await expect(visitor.locator("#report-ok")).toContainText(`déjà été reçu. Référence : ${portal.reference}`);
  await visitor.context().close();

  await login(page, "pm");
  await page.goto("/app/tickets");
  await expect(page.getByRole("heading", { name: "Ticket Center" })).toBeVisible();
  await shot(page, "04-ticket-center");
  portal.path = await openTicket(page, portal.reference, "Panier vidé au paiement");
  await expect(page.getByText(`${portal.reference} · Boutique sans API`)).toBeVisible();
  await expect(page.getByText("Formulaire public").first()).toBeVisible();
  const detail = await (await page.request.get(`/api/v1/tickets/${portal.path.split("/").pop()}/`)).json() as { workspace: number; application: { name: string }; attachments: unknown[] };
  expect([detail.workspace, detail.application.name, detail.attachments.length]).toEqual([fixtures().workspaces.alpha, "Boutique sans API", 1]);
});

test("6 · widget par balise script et formulaire existant connecté par le SDK", async ({ browser }) => {
  pages["/widget.html"] = `<!doctype html><html lang="fr"><body><h1>Boutique</h1>
    <script src="${DJANGO}/static/support/devflow-widget.js" data-app="${cfg.slug}" data-name="Boutique (widget)" defer></script></body></html>`;
  pages["/form.html"] = `<!doctype html><html lang="fr"><body><form id="report">
    <label>Sujet <input name="sujet"></label><label>Message <textarea name="message"></textarea></label>
    <label>Email <input name="email"></label><button type="submit">Envoyer</button></form>
    <script src="${DJANGO}/static/support/devflow-intake.js"></script>
    <script>DevFlowIntake.connect(document.querySelector("#report"), { app: "${cfg.key}", fields: { title: "sujet", description: "message", email: "email" } });</script>
    </body></html>`;
  const page = await (await browser.newContext()).newPage();

  await page.goto(`${HOST}/widget.html`);
  await page.getByRole("button", { name: "Signaler un problème" }).click();
  const frame = page.frameLocator('iframe[title="Signaler un problème"]');
  await expect(frame.getByText("Boutique (widget)")).toBeVisible();  // nom personnalisé par l'intégrateur
  await fillReport(frame, "Bouton payer inactif", "widget@boutique.test");
  await page.waitForTimeout(3_200);
  await frame.locator("#submit").click();
  await expect(frame.locator("#report-ok")).toContainText("Signalement enregistré");
  await shot(page, "05-widget");

  await page.goto(`${HOST}/form.html`);
  await page.getByLabel("Sujet").fill("Code promo refusé");
  await page.getByLabel("Message").fill("Le code BIENVENUE est refusé.");
  await page.getByLabel("Email").fill("form@boutique.test");
  await page.waitForTimeout(3_200);
  await page.getByRole("button", { name: "Envoyer" }).click();
  await expect(page.getByRole("status")).toContainText("Signalement transmis. Référence : TCK-");

  // Soumissions abusives depuis la même adresse : bloquées après 5 envois en 10 min.
  let last = "";
  for (let i = 0; i < 3 && !last.includes("Trop de signalements"); i += 1) {
    await page.waitForTimeout(3_200);
    await page.getByLabel("Sujet").fill(`Envoi répété ${i}`);
    await page.getByRole("button", { name: "Envoyer" }).click();
    await expect(page.getByRole("status")).not.toBeEmpty();
    last = (await page.getByRole("status").textContent()) ?? "";
  }
  expect(last).toContain("Trop de signalements");
  await page.context().close();
});

test("7-12 · affectation, priorité, statut, commentaire et pièce jointe, tâche, résolution, clôture", async ({ page }) => {
  await login(page, "pm");
  await page.goto(portal.path);
  await assignTo(page, "Ana E2E");
  await page.locator("#q-priority").selectOption("P2");
  await expect(page.getByText("Ticket qualifié.")).toBeVisible();
  await expect(page.locator("#q-priority")).toHaveValue("P2");
  await page.getByRole("button", { name: "En cours", exact: true }).click();
  await expect(page.getByText("En cours").first()).toBeVisible();
  await page.locator('input[type="file"]').last().setInputFiles({ name: "journal.txt", mimeType: "text/plain", buffer: Buffer.from("trace paiement") });
  await reply(page, "Nous reproduisons le problème.");
  await expect(page.getByText("journal.txt").first()).toBeVisible();
  await page.getByRole("button", { name: /Créer une tâche/ }).click();
  const pick = page.getByRole("dialog");  // application créée sans projet : l'agent choisit le projet
  await pick.locator("#task-project").selectOption({ label: "Portail E2E" });
  await pick.getByRole("button", { name: "Créer la tâche" }).click();
  const taskLink = page.getByRole("link", { name: /Panier vidé au paiement/ }).last();
  await expect(taskLink).toBeVisible();
  const taskPath = (await taskLink.getAttribute("href"))!;

  await login(page, "agent");
  await page.goto(taskPath);
  await page.getByRole("button", { name: "Démarrer" }).click();
  await page.getByRole("button", { name: "Terminer" }).click();
  await expect(page.getByRole("button", { name: "Rouvrir" })).toBeVisible();

  await login(page, "pm");
  await page.goto(portal.path);
  await expect(page.getByText("Résolu").first()).toBeVisible();  // synchronisation tâche → ticket
  await page.getByRole("button", { name: "Clôturé", exact: true }).click();
  await expect(page.getByText("Clôturé").first()).toBeVisible();
  await shot(page, "06-fiche-ticket-cloture");
});

test("13 · notifications, SLA, suivi par le déclarant et accès refusé", async ({ page, browser }) => {
  await login(page, "agent");
  await page.goto("/app/notifications");
  await expect(page.getByText(new RegExp(portal.reference)).first()).toBeVisible();
  await login(page, "pm");
  await page.goto(portal.path);
  await expect(page.getByText("Première réponse")).toBeVisible();
  await expect(page.getByText(/Atteint le|Dépassé/).first()).toBeVisible();

  const visitor = await (await browser.newContext()).newPage();
  await visitor.goto(cfg.hosted);
  await visitor.getByRole("tab", { name: "Suivre un signalement" }).click();
  await visitor.locator("#t-reference").fill(portal.reference);
  await visitor.locator("#t-code").fill("mauvais-code");
  await visitor.getByRole("button", { name: "Consulter" }).click();
  await expect(visitor.locator("#track-error")).toContainText("incorrect");
  await visitor.locator("#t-code").fill(portal.code);
  await visitor.getByRole("button", { name: "Consulter" }).click();
  await expect(visitor.locator("#track-result")).toContainText("Clôturé");
  await expect(visitor.locator("#track-result")).toContainText("Nous reproduisons le problème.");
  await shot(visitor, "07-suivi-declarant");
  await visitor.context().close();

  await login(page, "bob");
  await page.goto(portal.path);
  await expect(page.getByText("Ticket introuvable.")).toBeVisible();
});
