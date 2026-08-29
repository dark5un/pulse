import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { latestAnalysis, statusForBranch } from "../extensions/state.js";
import type { PulseResult } from "../extensions/types.js";

const packageDir = fileURLToPath(new URL("..", import.meta.url));
const extensionSource = readFileSync(`${packageDir}/extensions/pulse.ts`, "utf8");

const result = (overrides: Partial<PulseResult> = {}): PulseResult => ({
  schema_version: 1,
  status: "ok",
  session_id: "session",
  branch_leaf_id: "leaf",
  score: 87,
  task_type: "coding",
  signals: [],
  coaching: [],
  attribution: { user: 0, agent: 0, other: 0 },
  provider: "local",
  model: "llama",
  message_count: 8,
  user_turn_count: 4,
  error: null,
  ...overrides,
});

describe("pulse_analyze", () => {
  it("is registered as a read-only structured analysis tool", () => {
    expect(extensionSource).toContain("pulse_analyze");
    expect(extensionSource).toContain("details");
  });
});

describe("branch status restoration", () => {
  it("restores the latest status from the active branch only", () => {
    const entries = [
      { type: "custom", customType: "pulse:analysis", data: { schemaVersion: 1, sessionId: "other", branchLeafId: "leaf", result: result({ session_id: "other", score: 12 }) } },
      { type: "custom", customType: "pulse:analysis", data: { schemaVersion: 1, sessionId: "session", branchLeafId: "sibling", result: result({ branch_leaf_id: "sibling", score: 44 }) } },
      { type: "custom", customType: "pulse:analysis", data: { schemaVersion: 1, sessionId: "session", branchLeafId: "leaf", result: result() } },
    ];
    expect(latestAnalysis(entries, "session", "leaf")?.result.score).toBe(87);
    expect(statusForBranch(entries, "session", "leaf")).toBe("87/100");
    expect(statusForBranch(entries, "session", "missing")).toBeUndefined();
  });
});

// Keep the test fixture honest about the public entry shape used by Pi.
it("uses custom session entries rather than external persistence", () => {
  expect(extensionSource).toContain("session_start");
  expect(extensionSource).toContain("session_tree");
  expect(extensionSource).toContain("saveAnalysis");
});

void packageDir;

type _Result = PulseResult;
void (undefined as unknown as _Result);
