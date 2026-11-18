import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RealtimeHub, UNREACHABLE_AFTER_MS, backoffDelay, useRealtimeStore } from "@/lib/realtime";
import { FakeWebSocket } from "./fakeSocket";

const hub = () => new RealtimeHub({ WebSocketImpl: FakeWebSocket as unknown as typeof WebSocket, url: (p) => `ws://test${p}`, random: () => 0 });
const last = () => FakeWebSocket.instances[FakeWebSocket.instances.length - 1]!;

describe("RealtimeHub", () => {
  beforeEach(() => { vi.useFakeTimers(); FakeWebSocket.reset(); });
  afterEach(() => vi.useRealTimers());

  it("shares one socket per path and fans out events without duplicates", () => {
    const h = hub();
    const a = vi.fn(), b = vi.fn();
    const offA = h.subscribe("/ws/me/", a);
    h.subscribe("/ws/me/", b);
    expect(FakeWebSocket.instances).toHaveLength(1);
    last().open();
    last().receive({ type: "notification", notification: { id: 1 } });
    expect(a).toHaveBeenCalledWith({ type: "notification", notification: { id: 1 } });
    expect(b).toHaveBeenCalledTimes(2); // socket.open + notification
    offA();
    last().receive({ type: "x" });
    expect(a).toHaveBeenCalledTimes(2);
  });

  it("reconnects with exponential backoff and signals the resync", () => {
    const h = hub();
    const handler = vi.fn();
    h.subscribe("/ws/me/", handler);
    last().open();
    last().drop();
    expect(useRealtimeStore.getState().statuses["/ws/me/"]).toBe("reconnecting");
    vi.advanceTimersByTime(499);
    expect(FakeWebSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(2);
    last().drop();
    vi.advanceTimersByTime(999); // 2e tentative : 1 s (random = 0 → moitié du plafond 2 s)
    expect(FakeWebSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    last().open();
    expect(handler).toHaveBeenLastCalledWith({ type: "socket.open", reconnected: true });
    expect(useRealtimeStore.getState().statuses["/ws/me/"]).toBe("open");
  });

  it("stops retrying on 4401/4403", () => {
    const h = hub();
    h.subscribe("/ws/me/", vi.fn());
    last().drop(4401);
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(useRealtimeStore.getState().statuses["/ws/me/"]).toBe("closed");
  });

  it("cleans up socket and timers when the last subscriber leaves", () => {
    const h = hub();
    const off = h.subscribe("/ws/channels/3/", vi.fn());
    last().drop();
    off();
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(h.connectionCount()).toBe(0);
    expect(useRealtimeStore.getState().statuses["/ws/channels/3/"]).toBeUndefined();
  });

  it("detects dead connections with ping/pong heartbeat", () => {
    const h = hub();
    h.subscribe("/ws/me/", vi.fn(), { heartbeat: true });
    last().open();
    vi.advanceTimersByTime(25_000);
    expect(last().sent).toEqual([{ type: "ping" }]);
    last().receive({ type: "pong" });
    vi.advanceTimersByTime(25_000 + 10_000);
    expect(FakeWebSocket.instances).toHaveLength(1); // pong reçu puis 2e ping sans réponse → coupure
    expect(last().readyState).toBe(3);
  });

  it("caps backoff at 30 s", () => {
    expect(backoffDelay(0, () => 1)).toBe(1000);
    expect(backoffDelay(10, () => 0)).toBe(15_000);
    expect(backoffDelay(10, () => 1)).toBe(30_000);
    expect(backoffDelay(10, () => 1, 300_000)).toBe(300_000);
  });

  /** Coupe le socket courant et mesure (au pas de 500 ms, random = 0) le délai avant la tentative suivante. */
  function failAndMeasure(path = "/ws/me/"): number {
    const sockets = () => FakeWebSocket.instances.filter((ws) => ws.url.endsWith(path));
    const before = sockets().length;
    sockets()[before - 1]!.drop();
    let waited = 0;
    while (sockets().length === before) {
      vi.advanceTimersByTime(500);
      waited += 500;
    }
    return waited;
  }

  it("spaces out retries only after 2 min without ever opening (blocked WebSocket)", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    hub().subscribe("/ws/me/", vi.fn());
    const delays: number[] = [];
    let elapsed = 0;
    while (elapsed < UNREACHABLE_AFTER_MS) {
      const delay = failAndMeasure();
      delays.push(delay);
      elapsed += delay;
    }
    // Rythme normal pendant 2 min : 0,5 s, 1 s, 2 s, 4 s, 8 s puis 15 s (plafond 30 s, random = 0).
    expect(delays.slice(0, 6)).toEqual([500, 1000, 2000, 4000, 8000, 15_000]);
    expect(Math.max(...delays)).toBe(15_000);
    expect(warn).not.toHaveBeenCalled();
    // Au-delà, plafond de 5 min (150 s avec random = 0) et un seul avertissement.
    expect(failAndMeasure()).toBe(150_000);
    expect(failAndMeasure()).toBe(150_000);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn.mock.calls[0]![0]).toContain("/ws/me/ injoignable");
    expect(useRealtimeStore.getState().statuses["/ws/me/"]).toBe("connecting"); // jamais abandonné
    warn.mockRestore();
  });

  it("keeps the normal pace through a deploy outage at page load, then resyncs", () => {
    const handler = vi.fn();
    hub().subscribe("/ws/me/", handler);
    let elapsed = 0;
    while (elapsed < 90_000) elapsed += failAndMeasure(); // serveur redémarré en 1 min 30
    expect(failAndMeasure()).toBe(15_000); // toujours le plafond de 30 s
    last().open();
    // Jamais ouvert auparavant, mais des tentatives ont échoué : événements manqués → resynchronisation.
    expect(handler).toHaveBeenLastCalledWith({ type: "socket.open", reconnected: true });
  });

  it("announces a first open without failures as a fresh connection", () => {
    const handler = vi.fn();
    hub().subscribe("/ws/me/", handler);
    last().open();
    expect(handler).toHaveBeenLastCalledWith({ type: "socket.open", reconnected: false });
  });

  it("wakes the other waiting sockets as soon as one reopens", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const h = hub();
    const sockets = (path: string) => FakeWebSocket.instances.filter((ws) => ws.url.endsWith(path));
    h.subscribe("/ws/me/", vi.fn());
    sockets("/ws/me/").at(-1)!.open();
    h.subscribe("/ws/channels/9/", vi.fn()); // fil ouvert pendant une longue coupure
    sockets("/ws/me/").at(-1)!.drop();
    let elapsed = 0;
    while (elapsed < UNREACHABLE_AFTER_MS + 30_000) elapsed += failAndMeasure("/ws/channels/9/");
    const pending = sockets("/ws/channels/9/").length;
    sockets("/ws/channels/9/").at(-1)!.drop(); // le fil attendrait maintenant 150 s
    vi.advanceTimersByTime(1000);
    expect(sockets("/ws/channels/9/")).toHaveLength(pending);
    sockets("/ws/me/").at(-1)!.open(); // le serveur répond de nouveau
    expect(sockets("/ws/channels/9/")).toHaveLength(pending + 1); // nouvel essai immédiat
    warn.mockRestore();
  });

  it("keeps fast reconnection for a socket that worked before", () => {
    hub().subscribe("/ws/me/", vi.fn());
    last().open();
    let elapsed = 0;
    const delays: number[] = [];
    while (elapsed < 2 * UNREACHABLE_AFTER_MS) {
      const delay = failAndMeasure();
      delays.push(delay);
      elapsed += delay;
    }
    expect(Math.max(...delays)).toBe(15_000); // plafond 30 s inchangé, même après 4 min
  });

  it("retries at once when the tab comes back, even in slow mode", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const h = hub();
    h.subscribe("/ws/me/", vi.fn());
    let elapsed = 0;
    while (elapsed < UNREACHABLE_AFTER_MS) elapsed += failAndMeasure();
    const before = FakeWebSocket.instances.length;
    last().drop(); // prochaine tentative dans 150 s…
    h.wakeAll(); // …mais l'onglet redevient visible : essai immédiat
    expect(FakeWebSocket.instances).toHaveLength(before + 1);
    last().open();
    expect(useRealtimeStore.getState().statuses["/ws/me/"]).toBe("open");
    warn.mockRestore();
  });
});
