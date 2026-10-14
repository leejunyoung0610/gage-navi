import { describe, expect, it } from "vitest";

import {
  formatDate,
  formatMonths,
  formatPeriod,
  formatRate,
  formatRateCi,
  formatWon,
} from "@/lib/format";

// docs/40 §6 예시를 그대로 옮긴다
describe("docs/40 §6 예시", () => {
  it.each([
    [30000000, "3,000만 원"],
    [450000, "45만 원"],
    [120000000, "1억 2,000만 원"],
  ])("금액 %i → %s", (won, expected) => {
    expect(formatWon(won)).toBe(expected);
  });

  it("비율은 소수 첫째 자리: 0.4340 → 43.4%", () => {
    expect(formatRate("0.4340")).toBe("43.4%");
  });

  it("신뢰구간: (95% 신뢰구간 39.2~47.1%)", () => {
    expect(formatRateCi(["0.3920", "0.4710"])).toBe("(95% 신뢰구간 39.2~47.1%)");
  });

  it("날짜: 2026년 11월 20일", () => {
    expect(formatDate("2026-11-20")).toBe("2026년 11월 20일");
  });

  it("타임라인 기간: 2011.03 – 2013.08", () => {
    expect(formatPeriod("2011-03-15", "2013-08-02")).toBe("2011.03 – 2013.08");
  });

  it("기간 길이: 2년 5개월", () => {
    expect(formatMonths(29)).toBe("2년 5개월");
  });
});

describe("formatWon", () => {
  it.each([
    [0, "0원"],
    [5000, "5,000원"],
    [10000, "1만 원"],
    [12345678, "1,234만 5,678원"],
    [100000000, "1억 원"],
    [100005000, "1억 5,000원"],
    [1200000000000, "1조 2,000억 원"],
    [-450000, "-45만 원"],
  ])("%i → %s", (won, expected) => {
    expect(formatWon(won)).toBe(expected);
  });

  it.each([1.5, Number.NaN, Number.MAX_SAFE_INTEGER + 1])(
    "원 단위 정수가 아니면 오류: %s",
    (won) => {
      expect(() => formatWon(won)).toThrow(RangeError);
    },
  );
});

describe("formatRate", () => {
  it.each([
    ["0", "0.0%"],
    ["1", "100.0%"],
    ["0.4345", "43.5%"], // 반올림(0.5는 올림)
    ["0.43449", "43.4%"],
    ["0.9999", "100.0%"],
    ["0.05", "5.0%"],
    ["0.2950", "29.5%"],
  ])("%s → %s", (rate, expected) => {
    expect(formatRate(rate)).toBe(expected);
  });

  it.each(["", "abc", "-0.1", "1.2.3", "0.4e1"])("소수 문자열이 아니면 오류: %j", (rate) => {
    expect(() => formatRate(rate)).toThrow(RangeError);
  });
});

describe("formatDate", () => {
  it("월·일 앞의 0을 뗀다", () => {
    expect(formatDate("2026-01-05")).toBe("2026년 1월 5일");
  });

  it.each(["2026-13-01", "2026-02-30", "20261120", "2026-11-20T00:00:00"])(
    "날짜 형식이 아니면 오류: %s",
    (value) => {
      expect(() => formatDate(value)).toThrow(RangeError);
    },
  );
});

describe("formatMonths", () => {
  it.each([
    [0, "0개월"],
    [5, "5개월"],
    [12, "1년"],
    [24, "2년"],
    [13, "1년 1개월"],
  ])("%i → %s", (months, expected) => {
    expect(formatMonths(months)).toBe(expected);
  });

  it.each([-1, 1.5])("0 이상의 정수가 아니면 오류: %s", (months) => {
    expect(() => formatMonths(months)).toThrow(RangeError);
  });
});
