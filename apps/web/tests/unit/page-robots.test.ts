import type { Metadata } from "next";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FloorData, Lookup, PlaceData } from "@/lib/place";

// 가상 예시: 주소·필지 번호·건수는 형식 설명용 (운영 도메인은 T-081)
const SITE = "https://site.example.test";
const PNU = "1121510700100470001";

const place = vi.hoisted(() => ({
  fetchFloor: vi.fn<(pnu: string, floor: string) => Promise<Lookup<FloorData>>>(),
  fetchPlace: vi.fn<(pnu: string) => Promise<Lookup<PlaceData>>>(),
}));
vi.mock("@/lib/place", async (original) => ({ ...(await original()), ...place }));

const INDEX = { index: true, follow: true };
const NOINDEX = { index: false, follow: false };

function floorResult(recordCount: number): Lookup<FloorData> {
  const data = {
    pnu: PNU,
    floor: "1",
    jibun_label: "서울특별시 가상구 가상동 47-1",
    summary: { record_count: recordCount },
  } as FloorData;
  return { kind: "ok", data, dataAsOf: "2026-10-07" };
}

function placeResult(): Lookup<PlaceData> {
  const data = { pnu: PNU, jibun_label: "서울특별시 가상구 가상동 47-1" } as PlaceData;
  return { kind: "ok", data, dataAsOf: "2026-10-07" };
}

/** 모듈 수준 `metadata`는 불러올 때 정해지므로 환경 변수를 바꾼 뒤 새로 불러온다 */
async function load(enabled: string, site: string) {
  vi.stubEnv("INDEXING_ENABLED", enabled);
  vi.stubEnv("SITE_URL", site);
  vi.resetModules();
  const [layout, home, methodology, floorPage, placePage] = await Promise.all([
    import("@/app/layout"),
    import("@/app/page"),
    import("@/app/methodology/page"),
    import("@/app/place/[pnu]/[floor]/page"),
    import("@/app/place/[pnu]/page"),
  ]);
  const floorRobots = async (recordCount: number) => {
    place.fetchFloor.mockResolvedValueOnce(floorResult(recordCount));
    const meta: Metadata = await floorPage.generateMetadata({
      params: Promise.resolve({ pnu: PNU, floor: "1" }),
    });
    return meta.robots;
  };
  place.fetchPlace.mockResolvedValue(placeResult());
  const parcel: Metadata = await placePage.generateMetadata({
    params: Promise.resolve({ pnu: PNU }),
  });
  return {
    layout: layout.metadata.robots,
    home: home.metadata.robots,
    methodology: methodology.metadata.robots,
    parcel: parcel.robots,
    floorRobots,
  };
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("페이지별 robots 메타 (docs/40 §9)", () => {
  it.each([
    ["false", SITE],
    ["true", ""],
  ])("INDEXING_ENABLED=%j, SITE_URL=%j → 모든 페이지 noindex", async (enabled, site) => {
    const pages = await load(enabled, site);
    expect(pages.layout).toEqual(NOINDEX);
    expect(pages.home).toEqual(NOINDEX);
    expect(pages.methodology).toEqual(NOINDEX);
    expect(await pages.floorRobots(5)).toEqual(NOINDEX);
    expect(pages.parcel ?? pages.layout).toEqual(NOINDEX);
  });

  it("켜지면 홈·방법론·기록 2건 이상 층만 index, 나머지는 noindex", async () => {
    const pages = await load("true", SITE);
    expect(pages.home).toEqual(INDEX);
    expect(pages.methodology).toEqual(INDEX);
    expect(await pages.floorRobots(2)).toEqual(INDEX);
    expect(await pages.floorRobots(1)).toEqual(NOINDEX);
    // 필지 페이지·정정 요청·/privacy 등은 레이아웃 기본값(noindex)을 따른다
    expect(pages.parcel).toBeUndefined();
    expect(pages.layout).toEqual(NOINDEX);
  });

  it("층에 기록이 없으면(404) 레이아웃 기본값(noindex)", async () => {
    vi.stubEnv("INDEXING_ENABLED", "true");
    vi.stubEnv("SITE_URL", SITE);
    const floorPage = await import("@/app/place/[pnu]/[floor]/page");
    place.fetchFloor.mockResolvedValueOnce({ kind: "no_history" });
    const meta = await floorPage.generateMetadata({
      params: Promise.resolve({ pnu: PNU, floor: "9" }),
    });
    expect(meta.robots).toBeUndefined();
  });
});
