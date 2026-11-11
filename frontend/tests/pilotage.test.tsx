import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import type { ImportAnalysis, ImportDecisions, ImportDetail, TrackingBoard, TrackingRow } from "@/features/pilotage/api";
import { ambiguityValue, chosen, planOf, withPatch } from "@/features/pilotage/decisions";
import { ExportTrackingButton } from "@/features/pilotage/ExportTrackingButton";
import { PilotagePage } from "@/features/pilotage/PilotagePage";
import { ProjectTrackingSummary } from "@/features/pilotage/ProjectTrackingSummary";
import { TrackingImportsPage, TrackingImportWizardPage } from "@/features/pilotage/TrackingImportPage";
import { ME, mockApi, renderPage } from "./utils";

// ---------------------------------------------------------------------------
// Données de test (fictives)
// ---------------------------------------------------------------------------
const ROW: TrackingRow = {
  id: "project-7", kind: "project", pk: 7, workspace: { id: 1, name: "Alpha" }, project: { id: 7, name: "Portail Fournisseurs" },
  title: "Portail Fournisseurs", companies: ["ACME"], owners: [{ name: "Awa Koné", user_id: 4 }], contacts: ["Direction achats"],
  progress: 40, status: "IN_PROGRESS", status_label: "En cours", status_key: "en_cours", sheet_status: "En cours",
  start: "2026-01-05", end: "2026-03-31", late: true, days_late: 12, due_soon: false, stale: false,
  done: [{ text: "Cadrage validé", date: "2026-01-20", source: "log" }], done_count: 1,
  next: [{ id: 31, text: "Recette des écrans", due: "2026-04-10", status: "TODO", late: false }], next_count: 1,
  alerts: [{ id: 9, type: "risk", kind: "BLOCKER", kind_label: "Blocage", severity: "HIGH", severity_label: "Élevé", text: "En attente du capteur" }],
  blocked: true, pending_decisions: 0, updated_at: "2026-04-01T10:00:00Z", url: "/projects/7",
};

const BOARD: TrackingBoard = {
  rows: [ROW], count: 1, total: 3,
  kpis: {
    projects_total: 3, projects_active: 2, projects_done: 1, projects_suspended: 0, projects_late: 1, due_soon: 1, progress_avg: 55,
    projects_blocked: 1, pending_decisions: 2, tasks_open: 6, tasks_late: 1, activities_total: 4,
  },
  charts: {
    by_company: [{ label: "ACME", value: 2 }], by_status: [{ key: "en_cours", label: "En cours", value: 2 }],
    progress: [{ label: "1 à 49 %", value: 1 }], deadlines: [{ label: "En retard", value: 1 }],
    workload: [{ label: "Awa Koné", projects: 1, tasks: 2 }], alerts: [{ key: "HIGH", label: "Élevé", value: 1 }],
  },
  options: {
    companies: ["ACME", "Beta SA"], owners: [{ value: "u:4", label: "Awa Koné" }], projects: [{ value: "7", label: "Portail Fournisseurs" }],
    workspaces: [{ value: "1", label: "Alpha" }],
    statuses: [{ value: "en_cours", label: "En cours" }, { value: "suspendu", label: "Suspendu" }],
    alerts: [{ value: "any", label: "Avec alerte" }],
  },
  filters: ["Entreprise : ACME"], scope: { label: "tous les projets de Alpha", restricted: false }, can_import: true,
  generated_at: "2026-04-12T08:00:00Z",
};

const BRIEF = { generated_at: "2026-04-12T08:00:00Z", facts: [{ kind: "blocked", text: "1 projet bloqué : Portail Fournisseurs.", rows: ["project-7"] }], text: "", source: "rules" };

