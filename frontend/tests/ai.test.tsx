import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { matchRoutes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CopilotPage } from "@/features/ai/CopilotPage";
import { GenesisPage } from "@/features/ai/GenesisPage";
import { ImportDetailPage, ImportsPage } from "@/features/ai/ImportsPages";
import { ProposalDetailPage } from "@/features/ai/ProposalDetailPage";
import { ProjectProposalsPage } from "@/features/ai/ProposalsPages";
import { aiModuleTarget } from "@/features/ai/legacyRoutes";
import { resolveLegacyLink } from "@/lib/links";
import { ME, mockApi, renderPage } from "./utils";

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

const posted = (spy: ReturnType<typeof mockApi>, path: string) =>
  spy.mock.calls.find(([u, i]) => String(u).includes(path) && i?.method === "POST");

const OFF = { available: false, provider: "" };

describe("Genesis (création de projet par IA)", () => {
  const SCHEMA = {
    ai: OFF,
    fields: [
      { name: "name", label: "Nom du projet", type: "text", required: true, value: null },
      { name: "description", label: "Décrivez le projet", type: "textarea", required: true, value: null },
      { name: "workspace", label: "Workspace", type: "select", required: true, value: 1,
        choices: [{ value: "", label: "---------" }, { value: "1", label: "Alpha" }] },
      { name: "priority", label: "Priorité", type: "select", required: true, value: "MEDIUM",
        choices: [{ value: "MEDIUM", label: "Moyenne" }, { value: "HIGH", label: "Haute" }] },
      { name: "methodology", label: "Méthodologie", type: "select", required: false, value: "AGILE",
        choices: [{ value: "AGILE", label: "Agile" }, { value: "SCRUM", label: "Scrum" }] },
      { name: "target_date", label: "Date cible (facultatif)", type: "date", required: false, value: null },
      { name: "auto_apply", label: "Appliquer", type: "checkbox", required: false, value: true },
    ],
  };

  it("crée le projet (repli heuristique annoncé) puis propose les liens vers les éléments créés", async () => {
    const spy = mockApi({
      "POST ai/genesis/": { project: { id: 42, name: "Boutique" }, proposal: { id: 9, status: "APPLIED", status_label: "Appliquée" },
        applied: true, used_provider: "heuristic", counts: { tasks: 30, sprints: 4, milestones: 6 }, messages: ["Projet créé."] },
      "ai/genesis/": SCHEMA,
    });
    renderPage(<GenesisPage />, "/projects/genesis");
    expect(await screen.findByText(/IA désactivée/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Générer le projet/ }));
    expect(await screen.findAllByText("Champ obligatoire.")).toHaveLength(2);
    await userEvent.type(screen.getByLabelText(/Nom du projet/), "Boutique");
    await userEvent.type(screen.getByLabelText(/Décrivez le projet/), "Refonte du site marchand");
    await userEvent.selectOptions(screen.getByLabelText(/Méthodologie/), "SCRUM");
    await userEvent.click(screen.getByRole("button", { name: /Générer le projet/ }));
    expect(await screen.findByText(/Projet « Boutique » créé/)).toBeInTheDocument();
    const body = JSON.parse(String(posted(spy, "ai/genesis/")![1]!.body));
    expect(body).toMatchObject({ name: "Boutique", workspace: "1", methodology: "SCRUM", auto_apply: true, target_date: null });
    expect(screen.getByText(/30 tâche\(s\), 4 sprint\(s\), 6 jalon\(s\)/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ouvrir le projet" })).toHaveAttribute("href", "/projects/42");
    expect(screen.getByRole("link", { name: /Proposition IA/ })).toHaveAttribute("href", "/ai-proposals/9");
  });

  it("annonce le refus de droits sans proposer l'envoi", async () => {
    const spy = mockApi({ "ai/genesis/": { ...SCHEMA, can_create: false, fields: SCHEMA.fields.map((f) => (
      f.name === "workspace" ? { ...f, value: null, choices: [{ value: "", label: "---------" }] } : f)) } });
    renderPage(<GenesisPage />, "/projects/genesis");
    expect(await screen.findByText(/Votre rôle ne permet pas de créer un projet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Générer le projet/ })).toBeDisabled();
    expect(posted(spy, "ai/genesis/")).toBeUndefined();
  });
});

