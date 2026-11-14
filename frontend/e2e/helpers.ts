import { execFileSync } from "node:child_process";
import { createHash, createHmac } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { createServer, type Server } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const DJANGO = "http://127.0.0.1:8010";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const STATE = path.resolve(HERE, ".state");

export type Who = "owner" | "pm" | "agent" | "bob";
export interface Fixtures {
  users: Record<Who, { email: string; password: string; id: number }>;
  workspaces: { alpha: number; beta: number }; team: number; project: number;
  app: { id: number; key_id: string; secret: string };
  mailbox: { id: number; inbound_key: string; secret: string; address: string };
}

/** Données créées par `manage.py e2e_fixtures seed` (valeurs de test locales). */
export const fixtures = (): Fixtures => JSON.parse(readFileSync(path.join(STATE, "fixtures.json"), "utf-8")) as Fixtures;

export async function login(page: Page, who: Who) {
  const { email, password } = fixtures().users[who];
  await page.context().clearCookies();
  await page.goto("/app/login");
  await page.getByLabel("Adresse email").fill(email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

const sha256 = (body: string) => createHash("sha256").update(body).digest("hex");
const hmac = (secret: string, message: string) => createHmac("sha256", secret).update(message).digest("hex");

/** Appel serveur à serveur signé HMAC, comme le backend d'une application intégrée. */
export async function integration(request: APIRequestContext, method: "GET" | "POST", urlPath: string, payload?: unknown) {
  const { key_id, secret } = fixtures().app;
  const body = payload === undefined ? "" : JSON.stringify(payload);
  const ts = String(Math.floor(Date.now() / 1000));
  const signature = hmac(secret, `${ts}.${method}.${urlPath.split("?")[0]}.${sha256(body)}`);
  return request.fetch(`${DJANGO}${urlPath}`, {
    method, data: body || undefined,
    headers: { "Content-Type": "application/json", "X-DevFlow-App": key_id, "X-DevFlow-Timestamp": ts, "X-DevFlow-Signature": `sha256=${signature}` },
  });
}

/** E-mail brut (RFC 822) poussé par le « fournisseur » sur le webhook signé de la boîte. */
export async function inboundMail(request: APIRequestContext, raw: string) {
  const { inbound_key, secret } = fixtures().mailbox;
  const ts = String(Math.floor(Date.now() / 1000));
  return request.post(`${DJANGO}/api/v1/integrations/mail/${inbound_key}/`, {
    data: raw, headers: { "Content-Type": "message/rfc822", "X-DevFlow-Timestamp": ts, "X-DevFlow-Signature": `sha256=${hmac(secret, `${ts}.${raw}`)}` },
  });
}

export function rawMail({ from, subject, body, inReplyTo }: { from: string; subject: string; body: string; inReplyTo?: string }) {
  const id = `<${Date.now()}.${Math.random().toString(16).slice(2)}@acme.test>`;
  const headers = [`From: Client Acme <${from}>`, `To: ${fixtures().mailbox.address}`, `Subject: ${subject}`, `Message-ID: ${id}`,
    "MIME-Version: 1.0", "Content-Type: text/plain; charset=utf-8", ...(inReplyTo ? [`In-Reply-To: ${inReplyTo}`, `References: ${inReplyTo}`] : [])];
  return `${headers.join("\r\n")}\r\n\r\n${body}\r\n`;
}

/** E-mails écrits par Django (backend fichier des settings e2e). */
export function sentMails(): string[] {
  const dir = path.join(STATE, "mail");
  try {
    return readdirSync(dir).sort().map((f) => readFileSync(path.join(dir, f), "utf-8"));
  } catch {
    return [];
  }
}

/** Commande Django des tests E2E (horloge SLA…), avec les settings e2e. */
export function manage(...args: string[]) {
  const python = process.env.E2E_PYTHON ?? "./venv/bin/python";
  return execFileSync(python, ["manage.py", "e2e_fixtures", ...args], {
    cwd: ROOT, encoding: "utf-8",
    env: { ...process.env, DJANGO_SETTINGS_MODULE: "ProjectFlow.settings.e2e",
      ...(process.platform === "darwin" ? { DYLD_FALLBACK_LIBRARY_PATH: process.env.DYLD_FALLBACK_LIBRARY_PATH ?? "/opt/homebrew/lib" } : {}) },
  });
}

export interface Hook { event: string; signature: string; timestamp: string; body: string; payload: Record<string, unknown> }

/** Récepteur des webhooks sortants (URL configurée dans l'application de test). */
export function hookReceiver(port = 8099): Promise<{ hooks: Hook[]; close: () => Promise<void> }> {
  const hooks: Hook[] = [];
  const server: Server = createServer((req, res) => {
    let body = "";
    req.on("data", (chunk) => { body += chunk; });
    req.on("end", () => {
      hooks.push({
        event: String(req.headers["x-devflow-event"] ?? ""), signature: String(req.headers["x-devflow-signature"] ?? ""),
        timestamp: String(req.headers["x-devflow-timestamp"] ?? ""), body, payload: JSON.parse(body || "{}") as Record<string, unknown>,
      });
      res.writeHead(200, { "Content-Type": "application/json" }).end("{}");
    });
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve({
    hooks, close: () => new Promise((done) => server.close(() => done())),
  })));
}

/** Vérifie la signature d'un webhook reçu avec le secret de l'application. */
export const validHookSignature = (hook: Hook) => hook.signature === `sha256=${hmac(fixtures().app.secret, `${hook.timestamp}.${hook.body}`)}`;

// ─── Gestes communs des parcours ─────────────────────────────────────────────
export async function openTicket(page: Page, search: string, title: string) {
  await page.goto(`/app/tickets/list?q=${encodeURIComponent(search)}`);
  await page.getByRole("link", { name: title }).first().click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  return new URL(page.url()).pathname;
}

export async function assignTo(page: Page, agent: string) {
  await page.getByRole("button", { name: "Affecter" }).click();
  const assign = page.getByRole("dialog");
  await assign.locator("#assign-team").selectOption({ label: "Support N1" });
  await expect(assign.locator("#assign-agent option", { hasText: agent })).toBeAttached();
  await assign.locator("#assign-agent").selectOption({ label: agent });
  await assign.getByRole("button", { name: "Affecter" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText(agent).first()).toBeVisible();
}

export async function reply(page: Page, text: string, internal = false) {
  if (internal) await page.getByRole("radio", { name: "Note interne" }).click();
  await page.locator("#ticket-comment").fill(text);
  await page.getByRole("button", { name: /Envoyer/ }).click();
  await expect(page.getByText(text).first()).toBeVisible();
  await expect(page.locator("#ticket-comment")).toHaveValue("");  // envoi terminé : le champ est vidé
}

