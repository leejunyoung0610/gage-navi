/**
 * 사이트맵 (docs/40 §9, T-035). `/sitemap.xml`은 사이트맵 색인, `/sitemaps/{시군구}-{n}.xml`은 그 시군구의
 * 층 페이지 목록(파일당 50,000개 이하). 데이터는 요청 때 API(docs/30 `sitemap/sigungu`)에서 읽는다.
 */
import { apiBaseUrl, serverRenderHeaders } from "@/lib/api-base";
import type { components } from "@/lib/api/types";
import { SITEMAP_MAX_URLS } from "@/lib/indexing";
import { PLACE_REVALIDATE_SECONDS } from "@/lib/place";

export type SitemapSigungu = components["schemas"]["SitemapSigungu"];
export type SitemapFloor = components["schemas"]["SitemapFloor"];
type SigunguListResponse = components["schemas"]["SigunguListResponse"];
type SigunguFloorsResponse = components["schemas"]["SigunguFloorsResponse"];

const FILE_PATTERN = /^(\d{5})-([1-9]\d*)\.xml$/;

async function getJson<T>(path: string): Promise<T> {
  // 층 페이지와 같은 주기(1일)로 캐시한다 (docs/40 §2)
  const response = await fetch(`${apiBaseUrl()}/api/v1${path}`, {
    headers: serverRenderHeaders(),
    next: { revalidate: PLACE_REVALIDATE_SECONDS },
  });
  if (!response.ok) throw new Error(`사이트맵 API 오류 (${response.status})`);
  return (await response.json()) as T;
}

export async function fetchSitemapSigungu(): Promise<SitemapSigungu[]> {
  return (await getJson<SigunguListResponse>("/sitemap/sigungu")).data.sigungu;
}

export async function fetchSitemapFloors(code: string): Promise<SitemapFloor[]> {
  const path = `/sitemap/sigungu/${encodeURIComponent(code)}`;
  return (await getJson<SigunguFloorsResponse>(path)).data.floors;
}

/** 시군구마다 층 수를 50,000개씩 나눈 파일 이름 (`11215-1.xml`, `11215-2.xml`, …) */
export function sitemapFileNames(sigungu: SitemapSigungu[]): string[] {
  return sigungu.flatMap(({ code, floor_count }) =>
    Array.from(
      { length: Math.ceil(floor_count / SITEMAP_MAX_URLS) },
      (_, i) => `${code}-${i + 1}.xml`,
    ),
  );
}

/** 파일 이름 → 시군구 코드와 몇 번째 파일인지(1부터). 형식이 아니면 `null` */
export function parseSitemapFileName(name: string): { code: string; part: number } | null {
  const match = FILE_PATTERN.exec(name);
  return match ? { code: match[1]!, part: Number(match[2]) } : null;
}

/** `part`번째 파일에 들어갈 층 (비어 있으면 그런 파일은 없다) */
export function sitemapPart(floors: SitemapFloor[], part: number): SitemapFloor[] {
  return floors.slice((part - 1) * SITEMAP_MAX_URLS, part * SITEMAP_MAX_URLS);
}

function escapeXml(value: string): string {
  return value.replace(/[<>&'"]/g, (c) => `&#${c.charCodeAt(0)};`);
}

const XML_HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n';
const NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"';

export function sitemapIndexXml(siteUrl: string, fileNames: string[]): string {
  const items = fileNames.map(
    (name) => `<sitemap><loc>${escapeXml(`${siteUrl}/sitemaps/${name}`)}</loc></sitemap>`,
  );
  return `${XML_HEAD}<sitemapindex ${NS}>\n${items.join("\n")}\n</sitemapindex>\n`;
}

export function floorPath(floor: SitemapFloor): string {
  return `/place/${encodeURIComponent(floor.pnu)}/${encodeURIComponent(floor.floor)}`;
}

export function urlsetXml(siteUrl: string, floors: SitemapFloor[]): string {
  const items = floors.map(
    (f) => `<url><loc>${escapeXml(`${siteUrl}${floorPath(f)}`)}</loc></url>`,
  );
  return `${XML_HEAD}<urlset ${NS}>\n${items.join("\n")}\n</urlset>\n`;
}

export function xmlResponse(body: string): Response {
  return new Response(body, { headers: { "content-type": "application/xml; charset=utf-8" } });
}
