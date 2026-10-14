import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const revalidatePath = vi.hoisted(() => vi.fn());
vi.mock("next/cache", () => ({ revalidatePath }));

import { POST } from "@/app/api/revalidate/route";
import { REVALIDATE_SECRET_HEADER as SECRET_HEADER } from "@/lib/revalidate";

// 가상 예시 비밀값 — 실제 REVALIDATE_SECRET이 아니다
const FAKE_SECRET = "fake-example-revalidate-secret"; // 가상 예시 (헤더 값은 ASCII만 가능)
const PATHS = ["/place/1121510700100470001", "/place/1121510700100470001/B1"];

function request(headers: Record<string, string>, body: unknown = { paths: PATHS }): Request {
  return new Request("http://localhost:3000/api/revalidate", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

describe("POST /api/revalidate", () => {
  beforeEach(() => {
    vi.stubEnv("REVALIDATE_SECRET", FAKE_SECRET);
    revalidatePath.mockClear();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("헤더 이름은 API 클라이언트와 같다 (services/api/app/admin/revalidate.py)", () => {
    expect(SECRET_HEADER).toBe("x-revalidate-secret");
  });

  it("맞는 비밀이면 경로마다 revalidatePath", async () => {
    const response = await POST(request({ [SECRET_HEADER]: FAKE_SECRET }));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ revalidated: PATHS });
    expect(revalidatePath.mock.calls).toEqual(PATHS.map((path) => [path]));
  });

  it.each([
    ["잘못된 비밀", { [SECRET_HEADER]: "fake-example-wrong-secret" }],
    ["앞부분만 같은 비밀", { [SECRET_HEADER]: FAKE_SECRET.slice(0, -1) }],
    ["빈 비밀", { [SECRET_HEADER]: "" }],
    ["헤더 없음", {}],
  ])("%s → 401, 재생성하지 않음", async (_, headers) => {
    const response = await POST(request(headers));
    expect(response.status).toBe(401);
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("서버에 비밀이 설정되지 않았으면 어떤 요청도 401", async () => {
    vi.stubEnv("REVALIDATE_SECRET", "");
    expect((await POST(request({ [SECRET_HEADER]: "" }))).status).toBe(401);
    vi.stubEnv("REVALIDATE_SECRET", undefined);
    expect((await POST(request({ [SECRET_HEADER]: "undefined" }))).status).toBe(401);
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("비밀이 틀리면 본문을 보기 전에 401", async () => {
    const response = await POST(request({ [SECRET_HEADER]: "fake-example-wrong-secret" }, "{"));
    expect(response.status).toBe(401);
  });

  it.each([
    ["JSON이 아님", "{"],
    ["paths 없음", {}],
    ["빈 목록", { paths: [] }],
    ["상대 경로", { paths: ["place/1"] }],
    ["다른 호스트", { paths: ["//evil.example/x"] }],
    ["문자열이 아님", { paths: [1] }],
  ])("본문이 잘못되면(%s) 400", async (_, body) => {
    const response = await POST(request({ [SECRET_HEADER]: FAKE_SECRET }, body));
    expect(response.status).toBe(400);
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});
