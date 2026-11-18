import { render, screen } from "@testing-library/react";
import type { ComponentType } from "react";
import { createMemoryRouter, Outlet, RouterProvider, type RouteObject } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { router, withHydrateFallback } from "@/app/router";

const HYDRATE_WARNING = "No `HydrateFallback` element provided";

function deferredPage() {
  let resolve!: (Component: ComponentType) => void;
  const lazy = () => new Promise<{ Component: ComponentType }>((done) => { resolve = (Component) => done({ Component }); });
  return { lazy, resolve: (Component: ComponentType) => resolve(Component) };
}

const Loading = () => <p>Chargement de l'écran</p>;
const Page = () => <h1>Écran chargé</h1>;
const Shell = () => <div><span>Coque</span><Outlet /></div>;

describe("premier chargement des écrans découpés", () => {
  it("donne un écran d'attente à chaque route lazy de l'application", () => {
    const missing: string[] = [];
    let lazyRoutes = 0;
    const walk = (routes: RouteObject[], parent = "") => routes.forEach((route) => {
      const path = `${parent}/${route.path ?? (route.index ? "(index)" : "")}`;
      if (route.lazy) lazyRoutes += 1;
      if (route.lazy && !route.HydrateFallback && !route.hydrateFallbackElement) missing.push(path);
      if (route.children) walk(route.children, path);
    });
    walk(router.routes as RouteObject[]);
    expect(lazyRoutes).toBeGreaterThan(20);
    expect(missing).toEqual([]);
  });

  it("garde la coque et affiche l'attente au lieu d'une page blanche, sans avertissement", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const page = deferredPage();
    const memory = createMemoryRouter(
      withHydrateFallback([{ path: "/", Component: Shell, children: [{ path: "projects", lazy: page.lazy }] }], Loading),
      { initialEntries: ["/projects"] },
    );
    render(<RouterProvider router={memory} />);
    expect(screen.getByText("Coque")).toBeInTheDocument();
    expect(screen.getByText("Chargement de l'écran")).toBeInTheDocument();
    page.resolve(Page);
    expect(await screen.findByRole("heading", { name: "Écran chargé" })).toBeInTheDocument();
    expect(warn.mock.calls.flat().join(" ")).not.toContain(HYDRATE_WARNING);

    // Témoin : sans écran d'attente, React Router rend une page blanche et avertit.
    const bare = deferredPage();
    const { container } = render(<RouterProvider router={createMemoryRouter([{ path: "/", lazy: bare.lazy }])} />);
    expect(container).toBeEmptyDOMElement();
    expect(warn.mock.calls.flat().join(" ")).toContain(HYDRATE_WARNING);
    warn.mockRestore();
  });

  it("ne remplace pas un écran d'attente déjà déclaré", () => {
    const Own = () => null;
    const [route] = withHydrateFallback([{ path: "/login", HydrateFallback: Own, lazy: async () => ({ Component: Page }) }], Loading);
    expect(route!.HydrateFallback).toBe(Own);
  });
});
