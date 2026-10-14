import { defineConfig } from "vitest/config";

export default defineConfig({
  // tsconfig의 `@/*` 경로와 같게
  resolve: { alias: { "@": import.meta.dirname } },
  test: {
    environment: "node",
    include: ["tests/unit/**/*.test.ts", "lib/**/*.test.ts"],
  },
});
