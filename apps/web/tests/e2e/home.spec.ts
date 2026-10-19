import { expect, test } from "@playwright/test";

test("홈이 열리고 색인이 꺼져 있어요", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "일부러 틀린 제목 (T-106 실패 확인용)" })).toBeVisible();
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
});

test("색인이 꺼져 있으면 robots.txt가 전체를 막고 사이트맵이 없어요", async ({ request }) => {
  const robots = await request.get("/robots.txt");
  expect(robots.status()).toBe(200);
  const body = await robots.text();
  expect(body).toMatch(/Disallow: \/\s*$/m);
  expect(body).not.toContain("Sitemap:");
  expect((await request.get("/sitemap.xml")).status()).toBe(404);
  expect((await request.get("/sitemaps/11215-1.xml")).status()).toBe(404);
});
