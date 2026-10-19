import { afterEach, describe, expect, it, vi } from "vitest";

import { indexingSiteUrl, isIndexableFloor, pageRobots } from "@/lib/indexing";

// 가상 예시 주소 — 운영 도메인이 아니다(T-081에서 정한다)
const SITE = "https://site.example.test";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("indexingSiteUrl (docs/40 §9)", () => {
  it.each([
    ["false", SITE],
    ["", SITE],
    ["TRUE", SITE],
    ["1", SITE],
  ])("INDEXING_ENABLED=%j이면 꺼져요", (enabled, site) => {
    vi.stubEnv("INDEXING_ENABLED", enabled);
    vi.stubEnv("SITE_URL", site);
    expect(indexingSiteUrl()).toBeNull();
  });

  it.each(["", "   ", "site.example.test", "ftp://site.example.test"])(
    "INDEXING_ENABLED=true여도 SITE_URL=%j이면 꺼져요",
    (site) => {
      vi.stubEnv("INDEXING_ENABLED", "true");
      vi.stubEnv("SITE_URL", site);
      expect(indexingSiteUrl()).toBeNull();
    },
  );

  it("SITE_URL이 없으면 기본값으로 채우지 않아요", () => {
    vi.stubEnv("INDEXING_ENABLED", "true");
    delete process.env.SITE_URL;
    expect(indexingSiteUrl()).toBeNull();
  });

  it("둘 다 있으면 끝의 /를 뺀 주소", () => {
    vi.stubEnv("INDEXING_ENABLED", "true");
    vi.stubEnv("SITE_URL", `${SITE}/`);
    expect(indexingSiteUrl()).toBe(SITE);
  });
});

describe("pageRobots", () => {
  it("꺼져 있으면 허용 범위여도 noindex", () => {
    vi.stubEnv("INDEXING_ENABLED", "false");
    vi.stubEnv("SITE_URL", SITE);
    expect(pageRobots(true)).toEqual({ index: false, follow: false });
  });

  it("켜져 있으면 허용 범위만 index", () => {
    vi.stubEnv("INDEXING_ENABLED", "true");
    vi.stubEnv("SITE_URL", SITE);
    expect(pageRobots(true)).toEqual({ index: true, follow: true });
    expect(pageRobots(false)).toEqual({ index: false, follow: false });
  });

  it("기록 2건 이상인 층만 색인 허용", () => {
    expect([0, 1, 2, 3].map(isIndexableFloor)).toEqual([false, false, true, true]);
  });
});
