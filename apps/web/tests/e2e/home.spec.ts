import { expect, test } from "@playwright/test";

test("홈이 열리고 색인이 꺼져 있어요", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "가게내비" })).toBeVisible();
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
});
