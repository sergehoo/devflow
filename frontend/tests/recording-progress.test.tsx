import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RecordingProgress } from "@/features/meetings/RecordingProgress";
import { ME, mockApi, renderPage } from "./utils";

const FAILED = {
  id: 43, meeting_id: 5, status: "failed", status_label: "Échec", progress_percent: 100, progress_label: "Échec",
  is_terminal: true, is_final: true, created_at: "2099-01-10T10:00:00Z", started_at: null, completed_at: null,
  duration_seconds: 1, transcription_provider: "", summary_provider: "", error_message: "Transcription impossible",
  speakers_count: 0, recorded_by: "Paul", has_summary: false,
};

describe("Suivi d'un enregistrement en échec", () => {
  afterEach(() => vi.restoreAllMocks());

  it("affiche l'erreur, propose la relance et retire l'enregistrement supprimé", async () => {
    const api = mockApi({
      "auth/me/": ME,
      "meetings/recordings/43/status/": FAILED,
      "POST meetings/recordings/43/delete/": { messages: ["Enregistrement supprimé."] },
    });
    const onDeleted = vi.fn();
    renderPage(<RecordingProgress recordingId={43} meetingId={5} initial={FAILED} onDeleted={onDeleted} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Transcription impossible");
    expect(screen.getByRole("button", { name: /Réessayer la synthèse/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Supprimer/ }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Supprimer" }));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(43));
    expect(api.mock.calls.some(([u, i]) => String(u).includes("meetings/recordings/43/delete/") && i?.method === "POST")).toBe(true);
  });
});
