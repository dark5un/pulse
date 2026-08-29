import type { PulseResult } from "./types.js";
export function renderResult(r: PulseResult): string {
  const signals = r.signals.map(s => s.label ?? s.id).join(", ") || "none";
  const attribution = r.attribution;
  const lines = [
    `Pulse: ${r.score}/100 · ${r.status} · ${r.task_type}`,
    `Provider/model: ${r.provider}/${r.model}`,
    `Messages: ${r.message_count} (${r.user_turn_count} user turns)`,
    `Attribution: user ${(attribution.user ?? 0).toFixed(1)}% · agent ${(attribution.agent ?? 0).toFixed(1)}% · other ${(attribution.other ?? 0).toFixed(1)}%`,
    `Signals: ${signals}`,
  ];
  if (r.coaching.length) lines.push(`Coaching: ${r.coaching.join("; ")}`);
  const runtimeLogs = r.runtime_logs;
  if (Array.isArray(runtimeLogs) && runtimeLogs.length) {
    lines.push(`Runtime: ${runtimeLogs.map(log => `[${String(log.module)}] ${String(log.error)}`).join("; ")}`);
  }
  return lines.join("\n");
}
export function usage(): string { return "Usage: /pulse [trends|models|useful|not-useful|yes|no]"; }
