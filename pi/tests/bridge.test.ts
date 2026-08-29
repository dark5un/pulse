import { afterEach, describe, expect, it } from "vitest";
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { analyzeWithPulse } from "../extensions/bridge.js";

const dirs: string[] = [];
const script = (body: string) => {
  const dir = mkdtempSync(join(tmpdir(), "pi-pulse-"));
  dirs.push(dir);
  const path = join(dir, "pulse-fixture.mjs");
  writeFileSync(path, `#!/usr/bin/env node\n${body}\n`);
  chmodSync(path, 0o755);
  return path;
};
const input = { schema_version: 1 as const, harness: "pi" as const, session_id: "s", branch_leaf_id: "l", session_file: null, provider: "local", model: "llama", messages: [] };

afterEach(() => { for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true }); });

describe("Pulse bridge", () => {
  it("passes the versioned document and parses one result", async () => {
    const executable = script("process.stdin.resume(); process.stdin.on('end', () => process.stdout.write(JSON.stringify({schema_version:1,status:'ok'})))");
    await expect(analyzeWithPulse(input, { executable })).resolves.toMatchObject({ schema_version: 1, status: "ok" });
  });

  it("reports stderr for a failed executable", async () => {
    const executable = script("process.stderr.write('fixture failed'); process.exit(7)");
    await expect(analyzeWithPulse(input, { executable })).rejects.toThrow("fixture failed");
  });

  it("rejects malformed protocol output", async () => {
    const executable = script("process.stdout.write(JSON.stringify({schema_version:99}))");
    await expect(analyzeWithPulse(input, { executable })).rejects.toThrow("invalid pulse output");
  });

  it("enforces the output bound and timeout", async () => {
    const noisy = script("process.stdout.write('x'.repeat(1000))");
    await expect(analyzeWithPulse(input, { executable: noisy, maxOutputBytes: 100 })).rejects.toThrow("output exceeded limit");
    const slow = script("setTimeout(() => {}, 1000)");
    await expect(analyzeWithPulse(input, { executable: slow, timeoutMs: 10 })).rejects.toThrow("timed out after 10ms");
  });
});
