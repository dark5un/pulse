import type { PulseResult } from "./types.js";
export function renderResult(r: PulseResult): string { const signals=r.signals.map(s=>s.label??s.id).join(", ")||"none"; return `Pulse: ${r.score}/100 · ${r.status} · ${r.task_type}\nProvider/model: ${r.provider}/${r.model}\nMessages: ${r.message_count} (${r.user_turn_count} user turns)\nSignals: ${signals}${r.coaching.length?`\nCoaching: ${r.coaching.join("; ")}`:""}`; }
export function usage(): string { return "Usage: /pulse [trends|models|useful|not-useful|yes|no]"; }
