/**
 * 카카오 지도 JavaScript SDK 지연 로딩 (docs/40 §4.2, §11 — 지도는 JS 예산 밖, 쓸 때만 불러온다).
 *
 * SDK는 `autoload=false`로 불러와 `kakao.maps.load`가 끝난 뒤에 쓴다. 여기 타입은 SDK에서 실제로
 * 쓰는 부분만 적은 것이다(API 응답 타입이 아니다). 지도에서 찍은 좌표는 저장하지 않는다.
 */

const SDK_URL = "https://dapi.kakao.com/v2/maps/sdk.js";

export interface KakaoLatLng {
  getLat(): number;
  getLng(): number;
}

export interface KakaoMap {
  setCenter(latLng: KakaoLatLng): void;
}

export interface KakaoMarker {
  setPosition(latLng: KakaoLatLng): void;
  setMap(map: KakaoMap | null): void;
}

export interface KakaoMouseEvent {
  latLng: KakaoLatLng;
}

export interface KakaoMapsApi {
  LatLng: new (lat: number, lng: number) => KakaoLatLng;
  Map: new (container: HTMLElement, options: { center: KakaoLatLng; level: number }) => KakaoMap;
  Marker: new (options: { position: KakaoLatLng; map?: KakaoMap }) => KakaoMarker;
  event: {
    addListener(target: KakaoMap, type: "click", handler: (event: KakaoMouseEvent) => void): void;
  };
  load(callback: () => void): void;
}

declare global {
  interface Window {
    kakao?: { maps?: KakaoMapsApi };
  }
}

let loading: Promise<KakaoMapsApi> | null = null;

/** SDK를 한 번만 불러온다. 실패하면 다음 호출에서 다시 시도한다 */
export function loadKakaoMaps(): Promise<KakaoMapsApi> {
  if (loading) return loading;
  const key = process.env.NEXT_PUBLIC_KAKAO_JS_KEY;
  if (!key) return Promise.reject(new Error("NEXT_PUBLIC_KAKAO_JS_KEY가 설정되지 않았어요"));
  loading = new Promise<KakaoMapsApi>((resolve, reject) => {
    const fail = () => {
      loading = null;
      script.remove();
      reject(new Error("카카오 지도 SDK를 불러오지 못했어요"));
    };
    const script = document.createElement("script");
    script.src = `${SDK_URL}?appkey=${encodeURIComponent(key)}&autoload=false`;
    script.async = true;
    script.onerror = fail;
    script.onload = () => {
      const maps = window.kakao?.maps;
      if (!maps) return fail();
      maps.load(() => resolve(maps));
    };
    document.head.appendChild(script);
  });
  return loading;
}

/** 테스트 전용: 불러온 상태를 지운다 */
export function resetKakaoMapsForTest(): void {
  loading = null;
}
