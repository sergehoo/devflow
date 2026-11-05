import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RealtimeHub, backoffDelay, useRealtimeStore } from "@/lib/realtime";
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
  });
});
