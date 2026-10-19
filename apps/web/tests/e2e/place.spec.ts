/**
 * 필지·층 이력 페이지 (docs/40 §4.3·4.4, T-033 수용 기준 "360px에서 가로 스크롤 없음").
 * API는 tests/e2e/mock-api.mjs(가상 예시)다. 카카오 지도 SDK는 막는다(외부 호출 없음).
 */
import { expect, test, type Page } from "@playwright/test";

const PNU = "1121510700100470001"; // mock-api.mjs와 같은 가상 예시

test.use({ viewport: { width: 360, height: 780 } });

test.beforeEach(async ({ page }) => {
  await page.route("**/dapi.kakao.com/**", (route) => route.abort());
});

async function expectNoHorizontalScroll(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
}

test("필지 페이지 360px — 층 목록·층 미상 기록·전체 보기에서 가로 스크롤 없음", async ({
  page,
}) => {
  await page.goto(`/place/${PNU}`);
  await expect(page.getByRole("heading", { name: "층을 알 수 없는 기록 25건" })).toBeVisible();
  await expect(page.getByRole("link", { name: /지하 1층/ })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "가상특별시 가상구 아주긴이름의가상동 4-3" }),
  ).toBeVisible();
  await expectNoHorizontalScroll(page);
  await page.getByRole("button", { name: "전체 보기(25건)" }).click();
  await expectNoHorizontalScroll(page);
});

test("층 페이지 360px — 기준율 표시, 타임라인 전체 보기, 정정 시트에서 가로 스크롤 없음", async ({
  page,
}) => {
  await page.goto(`/place/${PNU}/1`);
  await expect(page).toHaveTitle(/1층 가게 이력 \| 가게내비/);
  await expect(page.getByRole("region", { name: "비슷한 자리의 3년 내 폐업률" })).toContainText(
    "43.1%",
  );
  await expectNoHorizontalScroll(page);
  await page.getByRole("button", { name: "전체 보기(30건)" }).click();
  await expectNoHorizontalScroll(page);
  await page.getByRole("button", { name: "정보가 잘못됐나요?" }).click();
  await expect(page.getByRole("dialog", { name: "정보 정정 요청" })).toBeVisible();
  await expectNoHorizontalScroll(page);
});

test("층 페이지 360px — 기준율 숨김(층 규모 검증 미통과)", async ({ page }) => {
  await page.goto(`/place/${PNU}/B1`);
  await expect(
    page.getByText(
      "이 정도 규모의 층에서는 과거 폐업 횟수와 폐업률의 관계가 검증 기준을 통과하지 못했어요",
    ),
  ).toBeVisible();
  await expectNoHorizontalScroll(page);
});

test("기록 없는 필지는 기준 월과 함께 안내", async ({ page }) => {
  await page.goto("/place/1121510700100480000");
  await expect(
    page.getByText("이 필지에는 2026년 11월 기준 식품 업소 인허가 기록이 없어요."),
  ).toBeVisible();
});
