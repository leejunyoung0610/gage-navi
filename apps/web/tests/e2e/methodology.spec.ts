/**
 * 방법론 페이지 (docs/40 §4.9, T-034). 가상 API(tests/e2e/mock-api.mjs)의 값으로 렌더한다.
 */
import { expect, test } from "@playwright/test";

test("방법론 페이지 360px — 섹션이 모두 있고 가로 스크롤 없음", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/methodology");
  await expect(page.getByRole("heading", { level: 1, name: "데이터와 계산 방법" })).toBeVisible();
  for (const name of ["주소 검색으로 필지를 찾는 정확도", "결과", "한계", "갱신 주기"]) {
    await expect(page.getByRole("heading", { level: 2, name, exact: true })).toBeVisible();
  }
  await expect(page.getByText("개별 예측력은 매우 작아요")).toBeVisible();
  await expect(page.getByText("95.0%").first()).toBeVisible(); // 가상 API의 판정용 일치율
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
});

test("층 페이지의 '어떻게 계산했나요?'에서 방법론으로 가요", async ({ page }) => {
  await page.goto("/place/1121510700100470001/1");
  await page.getByRole("link", { name: "어떻게 계산했나요?" }).click();
  await expect(page).toHaveURL(/\/methodology$/);
  await expect(page.getByRole("heading", { level: 2, name: "결과", exact: true })).toBeVisible();
});
