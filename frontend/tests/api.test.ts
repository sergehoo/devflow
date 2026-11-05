import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/services/api";

afterEach(() => {
  vi.restoreAllMocks();
  document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

function mockFetch(status: number, body: unknown) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  );
}

describe("api client", () => {
  it("sends CSRF token and same-origin credentials on writes", async () => {
    document.cookie = "csrftoken=abc123";
    const fetchMock = mockFetch(200, { ok: true });
    await api("auth/logout/", { method: "POST", body: { a: 1 } });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/v1/auth/logout/");
    expect(init?.credentials).toBe("same-origin");
    expect((init?.headers as Record<string, string>)["X-CSRFToken"]).toBe("abc123");
  });

  it("does not send CSRF on reads and builds query strings", async () => {
    document.cookie = "csrftoken=abc123";
    const fetchMock = mockFetch(200, []);
    await api("tasks/", { params: { search: "api", page: 2, empty: "" } });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/v1/tasks/?search=api&page=2");
    expect((init?.headers as Record<string, string>)["X-CSRFToken"]).toBeUndefined();
  });

  it("raises ApiError with the server message", async () => {
    mockFetch(400, { detail: "Identifiants invalides." });
    await expect(api("auth/login/", { method: "POST", body: {} })).rejects.toMatchObject({
      status: 400, message: "Identifiants invalides.",
    });
    mockFetch(400, { name: ["Ce champ est obligatoire."] });
    await expect(api("projects/", { method: "POST", body: {} })).rejects.toBeInstanceOf(ApiError);
  });
});

describe("actionBody", () => {
  it("n'envoie jamais un multipart vide (rejeté par Django en 400)", async () => {
    const { actionBody } = await import("@/services/api");
    expect([...actionBody().keys()]).toEqual(["next"]);
    expect([...actionBody({ status: "DONE" }).entries()]).toEqual([["status", "DONE"]]);
  });
});
