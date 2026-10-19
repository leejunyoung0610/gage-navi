import { defineConfig } from "vitest/config";

export default defineConfig({
  // tsconfig의 `@/*` 경로와 같게
  resolve: { alias: { "@": import.meta.dirname } },
  // tsconfig의 `jsx: preserve`는 Next용이라, 테스트에서는 React 자동 런타임으로 바꾼다
  oxc: { jsx: { runtime: "automatic" } },
  test: {
    environment: "node",
    // 컴포넌트 테스트(.tsx)는 파일 머리의 `@vitest-environment jsdom`으로 DOM을 쓴다
    include: ["tests/unit/**/*.test.{ts,tsx}", "lib/**/*.test.ts"],
  },
});
