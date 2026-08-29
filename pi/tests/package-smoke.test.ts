import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const packageDir = fileURLToPath(new URL("..", import.meta.url));
const packageJson = JSON.parse(readFileSync(`${packageDir}/package.json`, "utf8"));

describe("Pi package metadata", () => {
  it("declares the Pi package resource and development checks", () => {
    expect(packageJson.name).toBe("@dark5un/pi-pulse");
    expect(packageJson.keywords).toContain("pi-package");
    expect(packageJson.license).toBe("MIT");
    expect(packageJson.pi.extensions).toContain("./extensions/pulse.ts");
    expect(packageJson.scripts.check).toBe("tsc --noEmit -p tsconfig.json");
    expect(packageJson.scripts.test).toBe("vitest run");
  });
});

describe("extension resources", () => {
  for (const resource of [
    "extensions/pulse.ts",
    "extensions/types.ts",
    "extensions/normalize.ts",
    "extensions/bridge.ts",
    "extensions/render.ts",
    "extensions/state.ts",
    "extensions/config.ts",
  ]) {
    it(`includes ${resource}`, () => {
      expect(existsSync(`${packageDir}/${resource}`)).toBe(true);
    });
  }
});
