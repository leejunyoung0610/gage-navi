// @vitest-environment jsdom
/**
 * AddressSearch 컴포넌트 테스트 (docs/40 §4.2, T-032 수용 기준).
 * 주소·좌표·PNU는 모두 가상 예시다. API는 fetch 목, 카카오 지도 SDK는 모듈 목으로 바꾼다.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AddressSearch } from "@/components/AddressSearch";
import type { AddressItem } from "@/lib/address";

type ClickHandler = (event: { latLng: { getLat(): number; getLng(): number } }) => void;
const sdk = vi.hoisted(() => ({ click: null as ClickHandler | null }));

vi.mock("@/lib/kakao-maps", () => {
  class LatLng {
    constructor(
      private lat: number,
      private lng: number,
    ) {}
    getLat() {
      return this.lat;
    }
    getLng() {
      return this.lng;
    }
  }
  class FakeMap {
    setCenter() {}
  }
  class Marker {
    setPosition() {}
    setMap() {}
  }
  const maps = {
    LatLng,
    Map: FakeMap,
    Marker,
    event: {
      addListener: (_target: unknown, _type: string, handler: ClickHandler) => {
        sdk.click = handler;
      },
    },
    load: (callback: () => void) => callback(),
  };
  return { loadKakaoMaps: () => Promise.resolve(maps) };
});

const API = "http://api.example.test"; // 가상 예시
const PNU = "1121510700100470001"; // 가상 예시
const LAT = 37.123456; // 가상 예시 좌표
const LNG = 127.654321;

const item = (overrides: Partial<AddressItem> = {}): AddressItem => ({
  road_addr: "가상시 가상구 가상로 12",
  jibun_addr: "가상시 가상구 가상동 47-1",
  building_name: "가상빌딩",
  pnu: PNU,
  has_history: true,
  related_pnus: [],
  related_with_history: [],
  ...overrides,
});

const REVERSE_DATA = { pnu: PNU, items: [item({ related_pnus: ["1121510700100040003"] })] };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const ok = (data: unknown) => json(200, { data, meta: { request_id: "가상" } });
const fail = (status: number) =>
  json(status, {
    error: { code: "X", message: "가상", details: {} },
    meta: { request_id: "가상" },
  });

let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;
let onSelect: ReturnType<typeof vi.fn<(item: AddressItem) => void>>;

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AddressSearch onSelect={onSelect} />
    </QueryClientProvider>,
  );
}

function type(text: string) {
  fireEvent.change(screen.getByLabelText("주소"), { target: { value: text } });
}

function stubGeolocation(options: {
  permission?: PermissionState;
  getCurrentPosition?: Geolocation["getCurrentPosition"];
}) {
  Object.defineProperty(navigator, "geolocation", {
    configurable: true,
    value: {
      getCurrentPosition:
        options.getCurrentPosition ??
        ((success: PositionCallback) =>
          success({ coords: { latitude: LAT, longitude: LNG } } as GeolocationPosition)),
    },
  });
  Object.defineProperty(navigator, "permissions", {
    configurable: true,
    value: { query: () => Promise.resolve({ state: options.permission ?? "prompt" }) },
  });
}

function calledUrls(): URL[] {
  return fetchMock.mock.calls.map(([url]) => new URL(String(url)));
}

const results = () => screen.findByRole("list", { name: "주소 결과" });

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", API);
  fetchMock = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", fetchMock);
  onSelect = vi.fn<(item: AddressItem) => void>();
  sdk.click = null;
  stubGeolocation({});
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("주소 검색 상태 (docs/40 §4.2)", () => {
  it("로딩: 스켈레톤 3줄", async () => {
    fetchMock.mockReturnValue(new Promise(() => {}));
    setup();
    type("가상로 12");
    const skeleton = await screen.findByRole("status", { name: "불러오는 중" });
    expect(skeleton.children).toHaveLength(3);
  });

  it("2자 이상에서 디바운스 뒤 한 번 부른다", async () => {
    fetchMock.mockResolvedValue(ok({ items: [item()], page: 1, total: 1 }));
    setup();
    type("가");
    type("가상");
    type("가상로");
    await results();
    expect(calledUrls()).toHaveLength(1);
    const url = calledUrls()[0]!;
    expect(url.pathname).toBe("/api/v1/address/search");
    expect(url.searchParams.get("q")).toBe("가상로");
  });

  it("결과 없음: 안내 문구와 지도에서 고르기 안내", async () => {
    fetchMock.mockResolvedValue(ok({ items: [], page: 1, total: 0 }));
    setup();
    type("가상로 999");
    expect(await screen.findByText("주소를 조금 더 자세히 입력해 주세요")).toBeTruthy();
    expect(screen.getByText("주소로 찾기 어려우면 지도에서 골라 주세요.")).toBeTruthy();
  });

  it("검색어를 API가 받지 않으면(422) 결과 없음과 같다", async () => {
    fetchMock.mockResolvedValue(fail(422));
    setup();
    type("가상특별시");
    expect(await screen.findByText("주소를 조금 더 자세히 입력해 주세요")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "다시 시도" })).toBeNull();
  });

  it("오류: 재시도 버튼으로 다시 불러온다", async () => {
    fetchMock
      .mockResolvedValueOnce(fail(502))
      .mockResolvedValueOnce(ok({ items: [item()], page: 1, total: 1 }));
    setup();
    type("가상로 12");
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("주소를 불러오지 못했어요.")).toBeTruthy();
    expect(within(alert).getByText("주소로 찾기 어려우면 지도에서 골라 주세요.")).toBeTruthy();
    fireEvent.click(within(alert).getByRole("button", { name: "다시 시도" }));
    expect(await results()).toBeTruthy();
    expect(calledUrls()).toHaveLength(2);
  });

  it("이력 없음: 회색 + '식품 업소 기록 없음'", async () => {
    fetchMock.mockResolvedValue(
      ok({
        items: [
          item(),
          item({
            road_addr: "가상시 가상구 가상로 14",
            pnu: "1121510700100480000",
            has_history: false,
          }),
        ],
        page: 1,
        total: 2,
      }),
    );
    setup();
    type("가상로");
    const buttons = within(await results()).getAllByRole("button");
    expect(within(buttons[0]!).queryByText("식품 업소 기록 없음")).toBeNull();
    expect(within(buttons[1]!).getByText("식품 업소 기록 없음")).toBeTruthy();
    expect(buttons[1]!.className).toContain("text-muted");
  });

  it("필지를 모르는 항목은 고를 수 없다", async () => {
    fetchMock.mockResolvedValue(
      ok({ items: [item({ pnu: null, has_history: null })], page: 1, total: 1 }),
    );
    setup();
    type("가상로");
    const button = within(await results()).getByRole("button");
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(within(button).getByText("이 주소는 필지를 확인하지 못했어요")).toBeTruthy();
  });

  it("항목을 누르면 onSelect", async () => {
    fetchMock.mockResolvedValue(ok({ items: [item()], page: 1, total: 1 }));
    setup();
    type("가상로");
    fireEvent.click(within(await results()).getByRole("button"));
    expect(onSelect).toHaveBeenCalledWith(item());
  });
});

describe("현재 위치로 찾기", () => {
  it("좌표로 /address/reverse를 부르고 결과를 보여준다", async () => {
    fetchMock.mockResolvedValue(ok(REVERSE_DATA));
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "현재 위치로 찾기" }));
    expect(within(await results()).getByText("가상빌딩")).toBeTruthy();
    const url = calledUrls()[0]!;
    expect(url.pathname).toBe("/api/v1/address/reverse");
    expect([url.searchParams.get("lat"), url.searchParams.get("lng")]).toEqual([
      String(LAT),
      String(LNG),
    ]);
  });

  it("권한이 이미 거부돼 있으면 버튼을 숨기고, 지도에서 고르기는 남는다", async () => {
    stubGeolocation({ permission: "denied" });
    setup();
    expect(await screen.findByRole("button", { name: "지도에서 고르기" })).toBeTruthy();
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "현재 위치로 찾기" })).toBeNull();
    });
  });

  it("누른 뒤 권한을 거부하면 버튼을 숨기고 앱 안에 안내한다 (alert 없음)", async () => {
    const alertSpy = vi.fn();
    vi.stubGlobal("alert", alertSpy);
    stubGeolocation({
      getCurrentPosition: (_success, error) =>
        error?.({ code: 1, PERMISSION_DENIED: 1 } as GeolocationPositionError),
    });
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "현재 위치로 찾기" }));
    expect(
      await screen.findByText("위치 권한이 꺼져 있어요. 주소를 입력하거나 지도에서 골라 주세요."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "현재 위치로 찾기" })).toBeNull();
    expect(screen.getByRole("button", { name: "지도에서 고르기" })).toBeTruthy();
    expect(alertSpy).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("Geolocation이 없으면 버튼이 없다", async () => {
    Object.defineProperty(navigator, "geolocation", { configurable: true, value: undefined });
    // `"geolocation" in navigator`가 거짓이 되도록 지운다
    delete (navigator as { geolocation?: unknown }).geolocation;
    setup();
    expect(await screen.findByRole("button", { name: "지도에서 고르기" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "현재 위치로 찾기" })).toBeNull();
  });
});

describe("지도에서 고르기 (지도 SDK는 목)", () => {
  async function pickOnMap(lat: number, lng: number) {
    fireEvent.click(screen.getByRole("button", { name: "지도에서 고르기" }));
    await waitFor(() => expect(sdk.click).not.toBeNull());
    sdk.click!({ latLng: { getLat: () => lat, getLng: () => lng } });
  }

  it("찍은 좌표로 /address/reverse를 부르고 현재 위치로 찾기와 같은 결과를 보여준다", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(ok(REVERSE_DATA)));

    setup();
    fireEvent.click(await screen.findByRole("button", { name: "현재 위치로 찾기" }));
    const byLocation = (await results()).innerHTML;
    cleanup();

    setup();
    await pickOnMap(LAT, LNG);
    const byMap = (await results()).innerHTML;

    expect(byMap).toBe(byLocation);
    const [first, second] = calledUrls();
    expect(second!.pathname).toBe("/api/v1/address/reverse");
    expect(second!.search).toBe(first!.search);
  });

  it("위치 권한을 거부해도 지도에서 고를 수 있다", async () => {
    stubGeolocation({ permission: "denied" });
    fetchMock.mockResolvedValue(ok(REVERSE_DATA));
    setup();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "현재 위치로 찾기" })).toBeNull(),
    );
    await pickOnMap(LAT, LNG);
    expect(within(await results()).getByText("가상빌딩")).toBeTruthy();
  });

  it("그 지점의 필지를 모르면(pnu null) 다시 찍어 달라고 안내한다", async () => {
    fetchMock.mockResolvedValue(ok({ pnu: null, items: [] }));
    setup();
    await pickOnMap(LAT, LNG);
    expect(
      await screen.findByText("이 지점에서는 필지를 찾지 못했어요. 건물 위를 다시 찍어 주세요."),
    ).toBeTruthy();
  });

  it("한 필지에 건물이 여러 개면 모두 보여준다", async () => {
    fetchMock.mockResolvedValue(
      ok({ pnu: PNU, items: [item(), item({ building_name: "가상별관" })] }),
    );
    setup();
    await pickOnMap(LAT, LNG);
    expect(within(await results()).getAllByRole("button")).toHaveLength(2);
  });

  it("오류면 재시도 버튼이 같은 좌표로 다시 부른다", async () => {
    fetchMock.mockResolvedValueOnce(fail(502)).mockResolvedValueOnce(ok(REVERSE_DATA));
    setup();
    await pickOnMap(LAT, LNG);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("위치로 주소를 찾지 못했어요.")).toBeTruthy();
    fireEvent.click(within(alert).getByRole("button", { name: "다시 시도" }));
    expect(await results()).toBeTruthy();
    const [first, second] = calledUrls();
    expect(second!.search).toBe(first!.search);
  });
});

describe("related_pnus: null(확인 못 함)과 [](확인했고 없음)을 구분한다", () => {
  const RELATED_UNKNOWN = "같은 건물의 다른 필지 기록은 확인하지 못했어요.";

  it("null이면 확인하지 못했다는 안내", async () => {
    fetchMock.mockResolvedValue(ok({ pnu: PNU, items: [item({ related_pnus: null })] }));
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "현재 위치로 찾기" }));
    expect(within(await results()).getByText(RELATED_UNKNOWN)).toBeTruthy();
  });

  it("[]이면 안내하지 않는다", async () => {
    fetchMock.mockResolvedValue(ok({ pnu: PNU, items: [item({ related_pnus: [] })] }));
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "현재 위치로 찾기" }));
    await results();
    expect(screen.queryByText(RELATED_UNKNOWN)).toBeNull();
  });

  it("도로명 주소가 null이면 지번 주소만 보여준다", async () => {
    fetchMock.mockResolvedValue(
      ok({
        pnu: PNU,
        items: [item({ road_addr: null, building_name: null, related_pnus: null })],
      }),
    );
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "현재 위치로 찾기" }));
    const button = within(await results()).getByRole("button");
    expect(button.textContent).toBe("가상시 가상구 가상동 47-1");
  });
});
