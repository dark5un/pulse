import { describe, expect, it } from "vitest";
import { normalizeBranch, normalizeEntry } from "../extensions/normalize.js";

describe("normalizeEntry", () => {
  it("normalizes users, assistants, tool results, and bash executions", () => {
    expect(normalizeEntry({ id: "u", message: { role: "user", content: "hello" } })).toMatchObject({ role: "user", content: "hello" });
    expect(normalizeEntry({ id: "a", message: { role: "assistant", content: "answer" } })).toMatchObject({ role: "assistant", content: "answer" });
    expect(normalizeEntry({ id: "t", message: { role: "toolResult", content: "bad", toolName: "read", toolCallId: "c", isError: true } })).toMatchObject({ role: "tool", tool_name: "read", tool_call_id: "c", tool_error: true });
    expect(normalizeEntry({ id: "b", message: { role: "bashExecution", command: "false", output: "failed", exitCode: 1 } })).toMatchObject({ role: "tool", tool_name: "bash", content: "false\nfailed", tool_error: true });
  });

  it("ignores unknown roles and preserves tool calls", () => {
    expect(normalizeEntry({ id: "x", message: { role: "system", content: "ignore" } })).toBeNull();
    expect(normalizeEntry({ id: "a", message: { role: "assistant", content: [{ type: "text", text: "x" }, { type: "toolCall", name: "read" }] } })?.tool_calls).toEqual([{ type: "toolCall", name: "read" }]);
  });
});

describe("normalizeBranch", () => {
  it("creates the protocol envelope from the active branch", () => {
    const value = normalizeBranch([{ id: "u", message: { role: "user", content: "hi" } }, { id: "a", message: { role: "assistant", provider: "local", model: "llama", content: "ok" } }], "session", "leaf");
    expect(value).toMatchObject({ schema_version: 1, harness: "pi", session_id: "session", branch_leaf_id: "leaf", provider: "local", model: "llama" });
    expect(value.messages).toHaveLength(2);
  });
});

it("uses unknown provider metadata when no assistant exists", () => {
  expect(normalizeBranch([{ id: "u", message: { role: "user", content: "hi" } }], "s", "l")).toMatchObject({ provider: "unknown", model: "unknown" });
});

it("flattens nested rich text without trailing whitespace", () => {
  expect(normalizeEntry({ id: "a", message: { role: "assistant", content: [{ text: "answer" }, { text: "" }] } })?.content).toBe("answer");
});

it("marks cancelled bash executions as errors", () => {
  expect(normalizeEntry({ id: "b", message: { role: "bashExecution", command: "sleep", output: "", cancelled: true } })?.tool_error).toBe(true);
});

it("normalizes custom and summary entries as other", () => {
  expect(normalizeEntry({ id: "c", message: { role: "custom", content: "note" } })).toMatchObject({ role: "other", content: "note" });
});

it("handles missing message content safely", () => {
  expect(normalizeEntry({ id: "u", message: { role: "user" } })).toMatchObject({ role: "user", content: "" });
});

it("keeps null parent ids and timestamps", () => {
  expect(normalizeEntry({ id: "u", parentId: null, message: { role: "user", content: "x", timestamp: 42 } })).toMatchObject({ parent_id: null, timestamp: 42 });
});

it("does not treat a successful bash exit as an error", () => {
  expect(normalizeEntry({ id: "b", message: { role: "bashExecution", command: "true", output: "ok", exitCode: 0 } })?.tool_error).toBe(false);
});

it("joins array text blocks", () => {
  expect(normalizeEntry({ id: "u", message: { role: "user", content: ["one", "two"] } })?.content).toBe("one two");
});

it("preserves entry type provenance", () => {
  expect(normalizeEntry({ id: "u", type: "message", message: { role: "user", content: "x" } })?.metadata.entry_type).toBe("message");
});
