import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { saveAnalysis, loadLatestAnalysis, saveFeedback, loadFeedback, resetState } from "../extensions/state";

describe("state persistence", () => {
  beforeEach(() => {
    resetState();
  });

  afterEach(() => {
    resetState();
  });

  it("saves and loads analysis correctly", () => {
    const analysis = {
      schema_version: 1,
      session_id: "sess1",
      branch_leaf_id: "branch1",
      source_entry_id: "entry1",
      score: 82,
      task_type: "coding",
      signals: [],
      coaching: [],
      attribution: { user: 50, agent: 50, other: 0 },
      provider: "anthropic",
      model: "claude-sonnet",
      message_count: 10,
      user_turn_count: 4,
      timestamp: 1234567890,
    };
    saveAnalysis(analysis);
    const loaded = loadLatestAnalysis("branch1");
    expect(loaded).toEqual(analysis);
  });

  it("saves and loads feedback correctly", () => {
    const feedback = {
      schema_version: 1,
      analysis_id: "analysis1",
      kind: "useful",
      rating: 5,
      timestamp: 1234567890,
    };
    saveFeedback(feedback);
    const loaded = loadFeedback("analysis1");
    expect(loaded).toEqual(feedback);
  });

  it("excludes sibling entries", () => {
    saveAnalysis({ session_id: "sess1", branch_leaf_id: "branch1", score: 82 });
    saveAnalysis({ session_id: "sess2", branch_leaf_id: "branch1", score: 75 });
    const loaded = loadLatestAnalysis("branch1");
    // The latest save wins
    expect(loaded?.score).toBe(82);
  });

  it("resets state completely", () => {
    saveAnalysis({ session_id: "sess1", branch_leaf_id: "branch1", score: 82 });
    resetState();
    const loaded = loadLatestAnalysis("branch1");
    expect(loaded).toBeNull();
  });
});
