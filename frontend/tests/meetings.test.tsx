import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MeetingDetailPage } from "@/features/meetings/MeetingDetailPage";
import { MeetingsPage } from "@/features/meetings/MeetingsPage";
import { MeetingRecorder } from "@/features/meetings/Recorder";
import { RecordingPage } from "@/features/meetings/RecordingPage";
import { MeetingDashboardPage } from "@/features/meetings/DashboardPage";
import { meetingModuleTarget } from "@/features/meetings/constants";
import { resolveLegacyLink } from "@/lib/links";
import { ME, mockApi, renderPage } from "./utils";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const ROW = {
  status: "PLANNED", status_label: "Planifiée", meeting_type: "FOLLOW_UP", type_label: "Suivi", duration_minutes: 60,
  duration_label: "1h", organizer: "Paul", location: "", series_id: null, participants_count: 3,
};
const LIST = {
  results: [
    { ...ROW, id: 5, title: "Comité Portail", scheduled_at: "2099-01-10T09:00:00Z", project: { id: 7, name: "Portail" }, is_past: false },
    { ...ROW, id: 6, title: "Rétro", scheduled_at: "2020-01-10T09:00:00Z", project: null, is_past: true, status: "HELD", status_label: "Tenue" },
  ],
  count: 2, page: 1, num_pages: 1,
  type_choices: [{ value: "FOLLOW_UP", label: "Suivi" }, { value: "RETROSPECTIVE", label: "Rétrospective" }],
  status_choices: [{ value: "PLANNED", label: "Planifiée" }],
  current_project: { id: 7, name: "Portail" },
};

const USER = (id: number, name: string) => ({ id, name, email: `${name}@x.test` });
const PART = (id: number, name: string, extra = {}) => ({
  user: USER(id, name), rsvp_status: "INVITED", rsvp_label: "Invité", rsvp_note: "", rsvp_at: null, attendance_status: "UNKNOWN",
  attendance_label: "Non renseigné", self_confirmed: false, attendance_marked_by: "", attendance_marked_at: null, ...extra,
});
const DETAIL = {
  ...ROW, id: 5, title: "Comité Portail", scheduled_at: "2099-01-10T09:00:00Z", project: { id: 7, name: "Portail" },
  projects: [], sprint: null, series: { id: 2, name: "Hebdo" }, organizer_user: USER(2, "Paul"), meeting_link: "", external_participants: "Client — c@ext.test",
  attachments_count: 0, agenda_html: "", notes_html: "<p>Action : démo</p>", decisions_html: "", blockers_html: "", next_steps_html: "",
  ai_summary: "## Résumé\n- **Go** prod", ai_used_provider: "heuristic", ai_extracted_at: "2099-01-10T10:00:00Z",
  created_by: "Paul", created_at: "2099-01-01T09:00:00Z", updated_by: "", updated_at: "2099-01-01T09:00:00Z",
  agenda_items: [
    { id: 11, position: 1, title: "Budget", description: "", description_html: "", notes: "", notes_html: "", owner: USER(1, "Alice"),
      duration_minutes: 10, status: "PENDING", status_label: "À traiter", started_at: null, completed_at: null },
    { id: 12, position: 2, title: "Planning", description: "", description_html: "", notes: "", notes_html: "", owner: null,
      duration_minutes: 5, status: "PENDING", status_label: "À traiter", started_at: null, completed_at: null },
  ],
  agenda_status_choices: [{ value: "PENDING", label: "À traiter" }, { value: "DONE", label: "Traité" }],
  action_items: [{ id: 31, title: "Préparer la démo", description: "", owner: null, due_date: null, status: "OPEN", status_label: "Ouverte",
    priority: "HIGH", priority_label: "High", converted_task_id: null, converted_at: null }],
  action_priority_choices: [{ value: "LOW", label: "Low" }, { value: "MEDIUM", label: "Medium" }, { value: "HIGH", label: "High" }],
  can_convert_actions: true,
  participations: [PART(1, "Alice"), PART(3, "Bruno")],
  my_participation: PART(1, "Alice"),
  participations_stats: { accepted: 0, declined: 0, tentative: 0, pending: 2, present: 0, absent: 0 },
  can_mark_attendance: true,
  rsvp_choices: [], attendance_choices: [{ value: "UNKNOWN", label: "Non renseigné" }, { value: "PRESENT", label: "Présent" }, { value: "ABSENT", label: "Absent" }],
  reviews: { prefix: "project_reviews", management: { "project_reviews-TOTAL_FORMS": 1, "project_reviews-INITIAL_FORMS": 1 }, forms: [{
    id: 9, prefix: "project_reviews-0", project: { id: 7, name: "Portail" }, status_label: "Sur les rails", progress_pct: 10,
    fields: [
      { name: "id", label: "Id", type: "hidden", required: false, disabled: false, help_text: "", value: 9, max_length: null, min: null, max: null },
      { name: "project", label: "Projet", type: "hidden", required: true, disabled: false, help_text: "", value: 7, max_length: null, min: null, max: null },
      { name: "progress_pct", label: "Avancement", type: "number", required: true, disabled: false, help_text: "", value: 10, max_length: null, min: 0, max: 100 },
      { name: "DELETE", label: "Supprimer", type: "checkbox", required: false, disabled: false, help_text: "", value: false, max_length: null, min: null, max: null },
    ],
  }] },
  structured_decisions: [],
  recordings: [{ id: 42, meeting_id: 5, status: "waiting_speaker_mapping", status_label: "Identification voix", progress_percent: 70,
    progress_label: "Identification des voix (humain)", is_terminal: false, is_final: false, created_at: "2099-01-10T10:00:00Z", started_at: null,
    completed_at: null, duration_seconds: 125, transcription_provider: "", summary_provider: "", error_message: "", speakers_count: 1,
    recorded_by: "Paul", has_summary: false }],
  max_upload_mb: 600,
  downloads: { docx: "/meetings/5/minutes.docx", pdf: "/meetings/5/minutes.pdf" },
  legacy_url: "/meetings/5/",
};

