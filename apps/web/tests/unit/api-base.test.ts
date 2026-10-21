import { afterEach, describe, expect, it, vi } from "vitest";

import { apiBaseUrl, serverRenderHeaders } from "@/lib/api-base";

// 가상 예시 주소
describe("apiBaseUrl", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("서버에서는 API_INTERNAL_URL", () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000/");
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://localhost:8000");
    expect(apiBaseUrl()).toBe("http://api:8000");
  });

  it("브라우저에서는 NEXT_PUBLIC_API_BASE_URL", () => {
    vi.stubGlobal("window", {});
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://localhost:8000");
    expect(apiBaseUrl()).toBe("http://localhost:8000");
  });

  it("값이 없으면 기본값 없이 오류", () => {
    vi.stubEnv("API_INTERNAL_URL", "");
    expect(() => apiBaseUrl()).toThrow("API_INTERNAL_URL");
  });
});

// 가상 예시 비밀 값 (ADR-031)
describe("serverRenderHeaders", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("서버에서 API_SSR_SECRET이 있으면 x-ssr-secret", () => {
    vi.stubEnv("API_SSR_SECRET", "virtual-example-secret");
    expect(serverRenderHeaders()).toEqual({ "x-ssr-secret": "virtual-example-secret" });
  });

  it("값이 없으면 빈 헤더 (API가 IP 기준으로 센다)", () => {
    vi.stubEnv("API_SSR_SECRET", "");
    expect(serverRenderHeaders()).toEqual({});
  });

  it("브라우저에서는 값이 있어도 보내지 않는다", () => {
    vi.stubGlobal("window", {});
    vi.stubEnv("API_SSR_SECRET", "virtual-example-secret");
    expect(serverRenderHeaders()).toEqual({});
  });
});

describe("서버 렌더링 조회가 헤더를 붙인다 (ADR-031)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("필지·층 조회와 사이트맵 조회", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubEnv("API_SSR_SECRET", "virtual-example-secret");
    const seen: (string | null)[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: string, init?: RequestInit) => {
        seen.push(new Headers(init?.headers).get("x-ssr-secret"));
        return new Response(JSON.stringify({ data: { sigungu: [] }, meta: { data_as_of: "x" } }));
      }),
    );
    const { fetchFloor, fetchPlace } = await import("@/lib/place");
    const { fetchSitemapSigungu } = await import("@/lib/sitemap");
    await fetchPlace("1111010100100010000");
    await fetchFloor("1111010100100010000", "1");
    await fetchSitemapSigungu();
    expect(seen).toEqual(Array(3).fill("virtual-example-secret"));
  });
});
