import { describe, expect, it } from "vitest";
import { renderResult, usage } from "../extensions/render.js";
import type { PulseResult } from "../extensions/types.js";

const base: PulseResult = { schema_version: 1, status: "ok", session_id: "s", branch_leaf_id: "l", score: 82, task_type: "coding", signals: [], coaching: [], attribution: { user: 80, agent: 20, other: 0 }, provider: "local", model: "llama", message_count: 6, user_turn_count: 3, error: null };

describe("renderResult", () => {
  it("renders core result metadata and defaults empty signals", () => {
    expect(renderResult(base)).toContain("Pulse: 82/100 · ok · coding");
    expect(renderResult(base)).toContain("Provider/model: local/llama");
    expect(renderResult(base)).toContain("Signals: none");
  });
  it("renders attribution, coaching, and runtime provenance", () => {
    const text = renderResult({ ...base, signals: [{ id: "x", label: "A signal" }], coaching: ["Do this"], runtime_logs: [{ module: "bash", error: "failed", severity: "warning" }] });
    expect(text).toContain("Attribution: user 80.0% · agent 20.0% · other 0.0%");
    expect(text).toContain("Signals: A signal");
    expect(text).toContain("Coaching: Do this");
    expect(text).toContain("Runtime: [bash] failed");
  });
});

it("lists all supported commands", () => expect(usage()).toContain("trends|models|useful|not-useful|yes|no"));
 it("renders zero attribution when a category is absent", () => expect(renderResult({ ...base, attribution: {} })).toContain("Attribution: user 0.0% · agent 0.0% · other 0.0%"));
 it("renders multiple signals", () => expect(renderResult({ ...base, signals: [{ id: "one" }, { id: "two", label: "Two" }] })).toContain("Signals: one, Two"));
 it("omits empty coaching", () => expect(renderResult(base)).not.toContain("Coaching:"));
 it("omits empty runtime logs", () => expect(renderResult({ ...base, runtime_logs: [] })).not.toContain("Runtime:"));
 it("renders insufficient data status", () => expect(renderResult({ ...base, status: "insufficient_data" })).toContain("insufficient_data"));
 it("renders decimal scores", () => expect(renderResult({ ...base, score: 81.5 })).toContain("Pulse: 81.5/100"));
 it("renders runtime severity-independent detail", () => expect(renderResult({ ...base, runtime_logs: [{ module: "read", error: "warning" }] })).toContain("[read] warning"));
 it("renders multiple coaching items", () => expect(renderResult({ ...base, coaching: ["one", "two"] })).toContain("Coaching: one; two"));
 it("renders unknown task type", () => expect(renderResult({ ...base, task_type: "unknown" })).toContain("unknown"));
 it("renders empty provider/model", () => expect(renderResult({ ...base, provider: "unknown", model: "unknown" })).toContain("unknown/unknown"));
 it("renders empty signal labels using ids", () => expect(renderResult({ ...base, signals: [{ id: "id" }] })).toContain("Signals: id"));
 it("renders a zero message count", () => expect(renderResult({ ...base, message_count: 0, user_turn_count: 0 })).toContain("Messages: 0 (0 user turns)"));
 it("renders runtime log lists", () => expect(renderResult({ ...base, runtime_logs: [{ module: "a", error: "x" }, { module: "b", error: "y" }] })).toContain("[a] x; [b] y"));
 it("keeps usage prefixed for command completion", () => expect(usage()).toMatch(/^Usage: \/pulse/));
