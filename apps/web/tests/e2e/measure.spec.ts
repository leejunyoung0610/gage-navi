/**
 * 방문 측정·"도움이 됐나요"·측정 끄기 (T-104, docs/40 §10, ADR-027). API는 가상 API(mock-api.mjs).
 *
 * Playwright 브라우저는 `navigator.webdriver`가 참이고 헤드리스 UA에 `HeadlessChrome`이 들어 있어
 * 앱이 봇으로 판단한다(그래서 다른 e2e는 이벤트를 보내지 않는다). 이벤트 전송을 확인하는 테스트에서만
 * 테스트 쪽에서 webdriver를 거짓으로, UA를 일반 모바일 브라우저로 바꾼다 — 앱 코드에 테스트 예외는 없다.
 */
import { expect, test, type Page, type Request } from "@playwright/test";

const PNU = "1121510700100470001"; // mock-api.mjs와 같은 가상 예시
const WEB_ORIGIN = "http://localhost:3000"; // playwright.config.ts
const MOCK_API_ORIGIN = "http://localhost:4010"; // playwright.config.ts
const EVENTS_URL = `${MOCK_API_ORIGIN}/api/v1/measure/events`;
const CHROME_MOBILE =
  "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36";

/** 페이지가 보낸 모든 요청을 모은다 */
function recordRequests(page: Page): Request[] {
  const requests: Request[] = [];
  page.on("request", (request) => requests.push(request));
  return requests;
}

/**
 * 보내지 않았음을 확인하려고 잠깐 기다린다. 이 앱은 프리페치 등으로 `networkidle`에 이르지 않아
 * 그것을 쓸 수 없다. 이벤트는 페이지를 연 직후·클릭 직후에 나가므로 1초면 충분하다
 */
const QUIET_MS = 1000;

const measureEvents = (requests: Request[]) =>
  requests
    .filter((r) => r.url() === EVENTS_URL && r.method() === "POST")
    .map((r) => r.postDataJSON() as unknown);

/** 요청은 웹 자기 주소와 가상 API로만 간다 — e2e가 운영 API로 이벤트를 보내지 않는다 */
function expectOnlyLocalOrigins(requests: Request[]) {
  const origins = new Set(requests.map((r) => new URL(r.url()).origin));
  for (const origin of origins) expect([WEB_ORIGIN, MOCK_API_ORIGIN]).toContain(origin);
}

async function visitHomeAndFloor(page: Page) {
  await page.goto("/");
  await page.goto(`/place/${PNU}/1`);
  await expect(page.getByRole("heading", { name: "계약 판단에 도움이 됐나요?" })).toBeVisible();
}

test.describe("Playwright 기본 브라우저 (봇으로 판단)", () => {
  test("측정 이벤트를 보내지 않는다", async ({ page }) => {
    const requests = recordRequests(page);
    await visitHomeAndFloor(page);
    await page.getByRole("button", { name: "예" }).click();
    await expect(
      page.getByText("통계에서 빠지기를 켜 두어서 응답을 보내지 않았어요."),
    ).toBeVisible();
    await page.waitForTimeout(QUIET_MS);
    expect(measureEvents(requests)).toEqual([]);
    expectOnlyLocalOrigins(requests);
  });
});

test.describe("사람 브라우저로 바꾼 경우 (테스트 쪽에서만)", () => {
  test.use({ userAgent: CHROME_MOBILE });

  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(Navigator.prototype, "webdriver", { get: () => false });
    });
  });

  test("첫 방문은 한 번만, 예/아니오는 날짜만 담아 가상 API로 보낸다", async ({ page }) => {
    const requests = recordRequests(page);
    await visitHomeAndFloor(page);
    await page.getByRole("button", { name: "예" }).click();
    await expect(page.getByText("알려 주셔서 고마워요.")).toBeVisible();
    await expect.poll(() => measureEvents(requests)).toHaveLength(2);
    await page.waitForTimeout(QUIET_MS);
    const events = measureEvents(requests);
    expect(events).toHaveLength(2);
    expect(events[0]).toEqual({
      event: "first_visit",
      date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
    });
    expect(events[1]).toEqual({
      event: "helpful_yes",
      date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
    });
    expectOnlyLocalOrigins(requests);
  });

  test("/privacy에서 측정 끄기를 켜면 아무 이벤트도 보내지 않는다", async ({ page }) => {
    await page.goto("/privacy");
    const toggle = page.getByRole("switch", { name: /통계에서 빠지기/ });
    // 이 페이지에 처음 들어올 때 보낸 첫 방문은 스위치를 켜기 전이다
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "true");

    const requests = recordRequests(page);
    await page.evaluate(() => {
      localStorage.removeItem("gn.visit.first");
      localStorage.removeItem("gn.visit.first_sent");
    });
    await visitHomeAndFloor(page);
    await page.getByRole("button", { name: "아니오" }).click();
    await expect(
      page.getByText("통계에서 빠지기를 켜 두어서 응답을 보내지 않았어요."),
    ).toBeVisible();
    await page.waitForTimeout(QUIET_MS);
    expect(measureEvents(requests)).toEqual([]);
  });
});
