import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

function readJson(name: string): Record<string, unknown> {
  return JSON.parse(readFileSync(new URL(`../../${name}`, import.meta.url), "utf-8"));
}

describe("저장소 골격", () => {
  it("TypeScript strict가 켜져 있어요", () => {
    const tsconfig = readJson("tsconfig.json") as { compilerOptions: { strict?: boolean } };
    expect(tsconfig.compilerOptions.strict).toBe(true);
  });

  it("make check·e2e·gen-api가 부르는 스크립트가 있어요", () => {
    const pkg = readJson("package.json") as { scripts: Record<string, string> };
    for (const name of ["lint", "typecheck", "format:check", "test", "e2e", "gen:api"]) {
      expect(pkg.scripts[name], name).toBeTypeOf("string");
    }
  });
});
