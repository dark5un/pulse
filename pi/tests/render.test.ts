import { describe, it, expect } from "vitest";
import { renderAnalysis, renderTrends } from "../extensions/render";

describe("renderAnalysis", () => {
  it("renders analysis to a string", () => {
    const analysis = {
      schema_version: 1,
      session_id: "sess1",
      branch_leaf_id: "branch1",
      source_entry_id: "entry1",
      score: 82,
      task_type: "coding",
      signals: [{ id: "sig1", description: "Clear goal", attribution: { user: 30, agent: 70, other: 0 } }],
      coaching: ["Keep going"],
      attribution: { user: 30, agent: 70, other: 0 },
      provider: "anthropic",
      model: "claude-sonnet",
      message_count: 10,
      user_turn_count: 4,
      timestamp: 1234567890,
    };
    const rendered = renderAnalysis(analysis);
    expect(rendered).toContain("Score: 82/100");
    expect(rendered).toContain("Task Type: coding");
    expect(rendered).toContain("Keep going");
  });
});

describe("renderTrends", () => {
  it("renders trends to a string", () => {
    const analyses = [
      { model: "claude-sonnet", score: 82 },
      { model: "claude-sonnet", score: 75 },
      { model: "claude-opus", score: 90 },
    ];
    const rendered = renderTrends(analyses);
    expect(rendered).toContain("claude-sonnet");
    expect(rendered).toContain("claude-opus");
    expect(rendered).toContain("Average Score:");
  });
});
