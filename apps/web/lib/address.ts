/**
 * 주소 API 호출 (docs/30 §2 `address/search`, `address/reverse`, T-032).
 *
 * 좌표 결과(`reverse`)는 카카오 이용 조건상 저장·캐시하지 않는다(`data/README.md`). 이 모듈은 값을
 * 돌려주기만 하고 어디에도 남기지 않는다.
 */
import { apiBaseUrl } from "@/lib/api-base";
import type { components } from "@/lib/api/types";

export type AddressItem = components["schemas"]["AddressItem"];
export type AddressSearchData = components["schemas"]["AddressSearchData"];
export type AddressReverseData = components["schemas"]["AddressReverseData"];

/** API가 오류로 답했다. `status`로 화면 상태를 고른다(422 = 검색어를 받지 않음) */
export class AddressApiError extends Error {
  constructor(readonly status: number) {
    super(`주소 API 오류 (${status})`);
    this.name = "AddressApiError";
  }
}

async function getData<T>(path: string, params: URLSearchParams, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBaseUrl()}/api/v1${path}?${params.toString()}`, {
    signal,
    cache: "no-store",
  });
  if (!response.ok) throw new AddressApiError(response.status);
  const body = (await response.json()) as { data: T };
  return body.data;
}

export function searchAddress(q: string, signal?: AbortSignal): Promise<AddressSearchData> {
  return getData("/address/search", new URLSearchParams({ q }), signal);
}

export function reverseAddress(lat: number, lng: number): Promise<AddressReverseData> {
  return getData("/address/reverse", new URLSearchParams({ lat: String(lat), lng: String(lng) }));
}
