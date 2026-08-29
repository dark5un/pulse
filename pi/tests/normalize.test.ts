import { describe, it, expect } from "vitest";
import { normalizeMessages, extractProviderModel, extractToolInfo } from "../extensions/normalize";

describe("normalizeMessages", () => {
  it("converts raw messages to normalized format", () => {
    const raw = [
      {
        entryId: "msg1",
        parent_id: "branch1",
        role: "user",
        content: "Hello",
        tool_name: null,
        tool_call_id: null,
        tool_calls: [],
        tool_error: false,
        timestamp: 1234567890,
        metadata: {},
      },
    ];
    const normalized = normalizeMessages(raw);
    expect(normalized[0]).toHaveProperty("id", "msg1");
    expect(normalized[0]).toHaveProperty("parent_id", "branch1");
    expect(normalized[0].role).toBe("user");
  });

  it("handles missing fields gracefully", () => {
    const raw = [{ entryId: "msg2", content: "Test" }];
    const normalized = normalizeMessages(raw);
    expect(normalized[0]).toHaveProperty("role", "user");
    expect(normalized[0]).toHaveProperty("tool_calls", []);
  });
});

describe("extractProviderModel", () => {
  it("extracts provider and model from assistant messages", () => {
    const messages = [{ role: "assistant", content: "Claude Sonnet" }];
    const result = extractProviderModel(messages);
    expect(result.provider).toBe("Claude");
    expect(result.model).toBe("Sonnet");
  });

  it("returns defaults for unknown messages", () => {
    const messages = [{ role: "user", content: "Hello" }];
    const result = extractProviderModel(messages);
    expect(result.provider).toBe("unknown");
    expect(result.model).toBe("unknown");
  });
});

describe("extractToolInfo", () => {
  it("extracts tool information correctly", () => {
    const toolCall = { id: "call1", function: { name: "read_file", arguments: {} } };
    const result = extractToolInfo(toolCall);
    expect(result.toolName).toBe("read_file");
    expect(result.toolCallId).toBe("call1");
    expect(result.isError).toBe(false);
  });

  it("handles empty tool calls", () => {
    const result = extractToolInfo(null);
    expect(result.toolName).toBe("unknown");
    expect(result.toolCallId).toBe("unknown");
  });
});