const lastPost = (spy: ReturnType<typeof mockApi>, path: string) => {
  const call = [...spy.mock.calls].reverse().find(([u, i]) => String(u).includes(path) && i?.method === "POST");
  return call?.[1]?.body as FormData | undefined;
};

describe("Réunions — liste", () => {
  it("sépare à venir / passées et conserve le filtre projet", async () => {
    const spy = mockApi({ "auth/me/": ME, "meetings/": LIST });
    renderPage(<MeetingsPage />, "/meetings?project=7", "/meetings");
    expect(await screen.findByRole("link", { name: "Comité Portail" })).toHaveAttribute("href", "/meetings/5");
    expect(screen.getByRole("region", { name: "À venir" })).toHaveTextContent("Comité Portail");
    expect(screen.getByRole("region", { name: "Passées" })).toHaveTextContent("Rétro");
    expect(screen.getByText("Projet : Portail")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Nouvelle réunion/ })).toHaveAttribute("href", "/meetings/new?project=7");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Type de réunion" }), "RETROSPECTIVE");
    await vi.waitFor(() => expect(spy.mock.calls.some(([u]) => String(u).includes("type=RETROSPECTIVE") && String(u).includes("project=7"))).toBe(true));
  });
});

describe("Réunions — recherche dans l'URL", () => {
  it("reprend ?q= au chargement et l'envoie à Django", async () => {
    const spy = mockApi({ "auth/me/": ME, "meetings/": LIST });
    renderPage(<MeetingsPage />, "/meetings?q=Comit%C3%A9&project=7", "/meetings");
    expect(await screen.findByRole("searchbox", { name: "Rechercher une réunion" })).toHaveValue("Comité");
    await vi.waitFor(() => expect(spy.mock.calls.some(([u]) => String(u).includes("q=Comit") && String(u).includes("project=7"))).toBe(true));
    const box = screen.getByRole("searchbox", { name: "Rechercher une réunion" });
    await userEvent.clear(box);
    await userEvent.type(box, "Rétro");
    // waitFor (Testing Library) : l'écriture différée de ?q= dans l'URL a lieu sous act().
    await waitFor(() => expect(spy.mock.calls.some(([u]) => String(u).includes(`q=${encodeURIComponent("Rétro")}`) && String(u).includes("project=7"))).toBe(true));
  });
});

