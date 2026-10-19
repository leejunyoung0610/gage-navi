/**
 * 장소 API 호출 (docs/30 §2 `places/{pnu}`, `places/{pnu}/floors/{floor}`, `corrections`, T-033).
 *
 * 필지·층 페이지는 서버 컴포넌트 + ISR(1일, docs/40 §2)이라 조회는 서버에서 한다. 정정 요청과
 * 관련 필지 확인(주소 검색 재호출, docs/40 §4.3)만 브라우저에서 부른다.
 */
import { searchAddress } from "@/lib/address";
import { apiBaseUrl } from "@/lib/api-base";
import type { components } from "@/lib/api/types";

export type PlaceData = components["schemas"]["PlaceData"];
export type FloorData = components["schemas"]["FloorData"];
export type FloorRecord = components["schemas"]["FloorRecord"];
export type PlaceRecord = components["schemas"]["PlaceRecord"];
export type BaseRate = components["schemas"]["BaseRate"];
export type HoGroup = components["schemas"]["HoGroup"];
export type CorrectionIn = components["schemas"]["CorrectionIn"];
export type RelatedParcel = components["schemas"]["RelatedParcel"];
type HealthResponse = components["schemas"]["HealthResponse"];

/** ISR 주기 1일 (docs/40 §2). 라우트의 `revalidate`와 같은 값 */
export const PLACE_REVALIDATE_SECONDS = 86400;

/**
 * 조회 결과. `invalid`는 PNU·층 형식 오류(422), `no_history`는 필지·층에 기록 없음(404).
 * 그 밖의 오류(503 등)는 던져서 오류 화면으로 보낸다
 */
export type Lookup<T> =
  { kind: "ok"; data: T; dataAsOf: string } | { kind: "invalid" } | { kind: "no_history" };

async function lookup<T>(path: string): Promise<Lookup<T>> {
  const response = await fetch(`${apiBaseUrl()}/api/v1${path}`, {
    next: { revalidate: PLACE_REVALIDATE_SECONDS },
  });
  if (response.status === 422) return { kind: "invalid" };
  if (response.status === 404) return { kind: "no_history" };
  if (!response.ok) throw new Error(`장소 API 오류 (${response.status})`);
  const body = (await response.json()) as { data: T; meta: { data_as_of: string } };
  return { kind: "ok", data: body.data, dataAsOf: body.meta.data_as_of };
}

export function fetchPlace(pnu: string): Promise<Lookup<PlaceData>> {
  return lookup(`/places/${encodeURIComponent(pnu)}`);
}

export function fetchFloor(pnu: string, floor: string): Promise<Lookup<FloorData>> {
  return lookup(`/places/${encodeURIComponent(pnu)}/floors/${encodeURIComponent(floor)}`);
}

/** 이력 없음 문구의 기준 월(`YYYY-MM`). 알 수 없거나 헬스체크가 실패하면 `null` */
export async function fetchSnapshotMonth(): Promise<string | null> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/health`, {
      next: { revalidate: PLACE_REVALIDATE_SECONDS },
    });
    if (!response.ok) return null;
    return ((await response.json()) as HealthResponse).location_snapshot;
  } catch {
    return null;
  }
}

/** 정정 요청이 실패했다. `status`로 문구를 고른다(429 = 호출 제한) */
export class CorrectionError extends Error {
  constructor(readonly status: number) {
    super(`정정 요청 오류 (${status})`);
    this.name = "CorrectionError";
  }
}

/** 정정 요청을 보낸다. 본문은 어디에도 남기지 않는다(docs/30 §2) */
export async function submitCorrection(pnu: string, body: CorrectionIn): Promise<number> {
  const response = await fetch(
    `${apiBaseUrl()}/api/v1/places/${encodeURIComponent(pnu)}/corrections`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    },
  );
  if (!response.ok) throw new CorrectionError(response.status);
  const created = (await response.json()) as components["schemas"]["CorrectionResponse"];
  return created.data.id;
}

/**
 * 같은 건물의 다른 필지 중 기록이 있는 것 (docs/40 §4.3). 이 필지의 지번으로 주소 검색을 한 번
 * 부르고, `pnu`가 같은 항목들의 `related_with_history`를 합친다(나온 순서, 중복·자기 자신 제외).
 * 같은 항목이 없거나 값이 `null`이면 `null`(확인 못 함 — `[]`과 다르다). 호출 실패는 던진다
 */
export async function findRelatedParcels(
  pnu: string,
  jibunLabel: string,
  signal?: AbortSignal,
): Promise<RelatedParcel[] | null> {
  const { items } = await searchAddress(jibunLabel, signal);
  const same = items.filter((item) => item.pnu === pnu);
  if (same.length === 0) return null;
  const merged: RelatedParcel[] = [];
  for (const item of same) {
    if (item.related_with_history === null) return null;
    for (const related of item.related_with_history) {
      if (related.pnu !== pnu && !merged.some((m) => m.pnu === related.pnu)) merged.push(related);
    }
  }
  return merged;
}

/**
 * 같은 호수 그룹의 색 (docs/40 §4.4-5). `ho_groups` 순서대로 팔레트를 돌려 쓴다. 전체 목록 기준이라
 * "전체 보기"로 펼쳐도 바뀌지 않는다. 색만으로 뜻을 전하지 않도록 화면에는 호수 글자를 함께 쓴다
 */
export const HO_GROUP_COLORS = [
  "#2563eb",
  "#c2410c",
  "#7c3aed",
  "#047857",
  "#be185d",
  "#a16207",
] as const;

export interface HoMark {
  ho: string;
  color: string;
}

export function hoMarks(groups: readonly HoGroup[]): Map<number, HoMark[]> {
  const marks = new Map<number, HoMark[]>();
  groups.forEach((group, index) => {
    const color = HO_GROUP_COLORS[index % HO_GROUP_COLORS.length] ?? HO_GROUP_COLORS[0];
    for (const recordId of group.record_ids) {
      const list = marks.get(recordId) ?? [];
      list.push({ ho: group.ho, color });
      marks.set(recordId, list);
    }
  });
  return marks;
}
