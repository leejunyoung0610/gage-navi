/**
 * on-demand 재생성 (docs/40 §2, docs/30 §3). API가 정정 요청으로 기록을 숨긴 뒤 부른다.
 *
 * 헤더 `x-revalidate-secret`이 `REVALIDATE_SECRET`과 같아야 하고, 본문은 `{"paths": ["/place/…", …]}`.
 * 비밀이 설정되지 않았으면 모든 요청을 401로 거절한다.
 */
import { createHash, timingSafeEqual } from "node:crypto";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { REVALIDATE_SECRET_HEADER } from "@/lib/revalidate";

const bodySchema = z.object({
  paths: z.array(z.string().regex(/^\/(?!\/)\S*$/)).min(1),
});

/** 길이가 달라도 시간 차이가 나지 않게 해시끼리 비교한다 */
function secretMatches(given: string | null, expected: string | undefined): boolean {
  if (!expected || given === null) return false;
  const digest = (value: string) => createHash("sha256").update(value).digest();
  return timingSafeEqual(digest(given), digest(expected));
}

export async function POST(request: Request): Promise<Response> {
  if (
    !secretMatches(request.headers.get(REVALIDATE_SECRET_HEADER), process.env.REVALIDATE_SECRET)
  ) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid_body" }, { status: 400 });
  }
  const parsed = bodySchema.safeParse(body);
  if (!parsed.success) {
    return Response.json({ error: "invalid_body" }, { status: 400 });
  }
  for (const path of parsed.data.paths) {
    revalidatePath(path);
  }
  return Response.json({ revalidated: parsed.data.paths });
}
