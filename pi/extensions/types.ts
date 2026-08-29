export type NormalizedRole = "user" | "assistant" | "tool" | "other";
export interface NormalizedMessage {
  id: string; parent_id: string | null; role: NormalizedRole; content: string;
  tool_name: string | null; tool_call_id: string | null; tool_calls: Record<string, unknown>[];
  tool_error: boolean; timestamp: number | null; metadata: Record<string, unknown>;
}
export interface PulseInput {
  schema_version: 1; harness: "pi"; session_id: string; branch_leaf_id: string;
  session_file: string | null; provider: string; model: string; messages: NormalizedMessage[];
}
export interface PulseResult { schema_version: 1; status: string; session_id: string; branch_leaf_id: string; score: number; task_type: string; signals: {id:string; label?:string}[]; coaching: string[]; attribution: Record<string,number>; provider:string; model:string; message_count:number; user_turn_count:number; error:string|null; [key:string]: unknown }
export interface PulseEntry { schemaVersion: 1; sessionId:string; branchLeafId:string; sourceEntryId:string; timestamp:string; result:PulseResult; trigger:"command"|"automatic" }
export interface FeedbackEntry { schemaVersion:1; analysisEntryId:string; kind:"useful"|"not-useful"|"yes"|"no"; timestamp:string }
