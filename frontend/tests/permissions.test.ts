import { describe, expect, it } from "vitest";
import { can } from "@/lib/permissions";

describe("can (miroir RBAC)", () => {
  it("handles exact, domain wildcard and global wildcard", () => {
    expect(can(["task.view"], "task.view")).toBe(true);
    expect(can(["project.*"], "project.delete")).toBe(true);
    expect(can(["*"], "billing.view")).toBe(true);
    expect(can(["task.view"], "task.delete")).toBe(false);
    expect(can([], "task.view")).toBe(false);
    expect(can(undefined, "task.view")).toBe(false);
  });
});