const item = (over: Record<string, unknown>) => ({
  kind: "TASK", kind_label: "Tâche", item_status: "PROPOSED", item_status_label: "Proposé", local_ref: "", title: "", description: "",
  order_index: 0, priority: "", complexity: "", estimate_hours: 0, recommended_profile: "", recommended_assignee: null,
  sprint_ref: "", milestone_ref: "", depends_on_refs: [], acceptance_criteria: [], start_date: null, end_date: null,
  velocity_target: 0, edited_by: "", edited_at: null, applied: null, ...over,
});

const PROPOSAL = {
  id: 5, status: "READY", status_label: "Prête à validation", project: { id: 3, name: "Portail" },
  summary: "Synthèse du projet", risks_summary: "Délais serrés", recommendations: ["Comité hebdo"],
  used_provider: "heuristic", used_model: "", tokens_used: 0, error_message: "", triggered_by: "Alice", validated_by: "",
  validated_at: null, applied_at: null, rejected_at: null, created_at: "2026-11-05T10:00:00Z", updated_at: "2026-11-05T10:00:00Z",
  running: false, can_edit: true, editable: true, can_validate_all: true, can_apply: true, can_reject: true, can_regenerate: true,
  counts: { total: 3, validated: 0, by_kind: { SPRINT: 1, TASK: 2 }, applied_by_kind: {} },
  coherence: { total_hours: 16, unassigned_tasks: 1, broken_dependencies: [], load_rows: [{ user_id: 1, label: "Alice", hours: 8 }] },
  kinds: [],
  items: [
    item({ id: 11, kind: "SPRINT", kind_label: "Sprint", local_ref: "S1", title: "Sprint 1 — Cadrage", start_date: "2026-11-09", end_date: "2026-11-20" }),
    item({ id: 12, local_ref: "T1", title: "Ateliers fonctionnels", sprint_ref: "S1", estimate_hours: 8, recommended_assignee: { id: 1, name: "Alice" } }),
    item({ id: 13, local_ref: "T2", title: "Maquettes", estimate_hours: 8 }),
  ],
  logs: [{ id: 1, action: "GENERATED", action_label: "Générée", actor: "Alice", message: "Proposition générée.", created_at: "2026-11-05T10:00:00Z" }],
};

