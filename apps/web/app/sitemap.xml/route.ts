import { indexingSiteUrl } from "@/lib/indexing";
import { fetchSitemapSigungu, sitemapFileNames, sitemapIndexXml, xmlResponse } from "@/lib/sitemap";

// 빌드 때 API를 부르지 않는다(Docker 빌드에는 API가 없다). 색인 설정도 실행 환경 값으로 (docs/40 §9)
export const dynamic = "force-dynamic";

/** 사이트맵 색인. 색인이 꺼져 있으면 404 (docs/40 §9, T-035) */
export async function GET(): Promise<Response> {
  const siteUrl = indexingSiteUrl();
  if (siteUrl === null) return new Response("Not Found", { status: 404 });
  const names = sitemapFileNames(await fetchSitemapSigungu());
  return xmlResponse(sitemapIndexXml(siteUrl, names));
}
