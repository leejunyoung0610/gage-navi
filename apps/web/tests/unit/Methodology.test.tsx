// @vitest-environment jsdom
/**
 * 방법론 페이지 본문 (docs/40 §4.9, T-034 수용 기준).
 * 응답 값은 모두 가상 예시다 — 실제 측정값과 일부러 다르게 넣어, 화면 숫자가 응답에서 나오는지 본다.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Methodology } from "@/components/Methodology";
import type {
  BucketOut,
  ModelCard,
  ModelCardData,
  ScaleResult,
  SearchMatch,
  SettingResult,
} from "@/lib/methodology";

afterEach(cleanup);

const BUCKETS = ["0", "1", "2", "3", "4+"] as const;

function buckets(zero: string, many: string): BucketOut[] {
  return BUCKETS.map((bucket) => ({
    bucket,
    n: 1000,
    events: 300,
    rate: bucket === "0" ? zero : bucket === "4+" ? many : "0.3500",
    ci: bucket === "0" ? ["0.2001", "0.2201"] : ["0.3001", "0.4001"],
  }));
}

function setting(n: number, zero: string, many: string, or: number, ok = true): SettingResult {
  return {
    is_default: false,
    n,
    event_rate: "0.3000",
    buckets: buckets(zero, many),
    logit: { n: n - 10, or_per_prior: or, ci: [or - 0.01, or + 0.01], p: 0.0004 },
    criterion_a: true,
    criterion_b: ok,
  };
}

function scale(n: number, holds: boolean): ScaleResult {
  return { ...setting(n, "0.2100", "0.4400", holds ? 1.21 : 1.01, holds), holds };
}

// 가상 예시
const CARD: ModelCard = {
  data: {
    snapshot_label: "2031-04",
    license_group: "food3",
    as_of: "2031-04-05",
    cohort_from: "2005-01-01",
    cohort_to: "2028-04-06",
    n: 123457,
    event_rate: "0.3333",
  },
  default_setting: {
    bulk_exclusion: "surge_rule",
    convenience_store: "excluded",
    exclude_stale: "none",
    floor_unknown: "all",
  },
  base_rates: buckets("0.2222", "0.5555"),
  logit: {
    n: 120001,
    or_per_prior: 1.2346,
    ci: [1.2001, 1.2701],
    p: 1e-20,
    spec: "가상",
    se: "가상",
    with_other_floor_control: { or_per_prior: 1.3111, ci: [1.3, 1.32], or_other_floor: 0.9871 },
  },
  by_sigungu: [
    { sigungu: "가상구", n: 5001, or: 1.4321, ci: [1.3001, 1.5001] },
    { sigungu: "나상구", n: 4002, or: 0.9123, ci: [0.8001, 1.0501] },
    { sigungu: "다상구", n: 12, or: null, ci: null },
  ],
  out_of_time: { train: "2005-2016", test: "2017-2024", auc_base: 0.5712, auc_with_prior: 0.5788 },
  sensitivity: {
    bulk_exclusion: {
      none: setting(130001, "0.2011", "0.5011", 1.114),
      surge_rule: { ...setting(123457, "0.2222", "0.5555", 1.2345), is_default: true },
      w0_citywide_100: setting(122002, "0.2033", "0.5033", 1.133),
    },
    convenience_store: {
      excluded: setting(123457, "0.2222", "0.5555", 1.2345),
      included: setting(125003, "0.2044", "0.5044", 1.144),
    },
    exclude_stale: {
      none: setting(123457, "0.2222", "0.5555", 1.2345),
      same_ho: setting(121004, "0.2055", "0.5055", 1.155),
      same_ho_or_area: setting(120005, "0.2066", "0.5066", 1.166),
    },
    floor_unknown: {
      all: setting(123457, "0.2222", "0.5555", 1.2345),
      exclude_parcels_with_floorless_closure: setting(60006, "0.2077", "0.5077", 1.177, false),
    },
    bulk_as_censored: {
      n: 130001,
      buckets: [
        { bucket: "0", n: 1, censored: 0, rate: 0.21234, ci: [0.2, 0.22] },
        { bucket: "4+", n: 1, censored: 0, rate: 0.54321, ci: [0.53, 0.55] },
      ],
    },
    license_type: {
      general_restaurant: setting(90001, "0.2088", "0.4088", 1.088),
      rest_restaurant: setting(30002, "0.2099", "0.6099", 1.199),
      bakery: setting(3003, "0.2111", "0.6111", 1.011),
    },
  },
  robustness: { holds: false, failures: [] },
  by_floor_scale: {
    single: scale(80000, true),
    small: scale(30000, true),
    large: scale(20000, false),
  },
  by_floor_scale_full_history: null,
  floor_record_count: null,
  single_with_open_neighbor: null,
};
CARD.by_floor_scale!.large.buckets[4]!.n = 15000; // 대형의 4회 이상 15,000 / 20,000 = 75.0%

// 가상 예시
const MATCH: SearchMatch = {
  measured_on: "2031-03-02",
  seed: 1,
  remeasure: false,
  population: 98765,
  sample_size: 1500,
  judged: { matched: 1401, rate: "0.9340", ci: ["0.9201", "0.9461"] },
  reference: { matched: 1350, rate: "0.9000", ci: ["0.8841", "0.9141"] },
  related_only: { count: 51, share: "0.0340" },
  failures: [
    { type: "keyword_error", count: 0, share: "0.0000" },
    { type: "transport_error", count: 0, share: "0.0000" },
    { type: "no_result", count: 60, share: "0.0400" },
    { type: "jibun_changed", count: 27, share: "0.0180" },
    { type: "other", count: 12, share: "0.0080" },
  ],
  by_open_year: [
    {
      band: "1999년 이전",
      n: 100,
      matched: 81,
      rate: "0.8100",
      ci: ["0.7201", "0.8701"],
      reference_rate: "0.7900",
    },
    {
      band: "2021년 이후",
      n: 900,
      matched: 891,
      rate: "0.9900",
      ci: ["0.9801", "0.9951"],
      reference_rate: "0.9800",
    },
    {
      band: "개업일 없음",
      n: 5,
      matched: 1,
      rate: "0.2000",
      ci: ["0.0401", "0.6201"],
      reference_rate: "0.2000",
    },
  ],
};

const DATA: ModelCardData = { method_version: "2031.1.1", model_card: CARD, search_match: MATCH };

function section(name: string): HTMLElement {
  return screen.getByRole("region", { name });
}

describe("방법론 페이지 (docs/40 §4.9)", () => {
  it("§4.9의 섹션을 모두 보여줘요", () => {
    render(<Methodology data={DATA} />);
    for (const name of [
      "데이터 출처와 기준일",
      "주소 검색으로 필지를 찾는 정확도",
      "자리(층)를 어떻게 정했나요",
      "과거 폐업 횟수와 3년 내 폐업",
      "폐업 처리가 몰린 날",
      "설정을 하나씩 바꿔 본 결과",
      "결과",
      "한계",
      "갱신 주기",
    ]) {
      expect(section(name)).toBeTruthy();
    }
  });

  it("검색 일치율: 판정용·참고용 값과 신뢰구간, 측정일·표본, 개업연도별, 지번 변경(추정)", () => {
    render(<Methodology data={DATA} />);
    const text = section("주소 검색으로 필지를 찾는 정확도").textContent ?? "";
    expect(text).toContain("93.4%");
    expect(text).toContain("(92.0~94.6%)");
    expect(text).toContain("90.0%");
    expect(text).toContain("(88.4~91.4%)");
    expect(text).toContain("2031년 3월 2일에 측정, 대상 기록 98,765건 중 1,500건");
    expect(text).toContain("51건(3.4%)");
    expect(text).toContain("1999년 이전 개업 기록은 81.0%, 2021년 이후 개업 기록은 99.0%였어요");
    expect(text).toContain("27건(1.8%)");
    expect(text).toContain("가를 수 없어요");
  });

  it("결과: 기준율 표, 로지스틱, 층 규모별 판정, 시군구 점그래프", () => {
    render(<Methodology data={DATA} />);
    const results = section("결과");
    const text = results.textContent ?? "";
    expect(text).toContain("대상 123,457건 중 3년 안에 폐업한 비율은 33.3%예요");
    expect(text).toContain("55.6%"); // 기준율 표 4회 이상
    expect(text).toContain("1.235배였어요(95% 신뢰구간 1.200~1.270, p 0.001 미만, 120,001건)");
    expect(text).toContain("점포가 많은 층(10곳 이상)에서는 검증 기준을 통과하지 못해서");
    expect(text).toContain("시군구 3곳 중 1곳에서 1회당 오즈비가 1보다 컸고");
    const plot = within(results).getByRole("list", { name: "시군구별 과거 폐업 1회당 오즈비" });
    expect(plot.textContent).toContain("1.432 (1.300~1.500, 5,001건)");
    expect(plot.textContent).toContain("다상구계산하지 못했어요 (12건)");
  });

  it("시간 외 검증 AUC와 '개별 예측력은 매우 작다'", () => {
    render(<Methodology data={DATA} />);
    const text = section("결과").textContent ?? "";
    expect(text).toContain("개별 예측력은 매우 작아요");
    expect(text).toContain("시간 외 검증 AUC가 0.571 → 0.579예요");
    expect(text).toContain("2005-2016년에 문을 연 가게로 모형을 만들고 2017-2024년");
    expect(text).toContain("가려내는 힘은 매우 작아요");
  });

  it("설정별 결과와 폐업 처리 몰린 날 세 가지 비교", () => {
    render(<Methodology data={DATA} />);
    const sensitivity = section("설정을 하나씩 바꿔 본 결과").textContent ?? "";
    expect(sensitivity).toContain("두 기준을 만족하지 못한 설정이 있어요.");
    expect(sensitivity).toContain("유지 안 됨");
    expect(sensitivity).toContain("60,006");
    const surge = section("폐업 처리가 몰린 날").textContent ?? "";
    for (const value of ["130,001", "122,002", "1.114", "1.133", "21.2%", "54.3%"]) {
      expect(surge).toContain(value);
    }
  });

  it("한계·출처·갱신 주기의 숫자도 응답에서 만들어요", () => {
    render(<Methodology data={DATA} />);
    expect(section("한계").textContent).toContain("대상 20,000건 중 75.0%가 과거 폐업 4회 이상");
    expect(section("데이터 출처와 기준일").textContent).toContain(
      "통계 기준일은 2031년 4월 5일이에요(2031년 4월 데이터)",
    );
    expect(section("갱신 주기").textContent).toContain(
      "2031년 4월 데이터, 계산 방법 버전 2031.1.1",
    );
    expect(section("과거 폐업 횟수와 3년 내 폐업").textContent).toContain(
      "2005년 1월 1일부터 2028년 4월 6일까지 문을 연 가게 123,457건",
    );
  });

  it("실제 측정값을 하드코딩하지 않아요 (가상 응답에는 그 숫자가 없다)", () => {
    const { container } = render(<Methodology data={DATA} />);
    const text = container.textContent ?? "";
    // 2026-10 실제 값: 검색 판정용 95.85%·참고용 94.25%, 지번 변경 31건, AUC 0.619·0.624, OR 1.101
    for (const real of ["95.9%", "94.3%", "31건", "0.619", "0.624", "1.101", "250,131"]) {
      expect(text).not.toContain(real);
    }
  });

  it("아직 계산하지 않았으면 그렇게 말하고 정의·한계는 보여줘요", () => {
    render(<Methodology data={{ method_version: null, model_card: null, search_match: null }} />);
    expect(section("주소 검색으로 필지를 찾는 정확도").textContent).toContain(
      "아직 계산하지 않았어요.",
    );
    expect(section("결과").textContent).toContain("아직 계산하지 않았어요.");
    expect(section("한계").textContent).toContain("신고된 사실만");
    expect(section("자리(층)를 어떻게 정했나요").textContent).toContain(
      "필지(지번) 하나의 층 하나",
    );
  });

  it("금지 표현을 쓰지 않아요 (docs/40 §6)", () => {
    const { container } = render(<Methodology data={DATA} />);
    const text = container.textContent ?? "";
    for (const banned of [
      "망한 자리",
      "위험한 자리",
      "저주",
      "흉지",
      "대박",
      "승인 보장",
      "대출 확정",
      "100%",
      "무조건",
      "누구나",
      "행정 일괄 정리",
    ]) {
      expect(text).not.toContain(banned);
    }
  });
});
