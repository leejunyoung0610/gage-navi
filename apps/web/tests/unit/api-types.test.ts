import { describe, expectTypeOf, it } from "vitest";

import type { components, paths } from "@/lib/api/types";

// 생성 타입(T-031)이 API 계약(docs/30)을 담는지 tsc로 확인한다. 값은 실행하지 않는다.
type Schemas = components["schemas"];

describe("lib/api/types.ts", () => {
  it("공개 경로의 응답 타입이 스키마와 이어진다", () => {
    type PlaceOk =
      paths["/api/v1/places/{pnu}"]["get"]["responses"][200]["content"]["application/json"];
    expectTypeOf<PlaceOk>().toEqualTypeOf<Schemas["PlaceResponse"]>();
  });

  it("오류 코드는 docs/30 §1 표와 같다", () => {
    expectTypeOf<Schemas["ErrorCode"]>().toEqualTypeOf<
      | "VALIDATION_ERROR"
      | "NOT_FOUND"
      | "NO_HISTORY"
      | "RATE_LIMITED"
      | "UPSTREAM_UNAVAILABLE"
      | "SERVICE_UNAVAILABLE"
      | "UNAUTHORIZED"
      | "FORBIDDEN"
      | "CONFLICT"
      | "INTERNAL"
    >();
  });
});
