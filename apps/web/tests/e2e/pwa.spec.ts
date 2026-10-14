import { chromium, expect, test } from "@playwright/test";

// docs/40 §8. Lighthouse 12부터 PWA 항목이 없어져, Chrome이 설치 버튼을 띄울지 정하는 판정
// (`Page.getInstallabilityErrors`)을 직접 확인한다. 시크릿 창에서는 설치할 수 없어 일반 프로필로 띄운다
test("홈 화면에 설치할 수 있어요", async ({ baseURL }, testInfo) => {
  const context = await chromium.launchPersistentContext(testInfo.outputPath("profile"));
  try {
    const page = await context.newPage();
    await page.goto(new URL("/", baseURL).href);

    const scriptURL = await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.ready;
      return registration.active?.scriptURL;
    });
    expect(scriptURL).toBe(new URL("/sw.js", baseURL).href);

    const cdp = await context.newCDPSession(page);
    const manifest = await cdp.send("Page.getAppManifest");
    expect(manifest.errors).toEqual([]);
    const { installabilityErrors } = await cdp.send("Page.getInstallabilityErrors");
    expect(installabilityErrors).toEqual([]);
  } finally {
    await context.close();
  }
});

test("매니페스트: 이름·standalone·시작 URL·아이콘 192/512(maskable 포함)", async ({ request }) => {
  const response = await request.get("/manifest.webmanifest");
  expect(response.ok()).toBe(true);
  const manifest = (await response.json()) as {
    name: string;
    short_name: string;
    display: string;
    start_url: string;
    icons: { src: string; sizes: string; purpose: string }[];
  };
  expect(manifest).toMatchObject({
    name: "가게내비",
    short_name: "가게내비",
    display: "standalone",
    start_url: "/",
  });
  for (const sizes of ["192x192", "512x512"]) {
    for (const purpose of ["any", "maskable"]) {
      const icon = manifest.icons.find((i) => i.sizes === sizes && i.purpose === purpose);
      expect(icon, `${sizes} ${purpose}`).toBeDefined();
      expect((await request.get(icon!.src)).ok(), icon!.src).toBe(true);
    }
  }
});