const ANALYSIS: ImportAnalysis = {
  analyzed_at: "2026-04-12T08:00:00Z",
  sections: [
    { kind: "projects", sheet: "PROJET", title: "SUIVI DES PROJETS", header_row: 3, first_row: 4, last_row: 4, rows: 1 },
    { kind: "tasks", sheet: "PROJET", title: "SUIVI DES TACHES", header_row: 9, first_row: 10, last_row: 10, rows: 1 },
  ],
  rows: [
    {
      id: "projects:4", section: "projects", row: 4, title: "Portail Fournisseurs", companies: ["ACME"], owners: ["Awa Koné"], contacts: [],
      done: [{ id: "projects:4:done:0", text: "Cadrage validé" }],
      next: [{ id: "projects:4:next:0", text: "Recette des écrans", due: null, match: null, default: { action: "create", target_id: null } }],
      alerts: [{ id: "projects:4:alert:0", text: "En attente du capteur", kind: "DEPENDENCY", severity: "MEDIUM", match: null,
        default: { action: "create", target_id: null, kind: "DEPENDENCY", severity: "MEDIUM" } }],
      start: "2026-01-05", end: null, progress: 1, progress_raw: "1", status_raw: "En cours", status_key: "en_cours",
      raw: { title: "Portail Fournisseurs", done: "Cadrage validé", progress: "1" }, warnings: [], match: null,
      default: { action: "create", target_id: null },
    },
    {
      id: "tasks:10", section: "tasks", row: 10, title: "Veille technique", companies: ["ACME"], owners: ["Inconnu Test"], contacts: [],
      done: [], next: [{ id: "tasks:10:next:0", text: "Synthèse mensuelle", due: null, match: null, default: { action: "create", target_id: null } }],
      alerts: [], start: null, end: null, progress: null, progress_raw: "", status_raw: "suspendu", status_key: "suspendu",
      raw: { title: "Veille technique" }, warnings: [], match: null, default: { action: "create", target_id: null, project_id: null },
    },
  ],
  companies: [{ key: "acme", name: "ACME", rows: ["projects:4", "tasks:10"], ambiguous: false, match: null, default: { action: "create", label_id: null } }],
  people: [
    { key: "awa kone", name: "Awa Koné", roles: ["PORTEUR"], rows: ["projects:4"], match: { id: 4, name: "Awa Koné" }, candidates: [{ id: 4, name: "Awa Koné" }], unresolved: false, default: { user_id: 4 } },
    { key: "inconnu test", name: "Inconnu Test", roles: ["PORTEUR"], rows: ["tasks:10"], match: null, candidates: [], unresolved: true, default: { user_id: null } },
  ],
  statuses: [{ key: "en cours", raw: "En cours", known: "en_cours", rows: 1, default: { project: "IN_PROGRESS", task: "IN_PROGRESS" } }],
  container: { default: { mode: "create", project_id: null, name: "Activités Pôle Développement" } },
  ambiguities: [{
    id: "projects:4:progress", row: "projects:4", line: 4, field: "progress", message: "Avancement « 1 » : 1 % ou 100 % ?",
    options: [{ value: 1, label: "Conserver 1 %" }, { value: 100, label: "Appliquer 100 %" }], default: 1, suggestion: 100,
  }],
  warnings: [], unresolved_members: ["Inconnu Test"],
  stats: { projects: 1, tasks: 1, actions_done: 1, actions_next: 2, alerts: 1, companies: 1, people: 2, unresolved_people: 1, ambiguities: 1, warnings: 0 },
};

const DETAIL: ImportDetail = {
  id: 5, file_name: "suivi.xlsx", workspace: { id: 1, name: "Alpha" }, uploaded_by: "Alice", created_at: "2026-04-12T08:00:00Z",
  state: "analyzed", stats: ANALYSIS.stats, applied_at: null, applied_by: null, rolled_back_at: null, rolled_back_by: null,
  analysis: ANALYSIS, decisions: null, report: null, rollback: null,
  options: {
    users: [{ id: 4, name: "Awa Koné" }, { id: 8, name: "Bintou Diallo" }], projects: [{ id: 7, name: "Portail Fournisseurs", container: false }],
    labels: [{ id: 2, name: "ACME Groupe", kind: "COMPANY" }],
    project_statuses: [{ value: "IN_PROGRESS", label: "En cours" }], task_statuses: [{ value: "IN_PROGRESS", label: "En cours" }],
    alert_kinds: [{ value: "DEPENDENCY", label: "Dépendance" }, { value: "DECISION", label: "Décision" }],
    severities: [{ value: "MEDIUM", label: "Moyen" }, { value: "HIGH", label: "Élevé" }],
  },
};

const APPLIED: ImportDetail = {
  ...DETAIL, state: "applied", applied_at: "2026-04-12T09:00:00Z", applied_by: { id: 1, name: "Alice" }, decisions: {},
  report: { counts: { project: { created: 1 }, task: { created: 2 }, alert: { created: 1 } }, unresolved_members: ["Inconnu Test"],
    ambiguities_kept: ["Avancement « 1 » : 1 % ou 100 % ?"], warnings: 0, records: 9 },
};

