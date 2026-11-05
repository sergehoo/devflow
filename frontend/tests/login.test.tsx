import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { LoginPage } from "@/features/auth/LoginPage";
import { safeNext } from "@/features/auth/safeNext";

function renderLogin() {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ detail: "non authentifié" }), { status: 403, headers: { "content-type": "application/json" } }),
  );
  const router = createMemoryRouter([{ path: "/login", element: <LoginPage /> }], { initialEntries: ["/login"] });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("LoginPage", () => {
  it("validates fields before calling the API", async () => {
    renderLogin();
    await userEvent.click(await screen.findByRole("button", { name: /se connecter/i }));
    expect(await screen.findByText("Saisissez votre adresse email.")).toBeInTheDocument();
    expect(screen.getByText("Saisissez votre mot de passe.")).toBeInTheDocument();
  });

  it("only allows internal redirects", () => {
    expect(safeNext("/projects/12")).toBe("/projects/12");
    expect(safeNext("//evil.test")).toBe("/");
    expect(safeNext("https://evil.test")).toBe("/");
    expect(safeNext(null)).toBe("/");
  });
});
