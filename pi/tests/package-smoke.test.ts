import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { existsSync } from "fs";

describe("package metadata", () => {
  it("has valid package.json", () => {
    const packageJson = JSON.parse(readFileSync("./pi/package.json", "utf8"));
    expect(packageJson.name).toBe("@dark5un/pulse");
    expect(packageJson.keywords).toContain("pi-package");
    expect(packageJson.license).toBe("MIT");
  });

  it("has pi.extensions entry", () => {
    const packageJson = JSON.parse(readFileSync("./pi/package.json", "utf8"));
    expect(packageJson.pi).toHaveProperty("extensions");
    expect(packageJson.pi.extensions).toContain("pulse");
  });

  it("has no runtime dependency in devDependencies", () => {
    const packageJson = JSON.parse(readFileSync("./pi/package.json", "utf8"));
    const runtimeDeps = packageJson.dependencies || {};
    const devDeps = packageJson.devDependencies || {};
    // No runtime dependencies should be in devDependencies
    Object.keys(devDeps).forEach((key) => {
      expect(runtimeDeps[key]).toBeUndefined();
    });
  });
});

describe("extension file exists", () => {
  it("pulse.ts exists", () => {
    expect(existsSync("./pi/extensions/pulse.ts")).toBeTrue();
  });

  it("types.ts exists", () => {
    expect(existsSync("./pi/extensions/types.ts")).toBeTrue();
  });

  it("normalize.ts exists", () => {
    expect(existsSync("./pi/extensions/normalize.ts")).toBeTrue();
  });

  it("bridge.ts exists", () => {
    expect(existsSync("./pi/extensions/bridge.ts")).toBeTrue();
  });

  it("render.ts exists", () => {
    expect(existsSync("./pi/extensions/render.ts")).toBeTrue();
  });

  it("state.ts exists", () => {
    expect(existsSync("./pi/extensions/state.ts")).toBeTrue();
  });

  it("config.ts exists", () => {
    expect(existsSync("./pi/extensions/config.ts")).toBeTrue();
  });
});
