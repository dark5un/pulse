import { spawn } from "node:child_process";
import type { PulseInput, PulseResult } from "./types.js";

export interface BridgeOptions { executable?: string; timeoutMs?: number; maxOutputBytes?: number; }
export async function analyzeWithPulse(input: PulseInput, options: BridgeOptions = {}): Promise<PulseResult> {
  const executable = options.executable ?? process.env.PULSE_EXECUTABLE ?? "pulse";
  const timeout = options.timeoutMs ?? 15000; const max = options.maxOutputBytes ?? 2_000_000;
  return await new Promise((resolve, reject) => {
    const child = spawn(executable, ["analyze"], { stdio: ["pipe", "pipe", "pipe"] });
    let out = "", err = "", outBytes = 0, errBytes = 0, killed = false;
    const timer = setTimeout(() => { killed = true; child.kill("SIGTERM"); reject(new Error(`pulse timed out after ${timeout}ms`)); }, timeout);
    child.stdout.on("data", b => { outBytes += b.byteLength; out += b.toString(); if (outBytes > max && !killed) { killed = true; child.kill(); reject(new Error("pulse output exceeded limit")); } });
    child.stderr.on("data", b => { errBytes += b.byteLength; if (errBytes <= max) err += b.toString(); });
    child.on("error", e => { clearTimeout(timer); if (!killed) reject(new Error(`cannot start pulse: ${e.message}`)); });
    child.on("close", code => { clearTimeout(timer); if (killed) return; if (code !== 0) return reject(new Error(err.trim() || `pulse exited with code ${code}`)); try { const parsed = JSON.parse(out); if (!parsed || typeof parsed !== "object" || parsed.schema_version !== 1) throw new Error("invalid protocol result"); resolve(parsed as PulseResult); } catch (e) { reject(new Error(`invalid pulse output: ${e instanceof Error ? e.message : String(e)}`)); } });
    child.stdin.end(JSON.stringify(input));
  });
}
