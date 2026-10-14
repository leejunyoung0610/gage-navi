import { afterEach, describe, expect, it, vi } from "vitest";

import { apiBaseUrl } from "@/lib/api-base";

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
