/**
 * 방법론 페이지 데이터 (docs/30 `GET /stats/model-card`, docs/40 §4.9, T-034).
 *
 * 화면의 숫자는 모두 이 응답에서 만든다. 응답은 1일 캐시한다(docs/40 §2).
 */
import { apiBaseUrl } from "@/lib/api-base";
import type { components } from "@/lib/api/types";

type Schemas = components["schemas"];
export type ModelCardData = Schemas["ModelCardData"];
export type ModelCard = Schemas["ModelCardPayload"];
export type SearchMatch = Schemas["SearchMatchPayload"];
export type SettingResult = Schemas["SettingResult"];
export type ScaleResult = Schemas["ScaleResult"];
export type BucketOut = Schemas["BucketOut"];
export type SigunguOut = Schemas["SigunguOut"];

/** 응답 캐시 1일 (docs/40 §2) */
export const METHODOLOGY_REVALIDATE_SECONDS = 86400;

/** 오류(503 등)는 던져서 오류 화면으로 보낸다 */
export async function fetchModelCard(): Promise<ModelCardData> {
  const response = await fetch(`${apiBaseUrl()}/api/v1/stats/model-card`, {
    next: { revalidate: METHODOLOGY_REVALIDATE_SECONDS },
  });
  if (!response.ok) throw new Error(`방법론 API 오류 (${response.status})`);
  return ((await response.json()) as { data: ModelCardData }).data;
}

/** 버킷 하나 찾기. 없으면 `null` */
export function bucketOf(buckets: readonly BucketOut[], bucket: BucketOut["bucket"]) {
  return buckets.find((item) => item.bucket === bucket) ?? null;
}

/** 결론 유지 판정 (a)(b) 둘 다 참인지 (docs/10 §7.3) */
export function holds(result: Pick<SettingResult, "criterion_a" | "criterion_b">): boolean {
  return result.criterion_a && result.criterion_b;
}
