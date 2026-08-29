import type { NormalizedMessage, PulseInput } from "./types.js";

type Entry = { id: string; parentId?: string | null; timestamp?: string; type?: string; message?: Record<string, unknown>; };
const text = (value: unknown): string => Array.isArray(value) ? value.map(text).join(" ").trim() : typeof value === "string" ? value : (value && typeof value === "object" && "text" in value) ? String((value as {text:unknown}).text) : "";

export function normalizeEntry(entry: Entry): NormalizedMessage | null {
  const m = entry.message ?? {};
  const role = m.role;
  let normalized: NormalizedMessage["role"] = "other";
  let content = ""; let toolName: string | null = null; let callId: string | null = null; let error = false;
  if (role === "user") { normalized = "user"; content = text(m.content); }
  else if (role === "assistant") { normalized = "assistant"; content = text(m.content); }
  else if (role === "toolResult") { normalized = "tool"; content = text(m.content); toolName = typeof m.toolName === "string" ? m.toolName : null; callId = typeof m.toolCallId === "string" ? m.toolCallId : null; error = m.isError === true; }
  else if (role === "bashExecution") { normalized = "tool"; content = `${text(m.command)}\n${text(m.output)}`; toolName = "bash"; error = typeof m.exitCode === "number" && m.exitCode !== 0 || m.cancelled === true; }
  else if (role === "custom" || role === "branchSummary" || role === "compactionSummary") { normalized = "other"; content = text(m.content ?? m.summary); }
  else return null;
  const calls = Array.isArray(m.content) ? m.content.filter((x): x is Record<string, unknown> => !!x && typeof x === "object" && (x as {type?:unknown}).type === "toolCall") : [];
  return { id: entry.id, parent_id: entry.parentId ?? null, role: normalized, content, tool_name: toolName, tool_call_id: callId, tool_calls: calls, tool_error: error, timestamp: typeof m.timestamp === "number" ? m.timestamp : null, metadata: { provider: m.provider, model: m.model, entry_type: entry.type } };
}

export function normalizeBranch(entries: Entry[], sessionId: string, leafId: string): PulseInput {
  const messages = entries.map(normalizeEntry).filter((m): m is NormalizedMessage => m !== null);
  const assistant = entries.map(e => e.message).find(m => m?.role === "assistant");
  return { schema_version: 1, harness: "pi", session_id: sessionId, branch_leaf_id: leafId, session_file: null, provider: typeof assistant?.provider === "string" ? assistant.provider : "unknown", model: typeof assistant?.model === "string" ? assistant.model : "unknown", messages };
}
