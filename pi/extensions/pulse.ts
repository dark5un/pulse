import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { normalizeBranch } from "./normalize.js";
import { analyzeWithPulse } from "./bridge.js";
import { aggregate, latestAnalysis, saveAnalysis, saveFeedback, statusForBranch } from "./state.js";
import { renderResult, usage } from "./render.js";
import type { PulseResult } from "./types.js";

export default function pulseExtension(pi: ExtensionAPI) {
  let lastAutomaticKey = "";
  const branch = (ctx: any) => { const sm = ctx.sessionManager; const entries = sm.getBranch(); return { sm, entries, leaf: sm.getLeafId() ?? "root", session: sm.getSessionId() }; };
  const branchRevisionKey = (entries: any[], session: string, leaf: string) => `${session}:${leaf}:${entries.map(entry => String(entry.id ?? "")).join(",")}:${entries.length}`;
  const notify = (ctx:any, text:string, level:"info"|"warning"="info") => { if (ctx.hasUI && ctx.ui?.notify) ctx.ui.notify(text, level); else if (ctx.ui?.setStatus) ctx.ui.setStatus("pulse", text); };
  const run = async (ctx:any, trigger:"command"|"automatic"="command") => { const b=branch(ctx); const input=normalizeBranch(b.entries,b.session,b.leaf); const result=await analyzeWithPulse(input); if(result.status!=="insufficient_data") saveAnalysis(pi,result,trigger); return result; };
  pi.registerCommand("pulse", { description: "Analyze the active Pi branch with Pulse", handler: async (args:string, ctx:any) => {
    const command=(args||"").trim(); const b=branch(ctx);
    if (command === "") { try { const r=await run(ctx); notify(ctx,renderResult(r)); } catch(e) { notify(ctx,`Pulse error: ${e instanceof Error?e.message:String(e)}`,"warning"); } return; }
    if (command === "trends" || command === "models") { const a=aggregate(b.entries,b.session,b.leaf); notify(ctx,`${command}: ${a.count} branch-local analyses; average ${a.average.toFixed(1)}\n${a.models.map(m=>`${m.model}: ${m.count}, ${m.average.toFixed(1)}`).join("\n")||"No analyses yet."}`); return; }
    if (["useful","not-useful","yes","no"].includes(command)) { const latest=latestAnalysis(b.entries,b.session,b.leaf); if(!latest){notify(ctx,"No branch-local analysis to rate.","warning");return;} const id=saveFeedback(pi,b.entries,latest.sourceEntryId,command as any); notify(ctx,id?`Recorded ${command}.`: `Already rated ${command}.`); return; }
    notify(ctx,usage(),"warning");
  }});
  pi.registerTool({
    name: "pulse_analyze",
    label: "Pulse analysis",
    description: "Analyze the current Pi branch and return a structured Pulse quality report.",
    parameters: Type.Object({}),
    execute: async (_toolCallId, _params, _signal, _onUpdate, ctx) => {
      try {
        const result = await run(ctx);
        return { content: [{ type: "text", text: renderResult(result) }], details: result };
      } catch (e) {
        const message = `Pulse error: ${e instanceof Error ? e.message : String(e)}`;
        return { content: [{ type: "text", text: message }], details: { status: "error", error: message } };
      }
    },
  });
  pi.on("agent_settled", async (_event:any, ctx:any) => { if(process.env.PULSE_AUTO_ANALYZE !== "1") return; const b=branch(ctx); const key=branchRevisionKey(b.entries,b.session,b.leaf); if(key===lastAutomaticKey)return; try { const r=await run(ctx,"automatic"); lastAutomaticKey=key; if(r.status!=="insufficient_data" && ctx.hasUI) ctx.ui.setStatus?.("pulse",`${r.score}/100`); } catch { /* passive automation must never disrupt Pi */ } });
  const restoreStatus = (ctx:any) => {
    lastAutomaticKey = "";
    if (!ctx.hasUI) return;
    const b = branch(ctx);
    ctx.ui.setStatus?.("pulse", statusForBranch(b.entries, b.session, b.leaf));
  };
  pi.on("session_start", async (_event:any, ctx:any) => { restoreStatus(ctx); });
  pi.on("session_tree", async (_event:any, ctx:any) => { restoreStatus(ctx); });
}
