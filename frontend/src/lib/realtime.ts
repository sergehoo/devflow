/**
 * WebSocket centralisé (Django Channels).
 *
 * - Une seule connexion par chemin (`/ws/me/`, `/ws/channels/<id>/`), partagée par
 *   tous les abonnés (compteur de références) : pas de doublon de socket ni d'événement.
 * - Authentification par le cookie de session HttpOnly envoyé au handshake (même origine) :
 *   aucun jeton côté client.
 * - Reconnexion avec backoff exponentiel + jitter (1 s → 30 s), relancée immédiatement
 *   au retour du réseau ou de l'onglet, et dès qu'un autre flux du même serveur se rouvre ;
 *   abandon sur 4401 / 4403 (non authentifié / interdit).
 * - Socket jamais ouvert depuis 2 min (WebSocket bloqué par un proxy, poignée de main
 *   refusée…) : tentatives espacées jusqu'à 5 min. Un redéploiement (coupure plus courte)
 *   garde le rythme normal. En attendant, les écrans (notifications, liste et fil Messenger)
 *   se rafraîchissent périodiquement tant que leur flux n'est pas « open ».
 * - Heartbeat ping/pong optionnel pour détecter les connexions mortes.
 * - Nettoyage : le dernier désabonnement ferme le socket et annule les timers.
 * Chaque ouverture émet `{ type: "socket.open", reconnected }` ; `reconnected` est vrai
 * après une coupure ou des tentatives échouées, pour que les abonnés resynchronisent leurs
 * caches (événements manqués entre-temps).
 */
import { create } from "zustand";

export type RealtimeStatus = "idle" | "connecting" | "open" | "reconnecting" | "closed";
export interface RealtimeMessage {
  type: string;
  [key: string]: unknown;
}
export type RealtimeHandler = (message: RealtimeMessage) => void;
export interface SubscribeOptions {
  /** Le serveur répond `pong` à `ping` (flux /ws/me/ uniquement). */
  heartbeat?: boolean;
}

const FATAL_CLOSE_CODES = new Set([4401, 4403]);
const HEARTBEAT_MS = 25_000;
const PONG_TIMEOUT_MS = 10_000;
/** Plafond des reconnexions d'un socket qui a déjà fonctionné (coupure, redéploiement). */
export const RETRY_MAX_MS = 30_000;
/** Plafond une fois le flux jugé injoignable : jamais ouvert depuis `UNREACHABLE_AFTER_MS`. */
export const UNREACHABLE_RETRY_MAX_MS = 5 * 60_000;
/** Plus long qu'un redémarrage du serveur (collectstatic + démarrage de gunicorn). */
export const UNREACHABLE_AFTER_MS = 2 * 60_000;

export function backoffDelay(attempt: number, random: () => number = Math.random, max = RETRY_MAX_MS): number {
  const ceiling = Math.min(max, 1_000 * 2 ** attempt);
  return Math.round(ceiling / 2 + (random() * ceiling) / 2);
}

export const useRealtimeStore = create<{ statuses: Record<string, RealtimeStatus> }>(() => ({ statuses: {} }));
export const useRealtimeStatus = (path: string) => useRealtimeStore((s) => s.statuses[path] ?? "idle");

interface HubOptions {
  WebSocketImpl?: typeof WebSocket;
  url?: (path: string) => string;
  random?: () => number;
}

class ManagedSocket {
  private ws: WebSocket | null = null;
  private handlers = new Set<RealtimeHandler>();
  private attempt = 0;
  private everOpened = false;
  /** Début de la série d'échecs en cours (socket jamais ouvert). */
  private failingSince: number | null = null;
  private warnedUnreachable = false;
  private stopped = false;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private pingTimer: ReturnType<typeof setInterval> | undefined;
  private pongTimer: ReturnType<typeof setTimeout> | undefined;

  constructor(
    private readonly path: string,
    private readonly hub: RealtimeHub,
    private readonly heartbeat: boolean,
  ) {}

  get size() {
    return this.handlers.size;
  }

  add(handler: RealtimeHandler) {
    this.handlers.add(handler);
    if (!this.ws && !this.retryTimer) this.open();
  }

  remove(handler: RealtimeHandler) {
    this.handlers.delete(handler);
    if (this.handlers.size === 0) this.dispose();
  }

  send(data: unknown): boolean {
    if (this.ws?.readyState !== 1) return false;
    this.ws.send(JSON.stringify(data));
    return true;
  }

  /** Reconnexion immédiate (retour réseau / onglet visible) si une tentative est en attente. */
  wake() {
    if (this.stopped || this.ws || !this.retryTimer) return;
    clearTimeout(this.retryTimer);
    this.retryTimer = undefined;
    this.open();
  }

