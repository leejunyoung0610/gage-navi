/**
 * 자리 이력 여정 (T-036, docs/50 §7 "E2E: 주소 검색 → 필지 → 층 이력 → 근거/방법론").
 * 모바일 뷰포트 390×844(playwright.config.ts). API는 tests/e2e/mock-api.mjs(가상 예시)이고,
 * 카카오 지도 SDK는 막는다(외부 호출 없음).
 */
import { expect, test, type Page } from "@playwright/test";

const PNU = "1121510700100470001"; // mock-api.mjs와 같은 가상 예시
const ROAD_ADDR = "가상특별시 가상구 아주아주긴가상도로이름로 123번길 45";

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

test("검색 → 필지 → 층 → 근거·방법론 → 정정 요청 제출 (모바일)", async ({ page }) => {
  expect(page.viewportSize()).toEqual({ width: 390, height: 844 });

  // 1. 홈에서 주소 검색
  await page.goto("/");
  await page.getByLabel("주소", { exact: true }).fill("가상도로이름로 123");
  const results = page.getByRole("list", { name: "주소 결과" });
  await results.getByRole("button", { name: new RegExp(ROAD_ADDR) }).click();

  // 2. 필지 페이지
  await expect(page).toHaveURL(new RegExp(`/place/${PNU}$`));
  await expect(page.getByRole("heading", { name: "층 고르기" })).toBeVisible();
  await expectNoHorizontalScroll(page);

  // 3. 층 페이지
  await page.getByRole("link", { name: /^1층/ }).click();
  await expect(page).toHaveURL(new RegExp(`/place/${PNU}/1$`));
  await expect(page.getByRole("heading", { level: 1 })).toContainText("1층");

  // 4. 근거: 기준율 카드의 표본 수·신뢰구간·기준 월
  const card = page.getByRole("region", { name: "비슷한 자리의 3년 내 폐업률" });
  await expect(card).toContainText("43.1%");
  await expect(card).toContainText("612곳 기준");
  await expect(card).toContainText("95% 신뢰구간 39.2~47.1%");
  await expect(card).toContainText("2026년 11월 데이터");
  await expectNoHorizontalScroll(page);

  // 5. 방법론으로 갔다가 층 페이지로 돌아온다
  await card.getByRole("link", { name: "어떻게 계산했나요?" }).click();
  await expect(page).toHaveURL(/\/methodology$/);
  await expect(page.getByRole("heading", { level: 2, name: "결과", exact: true })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`/place/${PNU}/1$`));

  // 6. 정정 요청 제출
  await page.getByRole("button", { name: "정보가 잘못됐나요?" }).click();
  const sheet = page.getByRole("dialog", { name: "정보 정정 요청" });
  await expect(sheet).toBeVisible();
  await sheet.getByLabel("기타").check();
  await sheet.getByLabel("무엇이 잘못됐나요?").fill("  가상 예시: 상호가 달라요  ");
  const [request] = await Promise.all([
    page.waitForRequest(
      (req) => req.method() === "POST" && req.url().endsWith(`/api/v1/places/${PNU}/corrections`),
    ),
    sheet.getByRole("button", { name: "보내기" }).click(),
  ]);
  // 층 페이지의 시트 버튼은 기록을 고르지 않으므로 record_id 없이 층만 보낸다. 연락처 필드 없음 (docs/30 §2)
  expect(request.postDataJSON()).toEqual({
    kind: "other",
    message: "가상 예시: 상호가 달라요",
    floor: "1",
  });
  await expect(sheet.getByRole("status")).toHaveText("정정 요청을 받았어요. 확인한 뒤 반영할게요.");
  await expectNoHorizontalScroll(page);
});
