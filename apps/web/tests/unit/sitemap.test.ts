import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import robots from "@/app/robots";
import { GET as getIndex } from "@/app/sitemap.xml/route";
import { GET as getFile } from "@/app/sitemaps/[file]/route";
import { parseSitemapFileName, sitemapFileNames, type SitemapFloor } from "@/lib/sitemap";

// 가상 예시: 주소·시군구·필지 번호 모두 형식 설명용 (운영 도메인은 T-081)
const SITE = "https://site.example.test";
const API = "http://api.example.test";
const GU = "11215";

type Fake = { sigungu: { code: string; floor_count: number }[]; floors: SitemapFloor[] };
let fake: Fake;
let calls: string[];

function floors(n: number): SitemapFloor[] {
  return Array.from({ length: n }, (_, i) => ({
    pnu: `1121510700${String(i).padStart(9, "0")}`,
    floor: "1",
  }));
}

function enable(): void {
  vi.stubEnv("INDEXING_ENABLED", "true");
  vi.stubEnv("SITE_URL", SITE);
}

const file = (name: string) =>
  getFile(new Request(`${SITE}/sitemaps/${name}`), { params: Promise.resolve({ file: name }) });

beforeEach(() => {
  vi.stubEnv("API_INTERNAL_URL", API);
  fake = { sigungu: [], floors: [] };
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      calls.push(input);
      const path = input.replace(`${API}/api/v1`, "");
      const data =
        path === "/sitemap/sigungu"
          ? { sigungu: fake.sigungu }
          : { code: path.split("/").pop(), floors: fake.floors };
      return new Response(JSON.stringify({ data, meta: { request_id: "x" } }));
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("robots.txt (docs/40 §9)", () => {
  it("INDEXING_ENABLED가 true가 아니면 전체 차단, 사이트맵 없음", () => {
    vi.stubEnv("INDEXING_ENABLED", "false");
    vi.stubEnv("SITE_URL", SITE);
    expect(robots()).toEqual({ rules: { userAgent: "*", disallow: "/" } });
  });

  it("SITE_URL이 없으면 true여도 전체 차단", () => {
    vi.stubEnv("INDEXING_ENABLED", "true");
    vi.stubEnv("SITE_URL", "");
    expect(robots()).toEqual({ rules: { userAgent: "*", disallow: "/" } });
  });

  it("켜지면 페이지는 열고 API만 막고 사이트맵 색인을 알려요", () => {
    enable();
    expect(robots()).toEqual({
      rules: { userAgent: "*", allow: "/", disallow: "/api/" },
      sitemap: `${SITE}/sitemap.xml`,
    });
  });
});

describe("사이트맵이 꺼져 있을 때", () => {
  it.each([
    ["false", SITE],
    ["true", ""],
  ])("INDEXING_ENABLED=%j, SITE_URL=%j → 404이고 API를 부르지 않아요", async (enabled, site) => {
    vi.stubEnv("INDEXING_ENABLED", enabled);
    vi.stubEnv("SITE_URL", site);
    fake.sigungu = [{ code: GU, floor_count: 1 }];
    fake.floors = floors(1);
    expect((await getIndex()).status).toBe(404);
    expect((await file(`${GU}-1.xml`)).status).toBe(404);
    expect(calls).toEqual([]);
  });
});

describe("사이트맵이 켜져 있을 때", () => {
  beforeEach(enable);

  it("색인은 시군구별 파일을 50,000개씩 나눠 알려요", async () => {
    fake.sigungu = [
      { code: "11110", floor_count: 3 },
      { code: GU, floor_count: 50_001 },
    ];
    const response = await getIndex();
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("application/xml");
    const body = await response.text();
    expect([...body.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1])).toEqual([
      `${SITE}/sitemaps/11110-1.xml`,
      `${SITE}/sitemaps/${GU}-1.xml`,
      `${SITE}/sitemaps/${GU}-2.xml`,
    ]);
    expect(body).toContain('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
    expect(calls).toEqual([`${API}/api/v1/sitemap/sigungu`]);
  });

  it("시군구 파일에는 API가 준 층 페이지만 들어가요", async () => {
    fake.floors = [
      { pnu: "1121510700100470001", floor: "1" },
      { pnu: "1121510700100480000", floor: "RF" },
    ];
    const response = await file(`${GU}-1.xml`);
    expect(response.status).toBe(200);
    const body = await response.text();
    expect([...body.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1])).toEqual([
      `${SITE}/place/1121510700100470001/1`,
      `${SITE}/place/1121510700100480000/RF`,
    ]);
    expect(body).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
    expect(calls).toEqual([`${API}/api/v1/sitemap/sigungu/${GU}`]);
  });

  it("한 파일에 50,000개까지, 나머지는 다음 파일", async () => {
    fake.floors = floors(50_001);
    const count = async (name: string) =>
      ((await (await file(name)).text()).match(/<url>/g) ?? []).length;
    expect(await count(`${GU}-1.xml`)).toBe(50_000);
    expect(await count(`${GU}-2.xml`)).toBe(1);
    expect((await file(`${GU}-3.xml`)).status).toBe(404);
  });

  it.each(["11215.xml", "11215-0.xml", "1121-1.xml", "11215-1.txt", "abcde-1.xml"])(
    "형식이 아닌 파일 이름 %j는 404",
    async (name) => {
      expect((await file(name)).status).toBe(404);
      expect(calls).toEqual([]);
    },
  );

  it("층이 없는 시군구는 404", async () => {
    expect((await file(`${GU}-1.xml`)).status).toBe(404);
  });
});

describe("파일 이름", () => {
  it("층이 0개인 시군구는 파일이 없어요", () => {
    expect(sitemapFileNames([{ code: GU, floor_count: 0 }])).toEqual([]);
    expect(sitemapFileNames([{ code: GU, floor_count: 50_000 }])).toEqual([`${GU}-1.xml`]);
  });

  it("이름을 시군구와 순번으로 읽어요", () => {
    expect(parseSitemapFileName(`${GU}-12.xml`)).toEqual({ code: GU, part: 12 });
  });
});
