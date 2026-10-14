import { expect, test } from "@playwright/test";

test("헤더 메뉴와 푸터 안내가 있어요 (docs/40 §3)", async ({ page }) => {
  await page.goto("/");
  const menu = page.getByRole("navigation", { name: "주 메뉴" });
  for (const label of ["자리 이력", "정책자금", "폐업 지원", "내 사업장"]) {
    await expect(menu.getByRole("link", { name: label })).toBeVisible();
  }
  const footer = page.getByRole("contentinfo");
  await expect(footer).toContainText("행정안전부 인허가 데이터");
  await expect(footer).toContainText("가게내비는 신청을 대행하거나 수수료를 받지 않아요.");
  await expect(footer.getByRole("link", { name: "데이터와 계산 방법 보기" })).toHaveAttribute(
    "href",
    "/methodology",
  );
});

test("본문 글자 17px, 줄 간격 1.6 (docs/40 §1)", async ({ page }) => {
  await page.goto("/");
  const style = await page.evaluate(() => {
    const s = getComputedStyle(document.body);
    return { fontSize: s.fontSize, lineHeight: s.lineHeight };
  });
  expect(style.fontSize).toBe("17px");
  expect(parseFloat(style.lineHeight)).toBeCloseTo(17 * 1.6, 1);
});
