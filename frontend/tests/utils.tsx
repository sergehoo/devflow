import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";

type Handler = unknown | ((init: RequestInit | undefined, url: string) => unknown);

/** Mock de fetch : la première clé contenue dans l'URL (et la méthode, ex. "POST timesheet/cell") répond. */
export function mockApi(routes: Record<string, Handler>) {
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const method = (init?.method ?? "GET").toUpperCase();
    const entry = Object.entries(routes).find(([key]) => {
      const [m, path] = key.includes(" ") ? key.split(" ") : ["GET", key];
      return m === method && url.includes(path!);
    });
    if (!entry) return new Response(JSON.stringify({ detail: `non mocké: ${method} ${url}` }), { status: 404 });
    const body = typeof entry[1] === "function" ? (entry[1] as (i: RequestInit | undefined, u: string) => unknown)(init, url) : entry[1];
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  });
  return spy;
}

export const ME = {
  id: 1, username: "alice", email: "alice@a.test", first_name: "Alice", last_name: "", full_name: "Alice",
  is_superuser: false, avatar: null, job_title: "",
  workspace: { id: 1, name: "Alpha", role: "WORKSPACE_OWNER", role_label: "Propriétaire" },
  workspaces: [{ id: 1, name: "Alpha" }], permissions: ["*"],
};

export function renderPage(element: ReactElement, path = "/", pattern = "*") {
  const router = createMemoryRouter([{ path: pattern, element }], { initialEntries: [path] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}
