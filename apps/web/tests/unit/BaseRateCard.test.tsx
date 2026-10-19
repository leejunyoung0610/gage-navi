// @vitest-environment jsdom
/**
 * BaseRateCard (docs/40 §4.4-3, T-033 수용 기준 "기준율 표시·숨김 두 상태 스냅샷 테스트").
 * 비율·건수·코드는 모두 가상 예시다(docs/30 §2 예시 형식).
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { BaseRateCard, bucketLabel } from "@/components/BaseRateCard";
import type { BaseRate } from "@/lib/place";

afterEach(cleanup);

// 가상 예시
const SHOWN: BaseRate = {
  display: true,
  hidden_reason: null,
  floor_scale: "single",
  prior_closures_now: 4,
  bucket: "4+",
  primary: {
    scope_code: "11215",
    scope_label: "가상구",
    rate: "0.4310",
    ci: ["0.3920", "0.4710"],
    n: 612,
  },
  baseline: { scope_code: "11215", bucket: "0", rate: "0.2950", ci: ["0.2810", "0.3090"], n: 4012 },
  secondary: {
    scope_code: "11",
    scope_label: "서울",
    rate: "0.4340",
    ci: ["0.4260", "0.4420"],
    n: 14532,
  },
  snapshot_label: "2026-11",
  method_version: "2026.10.1",
};

const hidden = (reason: BaseRate["hidden_reason"]): BaseRate => ({
  ...SHOWN,
  display: false,
  hidden_reason: reason,
  primary: null,
  baseline: null,
  secondary: null,
});

describe("BaseRateCard", () => {
  it("표시 상태 스냅샷", () => {
    const { container } = render(<BaseRateCard baseRate={SHOWN} />);
    expect(container.innerHTML).toMatchSnapshot();
    const card = screen.getByRole("region", { name: "비슷한 자리의 3년 내 폐업률" });
    expect(card.textContent).toContain(
      "이 층처럼 과거 폐업이 4회 이상인 자리에 새로 연 가게는 3년 안에 43.1%가 문을 닫았어요.",
    );
    expect(card.textContent).toContain("과거 폐업이 없던 자리는 29.5%였어요.");
    expect(card.textContent).toContain(
      "가상구 한 점포가 쓰던 층 612곳 기준 · 95% 신뢰구간 39.2~47.1% · 2026년 11월 데이터",
    );
    expect(card.textContent).toContain(
      "참고 통계예요. 이 자리에 열 가게의 성패를 예측하지 않아요.",
    );
    expect(screen.getByRole("link", { name: "어떻게 계산했나요?" })).toHaveProperty(
      "pathname",
      "/methodology",
    );
  });

  it("숨김 상태(표본 부족) 스냅샷", () => {
    const { container } = render(<BaseRateCard baseRate={hidden("insufficient_sample")} />);
    expect(container.innerHTML).toMatchSnapshot();
    expect(container.textContent).toContain(
      "비슷한 이력의 자리가 충분하지 않아(200곳 미만) 통계를 보여드리지 않아요.",
    );
    expect(container.textContent).not.toMatch(/\d+\.\d%/);
  });

  it("숨김 상태(층 규모에서 검증 미통과) 스냅샷 — 비율·신뢰구간 없이 방법론 링크만 (T-019b)", () => {
    const { container } = render(
      <BaseRateCard baseRate={hidden("not_confirmed_for_floor_scale")} />,
    );
    expect(container.innerHTML).toMatchSnapshot();
    expect(container.textContent).toContain(
      "이 정도 규모의 층에서는 과거 폐업 횟수와 폐업률의 관계가 검증 기준을 통과하지 못했어요",
    );
    expect(container.textContent).not.toMatch(/\d+\.\d%|신뢰구간/);
    expect(screen.getByRole("link", { name: "어떻게 계산했나요?" })).toBeTruthy();
  });

  it("아직 계산 전(null)", () => {
    const { container } = render(<BaseRateCard baseRate={null} />);
    expect(container.textContent).toContain("이 자리의 통계는 아직 준비 중이에요.");
  });

  it.each([
    ["small", "여러 점포가 함께 있던 층(2~9곳)"],
    ["large", "점포가 많은 층(10곳 이상)"],
  ] as const)("층 규모 문구 %s", (scale, label) => {
    const { container } = render(<BaseRateCard baseRate={{ ...SHOWN, floor_scale: scale }} />);
    expect(container.textContent).toContain(`가상구 ${label} 612곳 기준`);
  });

  it("기준선이 서울로 대체되면 범위를 밝힌다", () => {
    const baseRate = { ...SHOWN, baseline: { ...SHOWN.baseline!, scope_code: "11" } };
    const { container } = render(<BaseRateCard baseRate={baseRate} />);
    expect(container.textContent).toContain("과거 폐업이 없던 자리는 29.5%였어요 (서울 기준).");
  });

  it("버킷 0이면 비교 문장을 되풀이하지 않는다", () => {
    const { container } = render(<BaseRateCard baseRate={{ ...SHOWN, bucket: "0" }} />);
    expect(container.textContent).toContain("과거 폐업이 0회인 자리");
    expect(container.textContent).not.toContain("과거 폐업이 없던 자리는");
  });

  it("버킷 문구", () => {
    expect(["0", "1", "2", "3", "4+"].map(bucketLabel)).toEqual([
      "0회",
      "1회",
      "2회",
      "3회",
      "4회 이상",
    ]);
    expect(() => bucketLabel("5")).toThrow(RangeError);
  });
});
