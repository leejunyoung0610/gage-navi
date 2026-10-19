// @vitest-environment jsdom
/**
 * 필지·층 페이지 부품 (docs/40 §4.3·4.4, T-033): 관련 필지, 정책자금 링크, 알림.
 * PNU·주소는 모두 가상 예시다.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FundingLink } from "@/components/FundingLink";
import { NOTICE_TEXT, PlaceNotices } from "@/components/PlaceNotices";
import { RelatedParcels } from "@/components/RelatedParcels";
import type { AddressItem } from "@/lib/address";
import { findRelatedParcels } from "@/lib/place";
import { PROFILE_STORAGE_KEY } from "@/lib/profile-store";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const API = "http://api.example.test"; // 가상 예시
const PNU = "1121510700100470001";
const OTHER = "1121510800200120000";
const THIRD = "1121510700100040003";
const LABEL = "가상시 가상구 가상동 47-1";

const item = (overrides: Partial<AddressItem> = {}): AddressItem => ({
  road_addr: "가상시 가상구 가상로 12",
  jibun_addr: LABEL,
  building_name: null,
  pnu: PNU,
  has_history: true,
  related_pnus: [OTHER],
  related_with_history: [{ pnu: OTHER, jibun_label: "가상시 가상구 다른동 산 12" }],
  ...overrides,
});

const fetchMock = vi.fn();
const answer = (items: AddressItem[]) =>
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify({ data: { items, page: 1, total: items.length } })),
  );

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", API);
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  fetchMock.mockReset();
  push.mockReset();
  localStorage.clear();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("findRelatedParcels — 주소 검색 재호출 (docs/40 §4.3)", () => {
  it("필지의 지번으로 검색하고, 같은 PNU 항목들의 목록을 합친다(순서·중복·자기 자신)", async () => {
    answer([
      item(),
      item({ pnu: "1121510700100990000", related_with_history: [{ pnu: "9", jibun_label: "x" }] }),
      item({
        related_with_history: [
          { pnu: PNU, jibun_label: LABEL },
          { pnu: OTHER, jibun_label: "가상시 가상구 다른동 산 12" },
          { pnu: THIRD, jibun_label: "가상시 가상구 가상동 4-3" },
        ],
      }),
    ]);
    expect(await findRelatedParcels(PNU, LABEL)).toEqual([
      { pnu: OTHER, jibun_label: "가상시 가상구 다른동 산 12" },
      { pnu: THIRD, jibun_label: "가상시 가상구 가상동 4-3" },
    ]);
    expect(String(fetchMock.mock.calls[0]![0])).toBe(
      `${API}/api/v1/address/search?q=${encodeURIComponent(LABEL).replace(/%20/g, "+")}`,
    );
  });

  it("같은 PNU가 없거나 값이 null이면 null(확인 못 함)", async () => {
    answer([item({ pnu: OTHER })]);
    expect(await findRelatedParcels(PNU, LABEL)).toBeNull();
    answer([item({ related_pnus: null, related_with_history: null })]);
    expect(await findRelatedParcels(PNU, LABEL)).toBeNull();
  });
});

function renderRelated() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <RelatedParcels pnu={PNU} jibunLabel={LABEL} />
    </QueryClientProvider>,
  );
}

describe("RelatedParcels", () => {
  it("기록이 있는 관련 필지를 /place/{pnu} 링크로", async () => {
    answer([item()]);
    renderRelated();
    const link = await screen.findByRole("link", { name: "가상시 가상구 다른동 산 12" });
    expect(link.getAttribute("href")).toBe(`/place/${OTHER}`);
  });

  it("빈 목록이면 아무것도 그리지 않는다", async () => {
    answer([item({ related_pnus: [], related_with_history: [] })]);
    const { container } = renderRelated();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container.textContent).toBe("");
  });

  it.each([
    ["검색 실패", () => fetchMock.mockResolvedValue(new Response("{}", { status: 502 }))],
    ["같은 PNU 없음", () => answer([item({ pnu: OTHER })])],
  ])("%s → 확인하지 못했어요", async (_name, setup) => {
    setup();
    renderRelated();
    await screen.findByText("같은 건물의 다른 필지 기록은 확인하지 못했어요.");
  });
});

describe("FundingLink (docs/40 §4.4-6)", () => {
  it("프로필에 시도·시군구 코드를 저장하고 /funding으로", () => {
    localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify({ schema_version: 1 }));
    render(<FundingLink pnu={PNU} />);
    fireEvent.click(screen.getByRole("button", { name: "이 자리로 정책자금 알아보기" }));
    expect(JSON.parse(localStorage.getItem(PROFILE_STORAGE_KEY)!)).toEqual({
      schema_version: 1,
      region: { sido_code: "11", sigungu_code: "11215" },
    });
    expect(push).toHaveBeenCalledWith("/funding");
  });

  it("저장소가 막혀도 이동한다", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("막힘 (가상 예시)", "QuotaExceededError");
    });
    render(<FundingLink pnu={PNU} />);
    fireEvent.click(screen.getByRole("button", { name: "이 자리로 정책자금 알아보기" }));
    expect(push).toHaveBeenCalledWith("/funding");
    vi.restoreAllMocks();
  });
});

describe("PlaceNotices (docs/40 §4.4-4)", () => {
  it("아는 알림만, 층 정보 누락은 필지 페이지 링크와 함께", () => {
    render(
      <PlaceNotices
        pnu={PNU}
        notices={["multiple_units_possible", "unknown_value", "pre_2005_floor_missing"]}
      />,
    );
    const list = screen.getAllByRole("listitem");
    expect(list).toHaveLength(2);
    expect(list[0]!.textContent).toBe(NOTICE_TEXT.multiple_units_possible);
    expect(screen.getByRole("link", { name: "필지 페이지 보기" }).getAttribute("href")).toBe(
      `/place/${PNU}`,
    );
  });

  it("알림이 없으면 그리지 않는다", () => {
    const { container } = render(<PlaceNotices pnu={PNU} notices={[]} />);
    expect(container.innerHTML).toBe("");
  });
});
