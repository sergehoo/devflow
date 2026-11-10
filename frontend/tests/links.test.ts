import { describe, expect, it } from "vitest";
import { resolveLegacyLink } from "@/lib/links";

describe("resolveLegacyLink", () => {
  it("maps migrated legacy URLs to React routes", () => {
    expect(resolveLegacyLink("/tasks/12/")).toEqual({ kind: "app", to: "/tasks/12" });
    expect(resolveLegacyLink("/chat/?channel=5")).toEqual({ kind: "app", to: "/messenger?channel=5" });
    expect(resolveLegacyLink("/timesheets/list/")).toEqual({ kind: "app", to: "/timesheets/validation?scope=all&status=" });
    // Modules du pont générique (phase 5)
    expect(resolveLegacyLink("/risks/3/?tab=x")).toEqual({ kind: "app", to: "/m/risk/3" });
    expect(resolveLegacyLink("/billing/invoices/")).toEqual({ kind: "app", to: "/m/invoice" });
    expect(resolveLegacyLink("/meetings/series/4/")).toEqual({ kind: "app", to: "/meetings/series/4" });
    expect(resolveLegacyLink("/my-day/")).toEqual({ kind: "app", to: "/my-day" });
  });
  it("keeps non-migrated pages on the legacy UI", () => {
    expect(resolveLegacyLink("/ai-insights/dashboard/")).toEqual({ kind: "legacy", href: "/ai-insights/dashboard/" });
  });
  it("opens migrated finance, invoice and profile pages in React", () => {
    expect(resolveLegacyLink("/workspaces/3/financial-ai/portfolio/?tab=x")).toEqual({ kind: "app", to: "/finance/portfolio" });
    expect(resolveLegacyLink("/billing/invoices/12/")).toEqual({ kind: "app", to: "/invoices/12" });
    expect(resolveLegacyLink("/profile/password/")).toEqual({ kind: "app", to: "/profile" });
  });
  it("refuses external or protocol-relative URLs (no open redirect)", () => {
    expect(resolveLegacyLink("https://evil.test/")).toBeNull();
    expect(resolveLegacyLink("//evil.test/x")).toBeNull();
    expect(resolveLegacyLink("/\\evil.test")).toBeNull();
    expect(resolveLegacyLink("")).toBeNull();
  });
});
