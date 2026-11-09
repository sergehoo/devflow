import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (m: string) => toastError(m), success: vi.fn() } }));

import { DOWNLOAD_ERROR, DownloadButton } from "@/features/meetings/DownloadButton";

describe("DownloadButton (exports Word / PDF)", () => {
  afterEach(() => { vi.restoreAllMocks(); toastError.mockReset(); });

  it("télécharge le fichier sans quitter React", async () => {
    const blob = new Blob(["%PDF"], { type: "application/pdf" });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(blob, {
      status: 200, headers: { "Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="CR-comite.pdf"' },
    }));
    const create = vi.fn(() => "blob:cr");
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<DownloadButton href="/meetings/1/minutes.pdf" filename="compte-rendu.pdf">PDF</DownloadButton>);
    fireEvent.click(screen.getByRole("button", { name: "PDF" }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/meetings/1/minutes.pdf"), expect.objectContaining({ redirect: "manual" }));
    expect((click.mock.contexts[0] as HTMLAnchorElement).download).toBe("CR-comite.pdf");
    expect(toastError).not.toHaveBeenCalled();
  });

  it("affiche une erreur quand Django redirige (génération impossible)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("<html></html>", { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<DownloadButton href="/meetings/1/minutes.docx" filename="compte-rendu.docx">Word</DownloadButton>);
    fireEvent.click(screen.getByRole("button", { name: "Word" }));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith(DOWNLOAD_ERROR));
    expect(click).not.toHaveBeenCalled();
  });
});
