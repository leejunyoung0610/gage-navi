import { defineConfig } from "@playwright/test";

const port = 3000;
const mockApiPort = 4010;
const mockApiUrl = `http://localhost:${mockApiPort}`;

export default defineConfig({
  testDir: "./tests/e2e",
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://localhost:${port}`,
    trace: "on-first-retry",
  },
  projects: [
    {
      // 모바일 뷰포트 390×844 (docs/50 §1)
      name: "mobile-chromium",
      use: {
        browserName: "chromium",
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
  // 서비스 워커는 프로덕션 빌드에만 있으므로(next.config.ts) 빌드한 앱으로 확인한다 (tests/e2e/pwa.spec.ts)
  // 장소 페이지(T-033)는 서버에서 API를 부르므로 가상 API 서버(tests/e2e/mock-api.mjs)를 함께 띄운다.
  // NEXT_PUBLIC_*는 빌드 때 번들에 들어가므로 빌드 명령에도 같은 값을 준다
  webServer: [
    {
      command: `node tests/e2e/mock-api.mjs`,
      url: `http://localhost:${mockApiPort}/api/v1/health`,
      reuseExistingServer: !process.env.CI,
      env: { MOCK_API_PORT: String(mockApiPort) },
    },
    {
      command: `pnpm build && pnpm start --port ${port}`,
      url: `http://localhost:${port}`,
      reuseExistingServer: !process.env.CI,
      timeout: 240_000,
      env: { API_INTERNAL_URL: mockApiUrl, NEXT_PUBLIC_API_BASE_URL: mockApiUrl },
    },
  ],
});