  private setStatus(status: RealtimeStatus) {
    useRealtimeStore.setState((s) => ({ statuses: { ...s.statuses, [this.path]: status } }));
  }

  private emit(message: RealtimeMessage) {
    [...this.handlers].forEach((handler) => {
      try {
        handler(message);
      } catch (error) {
        console.error("[realtime] handler", error);
      }
    });
  }

  private open() {
    this.stopped = false;
    this.setStatus(this.everOpened ? "reconnecting" : "connecting");
    const ws = new this.hub.WebSocketImpl(this.hub.url(this.path));
    this.ws = ws;
    ws.onopen = () => {
      // Tentatives échouées avant cette ouverture : des événements ont pu être manqués.
      const reconnected = this.everOpened || this.attempt > 0;
      this.everOpened = true;
      this.attempt = 0;
      this.failingSince = null;
      this.setStatus("open");
      this.startHeartbeat();
      this.emit({ type: "socket.open", reconnected });
      this.hub.wakeAll(); // serveur de nouveau joignable : les autres flux en attente réessaient
    };
    ws.onmessage = (event: MessageEvent) => {
      let message: RealtimeMessage;
      try {
        message = JSON.parse(String(event.data)) as RealtimeMessage;
      } catch {
        return;
      }
      if (message.type === "pong") {
        clearTimeout(this.pongTimer);
        return;
      }
      this.emit(message);
    };
    ws.onerror = () => ws.close();
    ws.onclose = (event: CloseEvent) => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.stopHeartbeat();
      if (this.stopped) return;
      if (FATAL_CLOSE_CODES.has(event.code)) {
        this.setStatus("closed");
        return;
      }
      this.setStatus("reconnecting");
      this.failingSince ??= Date.now();
      const unreachable = !this.everOpened && Date.now() - this.failingSince >= UNREACHABLE_AFTER_MS;
      if (unreachable && !this.warnedUnreachable) {
        this.warnedUnreachable = true;
        console.warn(`[realtime] ${this.path} injoignable : nouvelles tentatives espacées, rafraîchissement périodique en attendant.`);
      }
      const max = unreachable ? UNREACHABLE_RETRY_MAX_MS : RETRY_MAX_MS;
      this.retryTimer = setTimeout(() => {
        this.retryTimer = undefined;
        this.open();
      }, backoffDelay(this.attempt++, this.hub.random, max));
    };
  }

  private startHeartbeat() {
    if (!this.heartbeat) return;
    this.stopHeartbeat();
    this.pingTimer = setInterval(() => {
      if (!this.send({ type: "ping" })) return;
      clearTimeout(this.pongTimer);
      this.pongTimer = setTimeout(() => this.ws?.close(4000, "heartbeat timeout"), PONG_TIMEOUT_MS);
    }, HEARTBEAT_MS);
  }

  private stopHeartbeat() {
    clearInterval(this.pingTimer);
    clearTimeout(this.pongTimer);
    this.pingTimer = this.pongTimer = undefined;
  }

  private dispose() {
    this.stopped = true;
    clearTimeout(this.retryTimer);
    this.retryTimer = undefined;
    this.stopHeartbeat();
    const ws = this.ws;
    this.ws = null;
    if (ws && ws.readyState <= 1) ws.close(1000);
    useRealtimeStore.setState((s) => {
      const statuses = { ...s.statuses };
      delete statuses[this.path];
      return { statuses };
    });
    this.hub.forget(this.path);
  }
}

export class RealtimeHub {
  readonly WebSocketImpl: typeof WebSocket;
  readonly url: (path: string) => string;
  readonly random: () => number;
  private sockets = new Map<string, ManagedSocket>();

  constructor(options: HubOptions = {}) {
    this.WebSocketImpl = options.WebSocketImpl ?? globalThis.WebSocket;
    this.url = options.url ?? ((path) => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`);
    this.random = options.random ?? Math.random;
  }

  subscribe(path: string, handler: RealtimeHandler, options: SubscribeOptions = {}): () => void {
    let socket = this.sockets.get(path);
    if (!socket) {
      socket = new ManagedSocket(path, this, Boolean(options.heartbeat));
      this.sockets.set(path, socket);
    }
    socket.add(handler);
    const current = socket;
    return () => current.remove(handler);
  }

  send(path: string, data: unknown): boolean {
    return this.sockets.get(path)?.send(data) ?? false;
  }

  wakeAll() {
    this.sockets.forEach((socket) => socket.wake());
  }

  connectionCount(): number {
    return this.sockets.size;
  }

  forget(path: string) {
    this.sockets.delete(path);
  }
}

export const realtime = new RealtimeHub();

if (typeof window !== "undefined") {
  window.addEventListener("online", () => realtime.wakeAll());
  document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && realtime.wakeAll());
}
