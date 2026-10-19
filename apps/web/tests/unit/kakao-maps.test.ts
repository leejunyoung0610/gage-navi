// @vitest-environment jsdom
/** 카카오 지도 SDK 지연 로딩 (docs/40 §4.2·§11). SDK는 불러오지 않고 script 태그만 본다 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { loadKakaoMaps, resetKakaoMapsForTest } from "@/lib/kakao-maps";

const FAKE_KEY = "fake-example-js-key"; // 가상 예시

function sdkScript(): HTMLScriptElement | null {
  return document.head.querySelector('script[src^="https://dapi.kakao.com/v2/maps/sdk.js"]');
}

beforeEach(() => {
  resetKakaoMapsForTest();
  vi.stubEnv("NEXT_PUBLIC_KAKAO_JS_KEY", FAKE_KEY);
});

afterEach(() => {
  sdkScript()?.remove();
  delete window.kakao;
  vi.unstubAllEnvs();
});

describe("loadKakaoMaps", () => {
  it("부를 때 처음 script를 넣고 autoload=false 뒤 load가 끝나면 돌려준다", async () => {
    expect(sdkScript()).toBeNull(); // 페이지를 열 때 불러오지 않는다
    const loading = loadKakaoMaps();
    const script = sdkScript()!;
    const url = new URL(script.src);
    expect(url.searchParams.get("appkey")).toBe(FAKE_KEY);
    expect(url.searchParams.get("autoload")).toBe("false");

    const maps = { load: vi.fn((callback: () => void) => callback()) };
    window.kakao = { maps: maps as never };
    script.dispatchEvent(new Event("load"));
    await expect(loading).resolves.toBe(maps);
    expect(maps.load).toHaveBeenCalledOnce();
    expect(loadKakaoMaps()).toBe(loading); // 한 번만 불러온다
  });

  it("불러오기에 실패하면 거부하고 다음에 다시 시도한다", async () => {
    const loading = loadKakaoMaps();
    sdkScript()!.dispatchEvent(new Event("error"));
    await expect(loading).rejects.toThrow("카카오 지도 SDK를 불러오지 못했어요");
    expect(sdkScript()).toBeNull();
    loadKakaoMaps().catch(() => {});
    expect(sdkScript()).not.toBeNull();
  });

  it("JS 키가 없으면 script를 넣지 않고 거부한다", async () => {
    vi.stubEnv("NEXT_PUBLIC_KAKAO_JS_KEY", "");
    await expect(loadKakaoMaps()).rejects.toThrow("NEXT_PUBLIC_KAKAO_JS_KEY");
    expect(sdkScript()).toBeNull();
  });
});