describe("Réunions — fiche", () => {
  it("affiche la synthèse IA et ajoute / réordonne un point d'ordre du jour", async () => {
    const spy = mockApi({
      "auth/me/": ME, "POST meetings/5/agenda/reorder/": { ok: true, updated: 2 },
      "POST meetings/5/agenda/": { messages: ["Point ajouté à l'ordre du jour."] }, "meetings/5/": DETAIL,
    });
    renderPage(<MeetingDetailPage />, "/meetings/5", "/meetings/:id");
    expect(await screen.findByRole("heading", { name: "Comité Portail" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Résumé" })).toBeInTheDocument();
    expect(screen.getByText("Go").tagName).toBe("STRONG");
    expect(screen.getByRole("button", { name: /PDF/ })).toBeInTheDocument(); // téléchargement sans quitter React (tests/download.test.tsx)
    await userEvent.click(screen.getByRole("button", { name: "Ajouter un point" }));
    await userEvent.type(screen.getByLabelText("Titre du point *"), "Risques");
    await userEvent.click(screen.getByRole("button", { name: "Ajouter" }));
    await vi.waitFor(() => expect(lastPost(spy, "meetings/5/agenda/")?.get("title")).toBe("Risques"));
    await userEvent.click(screen.getByRole("button", { name: "Descendre Budget" }));
    await vi.waitFor(() => expect(lastPost(spy, "agenda/reorder/")?.get("order")).toBe("12,11"));
  });

  it("répond à l'invitation, pointe les présences et convertit une action", async () => {
    const spy = mockApi({
      "auth/me/": ME, "POST meetings/5/rsvp/": { messages: ["Réponse enregistrée : Accepté."] },
      "POST meetings/5/attendance/": { messages: ["Présence mise à jour pour 1 participant(s)."] },
      "POST meetings/actions/31/convert/": { messages: ["Tâche créée."] }, "meetings/5/": DETAIL,
    });
    renderPage(<MeetingDetailPage />, "/meetings/5?tab=participants", "/meetings/:id");
    await userEvent.click(await screen.findByRole("button", { name: "J'accepte" }));
    await vi.waitFor(() => expect(lastPost(spy, "meetings/5/rsvp/")?.get("rsvp_status")).toBe("ACCEPTED"));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Présence de Bruno" }), "ABSENT");
    await userEvent.click(screen.getByRole("button", { name: /Enregistrer la présence/ }));
    await vi.waitFor(() => {
      const body = lastPost(spy, "meetings/5/attendance/");
      expect(body?.get("attendance_3")).toBe("ABSENT");
      expect(body?.get("attendance_1")).toBe("UNKNOWN");
    });
    await userEvent.click(screen.getByRole("tab", { name: /Actions/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Convertir en tâche/ }));
    await vi.waitFor(() => expect(spy.mock.calls.some(([u, i]) => String(u).includes("meetings/actions/31/convert/") && i?.method === "POST")).toBe(true));
  });

  it("enregistre le tour de table avec le formulaire de gestion Django", async () => {
    const spy = mockApi({ "auth/me/": ME, "POST meetings/5/reviews/": { messages: ["Revues projet enregistrées."] }, "meetings/5/": DETAIL });
    renderPage(<MeetingDetailPage />, "/meetings/5?tab=reviews", "/meetings/:id");
    const progress = await screen.findByLabelText("Avancement");
    await userEvent.clear(progress);
    await userEvent.type(progress, "55");
    await userEvent.click(screen.getByRole("button", { name: /Enregistrer les revues/ }));
    await vi.waitFor(() => {
      const body = lastPost(spy, "meetings/5/reviews/");
      expect(body?.get("project_reviews-TOTAL_FORMS")).toBe("1");
      expect(body?.get("project_reviews-0-id")).toBe("9");
      expect(body?.get("project_reviews-0-project")).toBe("7");
      expect(body?.get("project_reviews-0-progress_pct")).toBe("55");
      expect(body?.has("project_reviews-0-DELETE")).toBe(false);
    });
  });

  it("lance l'analyse IA et affiche le bilan renvoyé par Django", async () => {
    const spy = mockApi({ "auth/me/": ME, "POST meetings/5/ai-process/": { ok: true, used_provider: "deepseek", action_items_created: 2, risks_created: 1 },
      "POST meetings/5/send-minutes/": { messages: ["Envoi du compte-rendu lancé en arrière-plan."] }, "meetings/5/": DETAIL });
    renderPage(<MeetingDetailPage />, "/meetings/5", "/meetings/:id");
    await userEvent.click(await screen.findByRole("button", { name: /Analyser par IA/ }));
    await vi.waitFor(() => expect(spy.mock.calls.some(([u, i]) => String(u).includes("meetings/5/ai-process/") && i?.method === "POST")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: /^Envoyer$/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("checkbox", { name: /participants externes/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: /Envoyer/ }));
    await vi.waitFor(() => expect(lastPost(spy, "meetings/5/send-minutes/")?.get("include_external")).toBe("0"));
  });
});

describe("Réunions — fiche et enregistreur", () => {
  it("garde la capture active quand on change d'onglet (enregistreur hors des onglets)", async () => {
    vi.stubGlobal("MediaRecorder", FakeRecorder);
    const stopTrack = vi.fn();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] }) },
    });
    mockApi({ "auth/me/": ME, "meetings/recordings/42/status/": DETAIL.recordings[0], "meetings/5/": DETAIL });
    renderPage(<MeetingDetailPage />, "/meetings/5", "/meetings/:id");
    await userEvent.click(await screen.findByRole("checkbox", { name: /J'ai informé les participants/ }));
    await userEvent.click(screen.getByRole("button", { name: /Démarrer l'enregistrement/ }));
    expect(await screen.findByRole("button", { name: "Pause" })).toBeInTheDocument();
    // Ordre du jour → présences → enregistrements : pas de blocage, la capture continue.
    await userEvent.click(screen.getByRole("tab", { name: /Participants/ }));
    expect(await screen.findByRole("combobox", { name: "Présence de Bruno" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Enregistrements/ }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.getByLabelText("Durée enregistrée")).toBeInTheDocument();
    expect(stopTrack).not.toHaveBeenCalled();
    // Quitter la fiche reste confirmé.
    await userEvent.click(screen.getByRole("link", { name: "Portail" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Quitter la page ?");
  });

  it("désactive la conversion en tâche sans le droit Django", async () => {
    mockApi({ "auth/me/": ME, "meetings/5/": { ...DETAIL, can_convert_actions: false } });
    renderPage(<MeetingDetailPage />, "/meetings/5?tab=actions", "/meetings/:id");
    expect(await screen.findByRole("button", { name: /Convertir en tâche/ })).toBeDisabled();
    expect(screen.getByText(/réservée aux chefs de projet/)).toBeInTheDocument();
  });
});

describe("Enregistrement — page compte-rendu", () => {
  const REC = {
    ...DETAIL.recordings[0], meeting: { id: 5, title: "Comité Portail", scheduled_at: "2099-01-10T09:00:00Z", internal_participants_count: 3, has_external_participants: true },
    consent_acknowledged: true, original_filename: "recording.webm", file_size_bytes: 10, tokens_used: 120, summary_markdown: "Résumé **clé**",
    transcript: "", segments: [{ speaker_label: "A", speaker: "Alice", start: 65, end: 70, text: "Bonjour" }], segments_total: 1,
    speakers: [{ label: "A", display_name: "", total_duration_seconds: 12, total_segments: 3, mapped_participant_id: null, is_confirmed: false,
      sample_url: "/meetings/5/recordings/42/speakers/A/sample/?token=t" }],
    participants: [{ id: "1", full_name: "Alice", email: "alice@x.test" }], all_mapped: false,
    decisions: [{ id: 71, kind: "decision", kind_label: "Décision", title: "Go prod", description: "", assignee_hint: "", due_date_hint: "",
      priority_hint: "", confidence: 0, is_accepted: false, accepted_at: null }],
    actions: [], risks: [], project_suggestions: [], sprint_suggestions: [], milestone_suggestions: [], task_suggestions: [], mentions: [],
    can_create_projects: true, can_create_tasks: true,
    audio_url: "/recordings/42/audio/", downloads: { docx: "/meetings/5/recordings/42/minutes.docx", pdf: "/meetings/5/recordings/42/minutes.pdf" },
  };

  it("associe les voix, valide les décisions et envoie le compte-rendu", async () => {
    const spy = mockApi({
      "auth/me/": ME,
      "POST meetings/recordings/42/speakers/": { messages: ["1 association(s) enregistrée(s)."] },
      "POST meetings/recordings/42/decisions/": { messages: ["1 décision(s) validée(s)."] },
      "POST meetings/recordings/42/send-minutes/": { messages: ["Envoi du compte-rendu lancé à 4 destinataire(s)."] },
      "meetings/recordings/42/status/": DETAIL.recordings[0],
      "meetings/recordings/42/": REC,
    });
    renderPage(<RecordingPage />, "/meetings/5/recordings/42", "/meetings/:id/recordings/:recordingId");
    expect(await screen.findByRole("heading", { name: "Compte-rendu de l'enregistrement" })).toBeInTheDocument();
    expect(screen.getByLabelText("Extrait audio de A")).toHaveAttribute("src", "/meetings/5/recordings/42/speakers/A/sample/?token=t");
    // Suivi du pipeline (polling) : sur la page elle-même, l'invitation renvoie au bloc ci-dessous.
    expect(await screen.findByText(/Identifiez chaque intervenant ci-dessous/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Progression du traitement" })).toHaveAttribute("aria-valuenow", "70");
    await userEvent.selectOptions(screen.getByLabelText("Associer à"), "1");
    await userEvent.click(screen.getByRole("button", { name: /Enregistrer les associations/ }));
    await vi.waitFor(() => expect(lastPost(spy, "recordings/42/speakers/")?.get("speaker_A")).toBe("1"));
    await userEvent.click(screen.getByRole("checkbox", { name: /Go prod/ }));
    await userEvent.click(screen.getByRole("button", { name: "Valider les décisions cochées" }));
    await vi.waitFor(() => expect(lastPost(spy, "recordings/42/decisions/")?.getAll("accept_decision")).toEqual(["71"]));
    await userEvent.click(screen.getByRole("button", { name: /Envoyer par email/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Adresses supplémentaires/), "a@b.test");
    await userEvent.click(within(dialog).getByRole("button", { name: /Envoyer maintenant/ }));
    await vi.waitFor(() => expect(lastPost(spy, "recordings/42/send-minutes/")?.get("extra_emails")).toBe("a@b.test"));
  });

  it("suit la régénération d'un compte-rendu terminé jusqu'au nouveau CR", async () => {
    let regenerated = false;
    let reads = 0;
    const done = { ...REC, status: "completed", status_label: "Terminé", is_final: true, is_terminal: true, progress_percent: 100, speakers: [] };
    const spy = mockApi({
      "auth/me/": ME,
      "POST meetings/recordings/42/regenerate/": () => { regenerated = true; return { messages: ["Régénération du compte-rendu lancée."] }; },
      "meetings/recordings/42/": () => {
        if (regenerated) reads += 1;
        // Le CR reste l'ancien tant que la tâche Celery n'a pas tourné (1re relecture), puis il change.
        return { ...done, completed_at: regenerated && reads > 1 ? "2099-01-10T11:00:00Z" : "2099-01-10T10:30:00Z",
          summary_markdown: regenerated && reads > 1 ? "Nouveau **CR**" : "Ancien CR" };
      },
    });
    renderPage(<RecordingPage />, "/meetings/5/recordings/42", "/meetings/:id/recordings/:recordingId");
    await userEvent.click(await screen.findByRole("button", { name: /Régénérer CR/ }));
    await vi.waitFor(() => expect(spy.mock.calls.some(([u, i]) => String(u).includes("recordings/42/regenerate/") && i?.method === "POST")).toBe(true));
    expect(await screen.findByText(/Régénération demandée/)).toBeInTheDocument();
    expect(await screen.findByText("Nouveau", {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.queryByText(/Régénération demandée/)).not.toBeInTheDocument();
  }, 12000);

  it("verrouille les suggestions que l'utilisateur n'a pas le droit de créer", async () => {
    const sug = (id: number, kind: string, title: string) => ({ ...REC.decisions[0], id, kind, kind_label: kind, title });
    const spy = mockApi({
      "auth/me/": ME, "POST meetings/recordings/42/suggestions/": { messages: ["1 tâche(s) créée(s)."] },
      "meetings/recordings/42/status/": DETAIL.recordings[0],
      "meetings/recordings/42/": { ...REC, can_create_projects: false, can_create_tasks: true,
        project_suggestions: [sug(81, "project_suggestion", "Portail v2")], task_suggestions: [sug(82, "task_suggestion", "Écrire la doc")] },
    });
    renderPage(<RecordingPage />, "/meetings/5/recordings/42", "/meetings/:id/recordings/:recordingId");
    expect(await screen.findByRole("checkbox", { name: /Portail v2/ })).toBeDisabled();
    expect(screen.getByText(/Création de projet réservée/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /Écrire la doc/ }));
    await userEvent.click(screen.getByRole("button", { name: /Créer les éléments cochés/ }));
    await vi.waitFor(() => expect(lastPost(spy, "recordings/42/suggestions/")?.getAll("accept_suggestion")).toEqual(["82"]));
  });
});

class FakeRecorder {
  static isTypeSupported = () => true;
  state = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  start() { this.state = "recording"; }
  pause() { this.state = "paused"; }
  resume() { this.state = "recording"; }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["son"], { type: "audio/webm" }) });
    this.onstop?.();
  }
}

class FakeXHR {
  static sent: FakeXHR[] = [];
  upload: { onprogress: ((e: { loaded: number; total: number }) => void) | null } = { onprogress: null };
  status = 202;
  statusText = "Accepted";
  responseText = JSON.stringify({ recording_id: "42", status: "uploaded" });
  headers: Record<string, string> = {};
  url = "";
  body: FormData | null = null;
  timeout = 1;
  withCredentials = false;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  onabort: (() => void) | null = null;
  open(_method: string, url: string) { this.url = url; }
  setRequestHeader(k: string, v: string) { this.headers[k] = v; }
  send(body: FormData) {
    this.body = body;
    FakeXHR.sent.push(this);
    setTimeout(() => { this.upload.onprogress?.({ loaded: 5, total: 10 }); this.onload?.(); }, 0);
  }
}

describe("Enregistreur (MediaRecorder)", () => {
  it("exige le consentement et explique un refus du micro", async () => {
    vi.stubGlobal("MediaRecorder", FakeRecorder);
    const denied = Object.assign(new Error("denied"), { name: "NotAllowedError" });
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockRejectedValue(denied) } });
    mockApi({ "auth/me/": ME });
    renderPage(<MeetingRecorder meetingId={5} maxUploadMb={600} />);
    const start = await screen.findByRole("button", { name: /Démarrer l'enregistrement/ });
    expect(start).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /J'ai informé les participants/ }));
    await userEvent.click(start);
    expect(await screen.findByRole("alert")).toHaveTextContent("Permission micro refusée");
  });

  it("enregistre, met en pause, reprend puis envoie l'audio sur l'endpoint historique", async () => {
    FakeXHR.sent = [];
    vi.stubGlobal("MediaRecorder", FakeRecorder);
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    const stopTrack = vi.fn();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] }) },
    });
    document.cookie = "csrftoken=tok";
    mockApi({ "auth/me/": ME });
    const onUploaded = vi.fn();
    renderPage(<MeetingRecorder meetingId={5} maxUploadMb={600} onUploaded={onUploaded} />);
    await userEvent.click(await screen.findByRole("checkbox", { name: /J'ai informé les participants/ }));
    await userEvent.click(screen.getByRole("button", { name: /Démarrer l'enregistrement/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Pause" }));
    expect(screen.getByText("En pause")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reprendre" }));
    await userEvent.click(screen.getByRole("button", { name: "Arrêter" }));
    await vi.waitFor(() => expect(onUploaded).toHaveBeenCalledWith(42));
    const xhr = FakeXHR.sent[0]!;
    expect(xhr.url).toBe("/api/v1/meetings/5/recordings/upload/");
    expect(xhr.headers["X-CSRFToken"]).toBe("tok");
    expect((xhr.body?.get("audio") as File).name).toBe("recording.webm");
    expect(xhr.body?.get("consent_acknowledged")).toBe("true");
    expect(xhr.body?.has("recording_id")).toBe(false);
    expect(stopTrack).toHaveBeenCalled();
  });

  it("refuse un fichier importé trop volumineux ou non audio", async () => {
    mockApi({ "auth/me/": ME });
    renderPage(<MeetingRecorder meetingId={5} maxUploadMb={1} />);
    await userEvent.click(await screen.findByRole("checkbox", { name: /J'ai informé les participants/ }));
    const input = screen.getByLabelText("Fichier audio à importer");
    await userEvent.upload(input, new File([new Uint8Array(2 * 1024 * 1024)], "long.mp3", { type: "audio/mpeg" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Fichier trop volumineux");
  });
});

describe("Tableau de bord et liens", () => {
  it("affiche les indicateurs du mois", async () => {
    mockApi({ "auth/me/": ME, "meetings/dashboard/": {
      month_stats: { total: 4, held: 2, planned: 1, cancelled: 1 }, upcoming: [{ ...LIST.results[0], projects_count: 0 }], recent: [],
      top_projects: [{ id: 7, name: "Portail", count: 3 }], active_series: [{ id: 2, name: "Hebdo", recurrence_label: "Tous les lundis à 09:00" }],
      calendar: [{ day: null, date: null, count: 0, is_today: false, is_weekend: false }, { day: 1, date: "2099-01-01", count: 1, is_today: true, is_weekend: false }],
      speaking: [{ name: "Alice", minutes: 12.5 }], execution_rate: 50, total_decisions_year: 2, executed_decisions_year: 1, top_discussed_projects: [],
    } });
    renderPage(<MeetingDashboardPage />);
    expect(await screen.findByText("Réunions ce mois")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Comité Portail" })).toHaveAttribute("href", "/meetings/5");
    expect(screen.getByRole("link", { name: /Hebdo/ })).toHaveAttribute("href", "/meetings/series/2");
    expect(screen.getByText("1 exécutées sur 2")).toBeInTheDocument();
  });

  it("ouvre les liens historiques des réunions dans les nouvelles pages", () => {
    expect(resolveLegacyLink("/meetings/?project=7&x=1")).toEqual({ kind: "app", to: "/meetings?project=7" });
    expect(resolveLegacyLink("/meetings/create/?project=7")).toEqual({ kind: "app", to: "/meetings/new?project=7" });
    expect(resolveLegacyLink("/meetings/5/")).toEqual({ kind: "app", to: "/meetings/5" });
    expect(resolveLegacyLink("/meetings/5/update/")).toEqual({ kind: "app", to: "/meetings/5/edit" });
    expect(resolveLegacyLink("/meetings/dashboard/")).toEqual({ kind: "app", to: "/meetings/dashboard" });
    expect(resolveLegacyLink("/meetings/decisions/?status=PENDING")).toEqual({ kind: "app", to: "/meetings/decisions?status=PENDING" });
    expect(resolveLegacyLink("/meetings/series/create/")).toEqual({ kind: "app", to: "/meetings/series/new" });
    expect(resolveLegacyLink("/meetings/5/recordings/")).toEqual({ kind: "app", to: "/meetings/5?tab=recordings" });
    expect(resolveLegacyLink("/meetings/5/recordings/42/speakers/")).toEqual({ kind: "app", to: "/meetings/5/recordings/42" });
    expect(resolveLegacyLink("/meetings/5/recordings/42/summary/")).toEqual({ kind: "app", to: "/meetings/5/recordings/42" });
    // Fichiers (exports) : restent servis par Django.
    expect(resolveLegacyLink("/meetings/5/minutes.pdf")).toEqual({ kind: "legacy", href: "/meetings/5/minutes.pdf" });
    expect(meetingModuleTarget("/m/meeting/5")).toBe("/meetings/5");
    expect(meetingModuleTarget("/m/meeting/5/edit")).toBe("/meetings/5/edit");
    expect(meetingModuleTarget("/m/meeting/new", "?project=7")).toBe("/meetings/new?project=7");
    expect(meetingModuleTarget("/m/meeting-series/3")).toBe("/meetings/series/3");
    expect(meetingModuleTarget("/m/meeting-decision", "?status=PENDING")).toBe("/meetings/decisions?status=PENDING");
    expect(meetingModuleTarget("/m/meeting")).toBe("/meetings");
  });
});