const RECORDS = { count: 1, page: 1, num_pages: 1, results: [
  { id: 1, section: "projects", row: 4, field: "project", index: 0, text: "Portail Fournisseurs", action: "created", action_label: "Créé", target_model: "Project", target_id: 7, rolled_back: false },
] };

const body = (init: RequestInit | undefined) => JSON.parse(String(init?.body ?? "{}")) as { decisions?: ImportDecisions };
const calls = (spy: ReturnType<typeof mockApi>, part: string) => spy.mock.calls.map(([input]) => String(input)).filter((u) => u.includes(part));

afterEach(() => { vi.restoreAllMocks(); });

// ---------------------------------------------------------------------------
describe("Pilotage › Suivi Pôle Développement", () => {
  it("affiche les indicateurs, le périmètre et les lignes consolidées", async () => {
    mockApi({ "auth/me/": ME, "tracking/board/": BOARD, "tracking/brief/": BRIEF });
    renderPage(<PilotagePage />, "/pilotage/suivi");
    expect(await screen.findByRole("heading", { name: "Suivi Pôle Développement" })).toBeInTheDocument();
    expect(screen.getByText(/tous les projets de Alpha · 1 ligne\(s\) sur 3/)).toBeInTheDocument();
    const kpis = screen.getByRole("region", { name: "Indicateurs clés" });
    ["Projets actifs", "Réalisés", "Suspendus", "En retard", "Échéances proches", "Avancement moyen", "Projets bloqués",
      "Décisions en attente", "Tâches ouvertes", "Tâches en retard"].forEach((label) => expect(within(kpis).getByText(label)).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Portail Fournisseurs" })).toHaveAttribute("href", "/projects/7");
    expect(screen.getByRole("link", { name: /Importer le suivi/ })).toHaveAttribute("href", "/imports/tracking");
    expect(await screen.findByText("1 projet bloqué : Portail Fournisseurs.")).toBeInTheDocument();
    expect(screen.queryByText("En attente du capteur")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Afficher le détail de Portail Fournisseurs" }));
    expect(screen.getAllByText("Cadrage validé")).toHaveLength(2);
    expect(screen.getByText("En attente du capteur")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Recette des écrans" })).toHaveAttribute("href", "/tasks/31");
  });

  it("transmet les filtres actifs à l'API et à l'export Excel", async () => {
    const spy = mockApi({ "auth/me/": ME, "tracking/board/": BOARD, "tracking/brief/": BRIEF });
    renderPage(<PilotagePage />, "/pilotage/suivi?company=ACME&status=suspendu");
    await screen.findByRole("heading", { name: "Suivi Pôle Développement" });
    expect(calls(spy, "tracking/board/")[0]).toMatch(/company=ACME/);
    expect(calls(spy, "tracking/board/")[0]).toMatch(/status=suspendu/);
    fireEvent.click(screen.getByRole("button", { name: /Exporter le suivi Excel/ }));
    await waitFor(() => expect(calls(spy, "tracking/export/").length).toBe(1));
    const url = new URL(calls(spy, "tracking/export/")[0]!, "http://devflow.local");
    expect(url.searchParams.get("fmt")).toBe("xlsx");
    expect(url.searchParams.get("company")).toBe("ACME");
    expect(url.searchParams.get("status")).toBe("suspendu");
  });

  it("masque l'import à qui n'en a pas le droit et signale un suivi vide", async () => {
    mockApi({ "auth/me/": { ...ME, permissions: ["task.view_assigned"] }, "tracking/brief/": { ...BRIEF, facts: [] },
      "tracking/board/": { ...BOARD, rows: [], count: 0, total: 0, filters: [], can_import: false, scope: { label: "vos projets et tâches de Alpha", restricted: true } } });
    renderPage(<PilotagePage />, "/pilotage/suivi");
    expect(await screen.findByText("Aucun projet suivi pour l'instant")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Importer le suivi/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Exporter le suivi Excel/ })).toBeInTheDocument();
  });
});

describe("Bouton « Exporter le suivi Excel »", () => {
  it("reste masqué (mode restreint) sans droit de consulter le suivi", async () => {
    const spy = mockApi({ "auth/me/": { ...ME, permissions: ["ticket.view"] } });
    renderPage(<ExportTrackingButton gated />);
    await waitFor(() => expect(calls(spy, "auth/me/").length).toBe(1));
    await waitFor(() => expect(screen.queryByRole("button", { name: /Exporter le suivi Excel/ })).not.toBeInTheDocument());
  });

  it("s'affiche pour un membre qui voit ses tâches", async () => {
    mockApi({ "auth/me/": { ...ME, permissions: ["task.view_assigned"] } });
    renderPage(<ExportTrackingButton gated />);
    expect(await screen.findByRole("button", { name: /Exporter le suivi Excel/ })).toBeInTheDocument();
  });
});

describe("Fiche projet › synthèse de suivi", () => {
  it("reprend progression, échéance, porteur, actions et alertes", async () => {
    mockApi({ "tracking/projects/7/": { row: ROW, activities: [], recent: [{ id: 1, title: "Projet mis à jour", actor: "Alice", type: "PROJECT_UPDATED", created_at: "2026-04-01T10:00:00Z" }] } });
    renderPage(<ProjectTrackingSummary projectId={7} />);
    expect(await screen.findByText("Synthèse de suivi")).toBeInTheDocument();
    expect(screen.getByText("12 j de retard")).toBeInTheDocument();
    expect(screen.getByText("Awa Koné")).toBeInTheDocument();
    expect(screen.getByText("Recette des écrans")).toBeInTheDocument();
    expect(screen.getByText("Projet mis à jour")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ouvrir dans le suivi" })).toHaveAttribute("href", "/pilotage/suivi?project=7");
  });

  it("reste masquée si le projet n'est pas visible dans le suivi (404)", async () => {
    const spy = mockApi({});
    const { container } = renderPage(<ProjectTrackingSummary projectId={7} />);
    await waitFor(() => expect(calls(spy, "tracking/projects/7/").length).toBeGreaterThan(0));
    expect(container).toBeEmptyDOMElement();
  });
});

// ---------------------------------------------------------------------------
describe("Décisions de l'assistant d'import", () => {
  it("fusionne un choix partiel sans perdre la proposition de l'analyse", () => {
    const alert = ANALYSIS.rows[0]!.alerts[0]!;
    const d = withPatch({}, "alerts", alert.id, { severity: "HIGH" });
    expect(chosen(d, "alerts", alert.id, alert.default)).toEqual({ action: "create", target_id: null, kind: "DEPENDENCY", severity: "HIGH" });
    expect(withPatch(d, "alerts", alert.id, { kind: "DECISION" }).alerts?.[alert.id]).toEqual({ severity: "HIGH", kind: "DECISION" });
  });

  it("garde la valeur du fichier tant que l'ambiguïté n'est pas tranchée (null compris)", () => {
    const a = ANALYSIS.ambiguities[0]!;
    expect(ambiguityValue({}, a)).toBe(1);
    expect(ambiguityValue({ ambiguities: { [a.id]: 100 } }, a)).toBe(100);
    expect(ambiguityValue({ ambiguities: { "x:end": null } }, { ...a, id: "x:end", default: "2026-03-04" })).toBeNull();
  });

  it("récapitule l'import : lignes ignorées, porteurs non résolus, ambiguïtés conservées", () => {
    const plan = planOf(ANALYSIS, {});
    expect(plan.projects.create).toBe(1);
    expect(plan.tasks.create).toBe(1);
    expect(plan.items.create).toBe(2);
    expect(plan.alerts.create).toBe(1);
    expect(plan.unresolved).toEqual(["Inconnu Test"]);
    expect(plan.ambiguitiesKept).toBe(1);
    const skipped = planOf(ANALYSIS, {
      rows: { "projects:4": { action: "skip" } }, people: { "inconnu test": { user_id: 8 } }, ambiguities: { "projects:4:progress": 100 },
    });
    expect(skipped.projects).toMatchObject({ create: 0, skip: 1 });
    expect(skipped.items.create).toBe(1);
    expect(skipped.alerts.create).toBe(0);
    expect(skipped.unresolved).toEqual([]);
    expect(skipped.ambiguitiesKept).toBe(0);
  });
});

describe("Assistant d'import du suivi", () => {
  const wizard = () => renderPage(<TrackingImportWizardPage />, "/imports/tracking/5", "/imports/tracking/:id");

  it("dépose le classeur puis ouvre l'assistant", async () => {
    const spy = mockApi({ "POST tracking/imports/": DETAIL, "tracking/imports/": { results: [], workspaces: [{ id: 1, name: "Alpha" }] } });
    renderPage(<TrackingImportsPage />, "/imports/tracking");
    const input = await screen.findByLabelText("Classeur de suivi (.xlsx)");
    const submit = screen.getByRole("button", { name: /Analyser le classeur/ });
    expect(submit).toBeDisabled();
    fireEvent.change(input, { target: { files: [new File(["x"], "suivi.xlsx")] } });
    expect(submit).toBeEnabled();
    // jsdom ne lève pas `required` sur un fichier injecté : on soumet le formulaire directement.
    fireEvent.submit(submit.closest("form")!);
    await waitFor(() => expect(spy.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true));
    const sent = spy.mock.calls.find(([, init]) => init?.method === "POST")![1]!.body as FormData;
    expect(sent.get("workspace")).toBe("1");
    expect((sent.get("file") as File).name).toBe("suivi.xlsx");
  });

  it("présente l'analyse (2 blocs) sans rien corriger d'office", async () => {
    mockApi({ "tracking/imports/5/": DETAIL });
    wizard();
    expect(await screen.findByText("Blocs détectés")).toBeInTheDocument();
    const blocks = screen.getByRole("table", { name: "Blocs détectés dans le classeur" });
    expect(within(blocks).getByText("Projets")).toBeInTheDocument();
    expect(within(blocks).getByText("Tâches / activités")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Prévisualisation/ }));
    expect(screen.getByText("1 %")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Mapping/ }));
    expect(screen.getByLabelText("Choix pour : Avancement « 1 » : 1 % ou 100 % ?")).toHaveValue("1");
    expect(screen.getByText("Non résolu")).toBeInTheDocument();
    expect(screen.getByLabelText("Utilisateur DevFlow pour Inconnu Test")).toHaveValue("");
  });

  it("n'envoie que les décisions prises, puis affiche le rapport", async () => {
    const spy = mockApi({ "POST tracking/imports/5/apply/": APPLIED, "tracking/imports/5/records/": RECORDS, "tracking/imports/5/": DETAIL });
    wizard();
    await screen.findByText("Blocs détectés");
    fireEvent.click(screen.getByRole("button", { name: /Mapping/ }));
    fireEvent.change(screen.getByLabelText("Utilisateur DevFlow pour Inconnu Test"), { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText("Décision pour la ligne 10"), { target: { value: "skip" } });
    fireEvent.click(screen.getByRole("button", { name: /^5\s*Import$/ }));
    expect(screen.getByText("Tous les porteurs sont rapprochés d'un utilisateur DevFlow.")).toBeInTheDocument();
    expect(screen.getByText(/1 donnée\(s\) ambiguë\(s\) conservée\(s\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Lancer l'import/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Importer" }));
    await waitFor(() => expect(spy.mock.calls.some(([input]) => String(input).includes("/apply/"))).toBe(true));
    const sent = body(spy.mock.calls.find(([input]) => String(input).includes("/apply/"))![1]);
    expect(sent.decisions).toEqual({ people: { "inconnu test": { user_id: 8 } }, rows: { "tasks:10": { action: "skip" } } });
    expect(await screen.findByText(/9 opération\(s\) tracée\(s\)/)).toBeInTheDocument();
    expect(screen.getByText(/Porteurs non résolus \(aucun compte créé\) : Inconnu Test/)).toBeInTheDocument();
    expect(await screen.findByRole("table", { name: "Journal d'audit de l'import" })).toBeInTheDocument();
  });

  it("fige le mapping d'un import appliqué et permet de l'annuler", async () => {
    const spy = mockApi({
      "POST tracking/imports/5/rollback/": { ...APPLIED, state: "rolled_back", rolled_back_at: "2026-04-12T10:00:00Z", rolled_back_by: { id: 1, name: "Alice" }, rollback: { archived: 3, removed: 4, restored: 0 } },
      "tracking/imports/5/records/": RECORDS, "tracking/imports/5/": APPLIED,
    });
    wizard();
    expect(await screen.findByText(/9 opération\(s\) tracée\(s\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Mapping/ }));
    expect(screen.getByLabelText("Décision pour la ligne 4")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Rapport/ }));
    fireEvent.click(screen.getByRole("button", { name: /Annuler l'import/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Annuler l'import" }));
    await waitFor(() => expect(spy.mock.calls.some(([input]) => String(input).includes("/rollback/"))).toBe(true));
    expect(await screen.findByText(/3 élément\(s\) archivé\(s\), 4 retiré\(s\), 0 restauré\(s\)/)).toBeInTheDocument();
  });
});
