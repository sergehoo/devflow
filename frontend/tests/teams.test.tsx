import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MembersPage } from "@/features/teams/MembersPage";
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

afterEach(() => vi.restoreAllMocks());

describe("Teams & members", () => {
  it("lists teams with counters", async () => {
    mockApi({ "teams/": { count: 1, next: null, previous: null, results: [{ id: 3, name: "Core", team_type: "DEV", team_type_label: "Développement", description: "", color: "", is_active: true, is_archived: false, velocity_target: 0, velocity_current: 0, lead_name: "Alice", members_count: 4, projects_count: 2 }] } });
    renderPage(<TeamsPage />);
    expect(await screen.findByText("Lead : Alice · 4 membre(s) · 2 projet(s)")).toBeInTheDocument();
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
