import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkspaceDetailPage } from "@/features/workspaces/WorkspaceDetailPage";
import { WorkspaceFormPage } from "@/features/workspaces/WorkspaceFormPage";
import { WorkspacesPage } from "@/features/workspaces/WorkspacesPage";
import { mockApi, renderPage } from "./utils";

const WS = {
  id: 3, name: "Alpha", slug: "alpha", is_archived: false, created_at: "", description: "Siège", logo: null, owner: 1,
  owner_name: "Alice", is_active: true, timezone: "Africa/Abidjan", quarter_label: "T4 2026", legal_name: "Alpha SA",
  tagline: "", legal_rccm: "", legal_cc: "", legal_tax_id: "", address_line1: "", address_line2: "", postal_code: "",
  city: "Abidjan", country: "", phone: "", website: "", email: "", bank_details: "", invoice_footer_text: "",
  accent_color: "#F4722B", teams_count: 2, projects_count: 5, memberships_count: 9, can_manage: false, can_delete: false,
};

afterEach(() => vi.restoreAllMocks());

describe("Workspaces", () => {
  it("lists workspaces with counters", async () => {
    mockApi({ "workspaces/": { count: 1, next: null, previous: null, results: [WS] } });
    renderPage(<WorkspacesPage />);
    expect(await screen.findByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Alice · T4 2026")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
  });

  it("hides management actions when the API denies them", async () => {
    mockApi({ "workspaces/3/overview/": { teams: [], projects: [], members: [] }, "workspaces/3/": WS });
    renderPage(<WorkspaceDetailPage />, "/workspaces/3", "/workspaces/:id");
    expect(await screen.findByRole("heading", { name: "Alpha" })).toBeInTheDocument();
    expect(screen.getByText("Alpha SA")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Modifier/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Supprimer/ })).not.toBeInTheDocument();
  });

  it("validates the create form before calling the API", async () => {
    const spy = mockApi({});
    renderPage(<WorkspaceFormPage />, "/workspaces/new");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    expect(await screen.findByText("Le nom est obligatoire.")).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalledWith(expect.stringContaining("workspaces/"), expect.objectContaining({ method: "POST" }));
  });
});