describe("Aperçu d'une proposition IA", () => {
  it("affiche l'arborescence et valide un élément via la vue Django", async () => {
    const spy = mockApi({
      "POST ai-proposals/5/items/12/validate/": { messages: ["Élément validé."], item: {}, proposal_status: "PARTIALLY_VALIDATED" },
      "ai-proposals/5/": PROPOSAL,
    });
    renderPage(<ProposalDetailPage />, "/ai-proposals/5", "/ai-proposals/:id");
    expect(await screen.findByRole("heading", { name: "Portail" })).toBeInTheDocument();
    expect(screen.getByText("Sprint 1 — Cadrage", { selector: "summary span" })).toBeInTheDocument();
    expect(screen.getByText(/Tâches hors sprint/)).toBeInTheDocument();
    expect(screen.getByText("Délais serrés")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Valider Ateliers fonctionnels" }));
    await vi.waitFor(() => expect(posted(spy, "ai-proposals/5/items/12/validate/")).toBeTruthy());
  });

  it("applique la proposition après confirmation et lie les éléments créés", async () => {
    const validated = { ...PROPOSAL, items: PROPOSAL.items.map((i) => ({ ...i, item_status: "VALIDATED", item_status_label: "Validé" })) };
    const spy = mockApi({ "POST ai-proposals/5/apply/": { messages: [], project_id: 3, applied_by_kind: { TASK: 2, SPRINT: 1 } }, "ai-proposals/5/": validated });
    renderPage(<ProposalDetailPage />, "/ai-proposals/5?tab=TASK", "/ai-proposals/:id");
    await userEvent.click(await screen.findByRole("button", { name: /Appliquer au projet/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Les 3 élément\(s\) validé\(s\)/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Appliquer" }));
    await vi.waitFor(() => expect(posted(spy, "ai-proposals/5/apply/")).toBeTruthy());
  });

  it("une proposition appliquée n'offre plus d'action et pointe vers les objets créés", async () => {
    const applied = {
      ...PROPOSAL, status: "APPLIED", status_label: "Appliquée au projet", editable: false, can_apply: false, can_validate_all: false, can_reject: false,
      counts: { ...PROPOSAL.counts, applied_by_kind: { TASK: 1 } },
      items: [item({ id: 12, local_ref: "T1", title: "Ateliers fonctionnels", item_status: "APPLIED", item_status_label: "Appliqué",
        applied: { model: "Task", id: 55, link: "/tasks/55" } })],
    };
    mockApi({ "ai-proposals/5/": applied });
    renderPage(<ProposalDetailPage />, "/ai-proposals/5?tab=TASK", "/ai-proposals/:id");
    expect(await screen.findByRole("link", { name: /Ouvrir l'élément créé : Ateliers fonctionnels/ })).toHaveAttribute("href", "/tasks/55");
    expect(screen.queryByRole("button", { name: "Valider Ateliers fonctionnels" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Appliquer au projet/ })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Ouvrir le projet" })).toHaveAttribute("href", "/projects/3");
  });

  it("sans droits (RBAC Django) : consultation seule, aucune action proposée", async () => {
    mockApi({ "ai-proposals/5/": { ...PROPOSAL, can_edit: false, editable: false, can_validate_all: false, can_apply: false,
      can_reject: false, can_regenerate: false } });
    renderPage(<ProposalDetailPage />, "/ai-proposals/5?tab=TASK", "/ai-proposals/:id");
    expect(await screen.findByText(/Consultation seule/)).toBeInTheDocument();
    for (const name of [/Tout valider/, /Appliquer au projet/, /Régénérer/, /Rejeter/]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    expect(screen.queryByRole("button", { name: "Valider Ateliers fonctionnels" })).not.toBeInTheDocument();
  });
});

describe("Historique et déclenchement", () => {
  it("déclenche une génération et suit sa progression", async () => {
    const spy = mockApi({
      "POST projects/3/ai-proposals/trigger/": { success: true, proposal_id: 8, status: "PENDING" },
      "projects/3/ai-proposals/status/": { proposal_id: 8, status: "PENDING", progress: 35, step_label: "Construction de la roadmap", eta_seconds: 60, is_terminal: false },
      "projects/3/ai-proposals/": { project: { id: 3, name: "Portail", methodology_label: "" }, ai: OFF, can_trigger: true,
        proposals: [{ id: 5, status: "READY", status_label: "Prête à validation", project: { id: 3, name: "Portail" }, items_count: 3,
          used_provider: "heuristic", triggered_by: "Alice", created_at: "2026-11-05T10:00:00Z", running: false }] },
    });
    renderPage(<ProjectProposalsPage />, "/projects/3/ai-proposals", "/projects/:id/ai-proposals");
    expect(await screen.findByRole("link", { name: /Ouvrir la proposition n° 5/ })).toHaveAttribute("href", "/ai-proposals/5");
    await userEvent.click(screen.getByRole("button", { name: /Générer une nouvelle proposition/ }));
    await vi.waitFor(() => expect(posted(spy, "projects/3/ai-proposals/trigger/")).toBeTruthy());
    expect(await screen.findByText("Construction de la roadmap")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Progression de la génération" })).toHaveAttribute("aria-valuenow", "35");
  });
});

describe("Import documentaire", () => {
  const ROW = { id: 4, file_name: "cdc.pdf", file_ext: "pdf", file_url: "/media/devflow/project_imports/cdc.pdf", status: "UPLOADED",
    status_label: "Uploadé", project: null, workspace: "Alpha", uploaded_by: "Alice", created_at: "2026-11-05T10:00:00Z", has_error: false, excerpt: "" };

  it("liste les documents du workspace avec leurs statistiques", async () => {
    const failed = { ...ROW, id: 5, file_name: "lot2.docx", file_ext: "docx", status: "FAILED", status_label: "Échec", has_error: true,
      excerpt: "Aucun texte exploitable n'a été trouvé dans ce document." };
    const spy = mockApi({ "auth/me/": ME, "imports/": { results: [ROW, failed], count: 2, page: 1, num_pages: 1,
      stats: { total: 2, uploaded: 1, processing: 0, completed: 0, failed: 1 },
      status_choices: [{ value: "UPLOADED", label: "Uploadé" }], projects: [{ id: 3, name: "Portail" }], workspace: { id: 1, name: "Alpha" },
      workspaces: [{ id: 1, name: "Alpha" }, { id: 2, name: "Beta" }] } });
    renderPage(<ImportsPage />, "/imports?project=3");
    expect(await screen.findByRole("link", { name: "cdc.pdf" })).toHaveAttribute("href", "/imports/4");
    expect(screen.getByRole("option", { name: "Portail" })).toBeInTheDocument();
    expect(screen.getByText("Aucun texte exploitable n'a été trouvé dans ce document.")).toHaveClass("text-destructive");
    expect(screen.getAllByText(/Workspace Alpha/)).toHaveLength(2);
    // Filtre workspace (parité de la liste historique) : réinitialise le filtre projet.
    await userEvent.selectOptions(screen.getByLabelText("Workspace"), "2");
    await vi.waitFor(() => expect(spy.mock.calls.some(([u]) => String(u).includes("workspace=2") && !String(u).includes("project=3"))).toBe(true));
  });

  it("indique une analyse réservée quand les droits manquent", async () => {
    mockApi({ "imports/4/": { ...ROW, file_name: "Cahier_des_charges_plateforme_v2_Xk3pQ9a.pdf", extracted_text: "", ai_payload: null,
      error_message: "", updated_at: ROW.created_at, related: [], proposal: null, analysis_running: false, can_analyze: false, ai: OFF } });
    renderPage(<ImportDetailPage />, "/imports/4", "/imports/:id");
    expect(await screen.findByText(/L'analyse IA est réservée/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Analyser avec l'IA/ })).toBeDisabled();
    expect(screen.getByRole("heading", { name: "Cahier_des_charges_plateforme_v2_Xk3pQ9a.pdf" }).parentElement?.parentElement?.parentElement)
      .toHaveClass("[&_h1]:wrap-anywhere");
  });

  it("analyse un document puis renvoie vers la proposition à valider", async () => {
    const spy = mockApi({
      "POST imports/4/analyze/": { import_id: 4, project: { id: 21, name: "cdc" }, proposal: { id: 30, status: "READY", status_label: "Prête" },
        applied: false, used_provider: "heuristic", counts: {} },
      "imports/4/": { ...ROW, extracted_text: "", ai_payload: null, error_message: "", updated_at: ROW.created_at, related: [], proposal: null,
        analysis_running: false, can_analyze: true, ai: OFF },
    });
    renderPage(<ImportDetailPage />, "/imports/4", "/imports/:id");
    await userEvent.click(await screen.findByRole("button", { name: /Analyser avec l'IA/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Nom du projet à créer")).toHaveValue("cdc");
    await userEvent.click(within(dialog).getByRole("button", { name: /Lancer l'analyse/ }));
    expect(await screen.findByRole("link", { name: "Revoir et valider la proposition" })).toHaveAttribute("href", "/ai-proposals/30");
    expect(JSON.parse(String(posted(spy, "imports/4/analyze/")![1]!.body))).toEqual({ name: "cdc", use_ai: true, auto_apply: false });
  });
});

describe("Copilote projet", () => {
  const LOGS = { project: { id: 3, name: "Portail", methodology: "SCRUM", methodology_label: "Scrum" }, ai: { available: true, provider: "deepseek" },
    logs: [{ id: 1, created_at: "2026-11-05T10:00:00Z", tool_name: "create_sprint", user: "Alice", status: "SUCCESS", status_label: "Succès",
      duration_ms: 12, error_message: "", affected: { type: "Sprint", id: 4, link: "/m/sprint/4" } }] };

  it("envoie une suggestion, affiche l'action exécutée et son lien", async () => {
    const spy = mockApi({
      "POST projects/3/copilot/": { type: "tool_result", message: "Sprint 5 créé.", tool_name: "create_sprint",
        actions_executed: [{ tool: "create_sprint", log_id: 2, link: "/m/sprint/9" }] },
      "projects/3/copilot/logs/": LOGS,
    });
    renderPage(<CopilotPage />, "/projects/3/copilot", "/projects/:id/copilot");
    expect(await screen.findByText(/IA active/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Crée-moi le prochain sprint" }));
    expect(await screen.findByText("Sprint 5 créé.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ouvrir l'élément/ })).toHaveAttribute("href", "/m/sprint/9");
    const body = JSON.parse(String(posted(spy, "projects/3/copilot/")![1]!.body));
    expect(body).toEqual({ message: "Crée-moi le prochain sprint avec une durée de 2 semaines", history: [] });
    expect(sessionStorage.getItem("devflow:copilot:project:3")).toContain("Sprint 5 créé.");
    await userEvent.click(screen.getByRole("tab", { name: /Journal d'actions IA/ }));
    expect(await screen.findByRole("link", { name: "Sprint n° 4" })).toHaveAttribute("href", "/m/sprint/4");
  });
});

describe("Routes et liens du chantier IA", () => {
  it("traduit les URL historiques vers les routes React", () => {
    expect(resolveLegacyLink("/ai/genesis/")).toEqual({ kind: "app", to: "/projects/genesis" });
    expect(resolveLegacyLink("/ai-proposals/12/")).toEqual({ kind: "app", to: "/ai-proposals/12" });
    expect(resolveLegacyLink("/ai-proposals/12/items/3/edit/")).toEqual({ kind: "app", to: "/ai-proposals/12" });
    expect(resolveLegacyLink("/ai-proposals/?status=READY")).toEqual({ kind: "app", to: "/ai-proposals?status=READY" });
    expect(resolveLegacyLink("/projects/4/ai-proposals/")).toEqual({ kind: "app", to: "/projects/4/ai-proposals" });
    expect(resolveLegacyLink("/projects/4/copilot/logs/")).toEqual({ kind: "app", to: "/projects/4/copilot?tab=logs" });
    expect(resolveLegacyLink("/project-imports/7/")).toEqual({ kind: "app", to: "/imports/7" });
    expect(resolveLegacyLink("/project-imports/create/?project=4")).toEqual({ kind: "app", to: "/imports?new=1&project=4" });
    expect(resolveLegacyLink("/project-imports/")).toEqual({ kind: "app", to: "/imports" });
  });

  it("résout les nouvelles routes sans masquer la fiche projet", async () => {
    const { router } = await import("@/app/router");
    const leaf = (path: string) => matchRoutes(router.routes, path)?.at(-1)?.route.handle as { crumb?: string } | undefined;
    expect(leaf("/projects/genesis")?.crumb).toBe("Créer avec l'IA");
    expect(leaf("/projects/12/ai-proposals")?.crumb).toBe("Propositions IA");
    expect(leaf("/projects/12/copilot")?.crumb).toBe("Copilote IA");
    expect(leaf("/projects/12")?.crumb).toBe("Fiche");
    expect(leaf("/projects/new")?.crumb).toBe("Nouveau");
    expect(leaf("/ai-proposals/5")?.crumb).toBe("Aperçu");
    expect(leaf("/imports/5")?.crumb).toBe("Document");
  });

  it("redirige les anciennes pages génériques du pont vers les écrans dédiés", async () => {
    const { router } = await import("@/app/router");
    const parent = (path: string) => matchRoutes(router.routes, path)?.at(-2)?.route.path;
    expect(parent("/m/ai-proposal/5")).toBe("m/ai-proposal");
    expect(parent("/m/project-import/7")).toBe("m/project-import");
    expect(parent("/m/project-import/new")).toBe("m/project-import");
    expect(parent("/m/project-import/7/edit")).toBe("m/:resource");
    expect(parent("/m/risk/7")).toBe("m/:resource");
    expect(aiModuleTarget("/m/ai-proposal/5", "")).toBe("/ai-proposals/5");
    expect(aiModuleTarget("/m/ai-proposal", "?project=3&q=x")).toBe("/ai-proposals?project=3");
    expect(aiModuleTarget("/m/project-import/7/", "")).toBe("/imports/7");
    expect(aiModuleTarget("/m/project-import/new", "?project=4")).toBe("/imports?new=1&project=4");
    expect(aiModuleTarget("/m/project-import/new", "?workspace=1")).toBe("/imports?new=1");
    expect(aiModuleTarget("/m/project-import", "?workspace=2&status=FAILED")).toBe("/imports?workspace=2&status=FAILED");
  });
});
