// @vitest-environment jsdom
/**
 * FloorTimeline (docs/40 §4.4-5, T-033 수용 기준 "같은 호수 그룹 색 일치").
 * 상호·날짜·호수는 모두 가상 예시다.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FloorTimeline, INITIAL_COUNT, type TimelineRecord } from "@/components/FloorTimeline";
import { HO_GROUP_COLORS, hoMarks } from "@/lib/place";

afterEach(cleanup);

const AS_OF = "2026-11-01"; // 가상 예시 기준일

let nextId = 1000;
const record = (overrides: Partial<TimelineRecord> = {}): TimelineRecord => ({
  record_id: nextId++,
  name: "가상분식",
  license_type: "general_restaurant",
  biz_category: "분식",
  opened_on: "2011-03-02",
  closed_on: "2013-08-30",
  status: "closed",
  tenure_days: 912,
  ho_list: [],
  bulk_closure: false,
  bulk_closure_detail: null,
  stale_suspect: false,
  ...overrides,
});

const items = () => screen.getAllByRole("listitem");
const dotColors = (item: HTMLElement) =>
  within(item)
    .queryAllByTestId("ho-dot")
    .map((dot) => dot.style.backgroundColor);

describe("FloorTimeline", () => {
  it("같은 호수 그룹은 같은 색 점과 호수 글자, 다른 그룹은 다른 색", () => {
    const a = record({ record_id: 1, name: "가상가게 가", ho_list: ["101"] });
    const b = record({ record_id: 2, name: "가상가게 나", ho_list: ["102"] });
    const c = record({ record_id: 3, name: "가상가게 다", ho_list: ["101"] });
    const d = record({ record_id: 4, name: "가상가게 라", ho_list: ["102"] });
    const e = record({ record_id: 5, name: "가상가게 마", ho_list: ["103"] }); // 혼자라 그룹 없음
    render(
      <FloorTimeline
        history={[a, b, c, d, e]}
        hoGroups={[
          { ho: "101", record_ids: [1, 3] },
          { ho: "102", record_ids: [2, 4] },
        ]}
        dataAsOf={AS_OF}
        label="층 이력"
      />,
    );
    const [ia, ib, ic, id, ie] = items() as [HTMLElement, ...HTMLElement[]];
    expect(dotColors(ia)).toHaveLength(1);
    expect(dotColors(ia)).toEqual(dotColors(ic!));
    expect(dotColors(ib!)).toEqual(dotColors(id!));
    expect(dotColors(ia)).not.toEqual(dotColors(ib!));
    expect(dotColors(ie!)).toEqual([]);
    // 색만으로 전하지 않는다 — 글자를 함께
    expect(ia.textContent).toContain("같은 호수(101호)로 신고된 기록");
    expect(ib!.textContent).toContain("같은 호수(102호)로 신고된 기록");
  });

  it("한 기록이 두 그룹에 들면 점 두 개", () => {
    const marks = hoMarks([
      { ho: "101", record_ids: [1, 2] },
      { ho: "102", record_ids: [2, 3] },
    ]);
    expect(marks.get(2)?.map((m) => m.ho)).toEqual(["101", "102"]);
    expect(marks.get(1)?.[0]?.color).toBe(HO_GROUP_COLORS[0]);
    expect(marks.get(3)?.[0]?.color).toBe(HO_GROUP_COLORS[1]);
  });

  it(`처음 ${INITIAL_COUNT}건만 그리고, 전체 보기로 나머지를 그린다 — 펼쳐도 그룹 색은 같다`, () => {
    const history = Array.from({ length: 45 }, (_, i) =>
      record({ record_id: i + 1, name: `가상가게 ${i + 1}`, ho_list: ["201"] }),
    );
    render(
      <FloorTimeline
        history={history}
        hoGroups={[{ ho: "201", record_ids: [1, 45] }]}
        dataAsOf={AS_OF}
        label="층 이력"
      />,
    );
    expect(items()).toHaveLength(INITIAL_COUNT);
    const firstColor = dotColors(items()[0]!);
    fireEvent.click(screen.getByRole("button", { name: "전체 보기(45건)" }));
    expect(items()).toHaveLength(45);
    expect(dotColors(items()[44]!)).toEqual(firstColor);
    expect(screen.queryByRole("button", { name: /전체 보기/ })).toBeNull();
  });

  it(`${INITIAL_COUNT}건 이하면 전체 보기 버튼이 없다`, () => {
    render(
      <FloorTimeline
        history={Array.from({ length: INITIAL_COUNT }, () => record())}
        dataAsOf={AS_OF}
        label="층 미상"
      />,
    );
    expect(screen.queryByRole("button", { name: /전체 보기/ })).toBeNull();
  });

  it("기간·기간 길이·업태 (docs/40 §4.4-5)", () => {
    render(
      <FloorTimeline
        history={[
          record({ name: "닫은 가게" }),
          record({
            name: "영업 중 가게",
            opened_on: "2024-05-20",
            closed_on: null,
            status: "open",
          }),
          record({ name: "개업일 모름", opened_on: null, closed_on: null, status: "closed" }),
          record({ name: "끝 모름", closed_on: null, status: "other", biz_category: null }),
        ]}
        dataAsOf={AS_OF}
        label="층 이력"
      />,
    );
    const [closed, open, noOpen, noEnd] = items() as HTMLElement[];
    expect(closed!.textContent).toContain("분식");
    expect(closed!.textContent).toContain("2011.03 – 2013.08 · 2년 5개월");
    expect(open!.textContent).toContain("2024.05 – 지금 · 2년 5개월");
    expect(open!.textContent).toContain("영업 중");
    expect(noOpen!.textContent).toContain("개업일 미상");
    expect(noOpen!.textContent).not.toMatch(/개월/);
    expect(noEnd!.textContent).toContain("2011.03 – 날짜 미상");
    expect(noEnd!.textContent).toContain("일반음식점"); // 업태가 없으면 업종
  });

  it("배지와 설명 — 폐업 처리 몰린 날·같은 호수에 새 신고 (ADR-020, ADR-023)", () => {
    render(
      <FloorTimeline
        history={[
          record({
            bulk_closure: true,
            bulk_closure_detail: { jurisdiction_label: "가상구", closure_count: 412 },
          }),
          record({
            bulk_closure: true,
            bulk_closure_detail: { jurisdiction_label: null, closure_count: 1200 },
          }),
          record({ status: "open", closed_on: null, stale_suspect: true }),
          record({ status: "suspended", closed_on: null }),
        ]}
        dataAsOf={AS_OF}
        label="층 이력"
      />,
    );
    const [bulk, bulkNoName, stale, suspended] = items() as HTMLElement[];
    expect(bulk!.textContent).toContain("폐업 처리 몰린 날");
    expect(bulk!.textContent).toContain(
      "이날 가상구에서 평소보다 훨씬 많은 폐업이 한꺼번에 처리됐어요(412건). 실제로 문을 닫은 날은 더 이를 수 있어요.",
    );
    expect(bulkNoName!.textContent).toContain(
      "이날 평소보다 훨씬 많은 폐업이 한꺼번에 처리됐어요(1,200건).",
    );
    expect(stale!.textContent).toContain("같은 호수에 새 신고");
    expect(stale!.textContent).toContain(
      "같은 호수로 나중에 다른 가게가 영업 신고를 했어요. 이 가게의 폐업 신고가 늦어졌을 수 있어요.",
    );
    expect(suspended!.textContent).toContain("휴업");
    expect(document.body.textContent).not.toContain("행정 일괄 정리");
  });

  it("정정 요청 시트 밖에서는 기록별 정정 버튼을 그리지 않는다", () => {
    render(<FloorTimeline history={[record()]} dataAsOf={AS_OF} label="층 이력" />);
    expect(screen.queryByRole("button", { name: "이 기록 정정 요청" })).toBeNull();
  });
});
