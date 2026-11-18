import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MembersPage } from "@/features/teams/MembersPage";
import { TeamDetailPage } from "@/features/teams/TeamDetailPage";
import { TeamFormPage } from "@/features/teams/FormPages";
import { TeamsPage } from "@/features/teams/TeamsPage";
import { ME, mockApi, renderPage } from "./utils";

const member = (id: number, name: string, extra = {}) => ({
  id, user: { id, name, email: `${name}@a.test`, is_active: true }, team: { id: 3, name: "Core" }, role: "DEVELOPER", role_label: "Développeur",
  status: "ACTIVE", status_label: "Actif", job_title: "", current_load_percent: 40, joined_at: null, manager: "Alice", capacity_hours_per_week: 40, is_owner: false, can_manage: true, can_remove: true, ...extra,
});
const page = (perms: { can_manage_passwords: boolean; can_onboard: boolean; can_manage: boolean }) => ({
  count: 2, next: null, previous: null, permissions: perms,
  results: [member(1, "Alice", { is_owner: true, can_manage: perms.can_manage, can_remove: false }), member(2, "Dan", { can_manage: perms.can_manage, can_remove: perms.can_manage })],
  filters: { teams: [{ value: "3", label: "Core" }], roles: [], statuses: [] },
});

const TEAM = {
  id: 3, name: "Core", team_type: "DEV", team_type_label: "Développement", color: "", is_active: true, is_archived: false,
  velocity_target: 40, velocity_current: 30, lead_name: "Alice", members_count: 4, projects_count: 2,
  description: '<p class="p1">&Eacute;quipe charg&eacute;e du socle technique.</p>',
  description_html: '<p class="p1">Équipe chargée du socle technique.</p><p><strong>Deuxième paragraphe</strong></p>',
  description_text: "Équipe chargée du socle technique.\nDeuxième paragraphe",
};

afterEach(() => vi.restoreAllMocks());

describe("Teams & members", () => {
  it("lists teams with counters and a readable description excerpt", async () => {
    mockApi({ "teams/": { count: 1, next: null, previous: null, results: [TEAM] } });
    renderPage(<TeamsPage />);
    expect(await screen.findByText("Core")).toBeInTheDocument();
    expect(screen.getByText("1 équipe(s)")).toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("4 membre(s)")).toBeInTheDocument();
    expect(screen.getByText("2 projet(s)")).toBeInTheDocument();
    // Texte brut fourni par Django : ni balise ni entité HTML à l'écran.
    expect(screen.getByText(/Équipe chargée du socle/)).toBeInTheDocument();
    expect(screen.queryByText(/<p|&eacute;/)).not.toBeInTheDocument();
  });

  it("renders the sanitized description and hides archive / delete without the rights", async () => {
    mockApi({ "auth/me/": { ...ME, permissions: ["team.view"] }, "teams/3/overview/": { members: [], projects: [] }, "teams/3/": TEAM });
    renderPage(<TeamDetailPage />, "/teams/3", "/teams/:id");
    expect(await screen.findByRole("heading", { name: "Core" })).toBeInTheDocument();
    expect(screen.getByText("Équipe chargée du socle technique.").tagName).toBe("P");
    expect(screen.getByText("Deuxième paragraphe").tagName).toBe("STRONG");
    expect(screen.queryByText(/<p/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Modifier/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Archiver/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Supprimer/ })).not.toBeInTheDocument();
  });

  it("keeps the team colour when the form is saved (no silent switch to black)", async () => {
    const spy = mockApi({
      "auth/me/": ME,
      "POST forms/team/3/": { id: 3, messages: [] },
      "forms/team/3/": { fields: [
        { name: "name", label: "Nom", type: "text", required: true, value: "Core" },
        { name: "description", label: "Description", type: "textarea", value: "Équipe chargée du socle technique." },
        { name: "color", label: "Couleur", type: "color", required: true, value: "#0EA5E9" }] },
    });
    renderPage(<TeamFormPage />, "/teams/3/edit", "/teams/:id/edit");
    const color = await screen.findByLabelText(/Couleur/);
    expect(color).toHaveValue("#0ea5e9");
    expect(screen.getByLabelText("Description")).toHaveValue("Équipe chargée du socle technique.");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    await vi.waitFor(() => {
      const post = spy.mock.calls.find(([u, i]) => String(u).includes("forms/team/3/") && i?.method === "POST");
      expect((post![1]!.body as FormData).get("color")).toBe("#0ea5e9");
    });
  });

  it("shows archive / delete to the workspace owner", async () => {
    mockApi({ "auth/me/": ME, "teams/3/overview/": { members: [], projects: [] }, "teams/3/": TEAM });
    renderPage(<TeamDetailPage />, "/teams/3", "/teams/:id");
    expect(await screen.findByRole("button", { name: /Archiver/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Supprimer/ })).toBeInTheDocument();
  });

  it("offers password reset modes only with the Django permission and never removes the owner", async () => {
    const spy = mockApi({ "auth/me/": ME, "team-members/": page({ can_manage_passwords: true, can_onboard: true, can_manage: true }), "POST actions/member-password-reset/2/": { messages: ["Lien envoyé."] } });
    renderPage(<MembersPage />);
    expect(await screen.findByRole("link", { name: /Intégrer un collaborateur/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retirer Alice" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retirer Dan" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Modifier Dan" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Réinitialiser le mot de passe de Alice" })).not.toBeInTheDocument(); // soi-même
    await userEvent.click(screen.getByRole("button", { name: "Réinitialiser le mot de passe de Dan" }));
    await userEvent.click(screen.getByRole("button", { name: /Envoyer un lien/ }));
    const fd = spy.mock.calls.find(([u]) => String(u).includes("member-password-reset"))![1]!.body as FormData;
    expect(fd.get("mode")).toBe("link");
  });

  it("hides management actions without permissions", async () => {
    mockApi({ "auth/me/": { ...ME, id: 9 }, "team-members/": page({ can_manage_passwords: false, can_onboard: false, can_manage: false }) });
    renderPage(<MembersPage />);
    expect(await screen.findByText("Dan")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Intégrer/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Réinitialiser/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Modifier Dan" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retirer Dan" })).not.toBeInTheDocument();
  });
});
