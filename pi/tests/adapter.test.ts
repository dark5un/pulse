import { describe, expect, it } from "vitest";
import { normalizeBranch, normalizeEntry } from "../extensions/normalize.js";
import { renderResult, usage } from "../extensions/render.js";
import { aggregate, latestAnalysis, saveAnalysis, saveFeedback } from "../extensions/state.js";
import type { PulseResult } from "../extensions/types.js";

const result = (overrides: Partial<PulseResult> = {}): PulseResult => ({
  schema_version: 1, status: "ok", session_id: "s1", branch_leaf_id: "l1", score: 82,
  task_type: "coding", signals: [{ id: "correction_chain", label: "Corrections" }],
  coaching: ["Keep the goal explicit."], attribution: { user: 80, agent: 20, other: 0 },
  provider: "local", model: "llama", message_count: 6, user_turn_count: 3,
  error: null, ...overrides,
});

describe("normalization", () => {
  it("preserves assistant metadata and flattens rich content", () => {
    const message = normalizeEntry({ id: "a1", parentId: "u1", type: "message", message: {
      role: "assistant", provider: "local", model: "llama", content: [{ type: "text", text: "answer" }, { type: "toolCall", name: "read" }], timestamp: 12,
    }});
    expect(message).toMatchObject({ id: "a1", parent_id: "u1", role: "assistant", content: "answer", timestamp: 12, tool_calls: [{ type: "toolCall", name: "read" }] });
    expect(message?.metadata).toMatchObject({ provider: "local", model: "llama", entry_type: "message" });
  });

  it("normalizes tool errors and ignores unsupported entries", () => {
    expect(normalizeEntry({ id: "t1", message: { role: "toolResult", toolName: "bash", toolCallId: "c1", content: "bad", isError: true } })).toMatchObject({ role: "tool", tool_name: "bash", tool_call_id: "c1", tool_error: true });
    expect(normalizeEntry({ id: "x", message: { role: "system", content: "ignore" } })).toBeNull();
  });

  it("selects the first assistant provider and model for the document", () => {
    const input = normalizeBranch([
      { id: "u", message: { role: "user", content: "hi" } },
      { id: "a", message: { role: "assistant", provider: "local", model: "llama", content: "ok" } },
    ], "s", "l");
    expect(input).toMatchObject({ schema_version: 1, harness: "pi", session_id: "s", branch_leaf_id: "l", provider: "local", model: "llama" });
    expect(input.messages).toHaveLength(2);
  });
});

describe("rendering", () => {
  it("renders attribution, coaching, and runtime detail", () => {
    const rendered = renderResult(result({
      runtime_logs: [{ module: "bash", error: "command failed", severity: "warning" }],
    }));
    expect(rendered).toContain("Attribution: user 80.0% · agent 20.0% · other 0.0%");
    expect(rendered).toContain("Coaching: Keep the goal explicit.");
    expect(rendered).toContain("Runtime: [bash] command failed");
  });

  it("documents every supported command", () => {
    expect(usage()).toContain("trends|models|useful|not-useful|yes|no");
  });
});

describe("branch-local state", () => {
  it("deduplicates feedback and aggregates only the selected branch", () => {
    const entries: { customType?: string; data?: unknown }[] = [];
    const writer = { appendEntry: (customType: string, data: unknown) => entries.push({ customType, data }) };
    saveAnalysis(writer, result(), "command");
    saveAnalysis(writer, result({ session_id: "s2", score: 20 }), "command");
    saveAnalysis(writer, result({ score: 90, model: "other" }), "automatic");
    const latest = latestAnalysis(entries, "s1", "l1");
    expect(latest?.result.score).toBe(90);
    expect(aggregate(entries, "s1", "l1")).toEqual({ count: 2, average: 86, models: [{ model: "local/llama", count: 1, average: 82 }, { model: "local/other", count: 1, average: 90 }] });
    const analysisId = latest!.analysisId;
    expect(saveFeedback(writer, entries, analysisId, "useful")).toBe(analysisId);
    expect(saveFeedback(writer, entries, analysisId, "useful")).toBeNull();
    expect(saveFeedback(writer, entries, analysisId, "not-useful")).toBeNull();
    expect(saveFeedback(writer, entries, analysisId, "yes")).toBe(analysisId);
    expect(saveFeedback(writer, entries, analysisId, "no")).toBeNull();
  });

  it("assigns distinct identities to analyses on the same branch", () => {
    const entries: { customType?: string; data?: unknown }[] = [];
    const writer = { appendEntry: (customType: string, data: unknown) => entries.push({ customType, data }) };
    saveAnalysis(writer, result(), "command");
    saveAnalysis(writer, result(), "command");
    const ids = entries.map(e => (e.data as any).analysisId);
    expect(new Set(ids).size).toBe(2);
  });
});
