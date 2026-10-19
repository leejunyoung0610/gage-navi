import { indexingSiteUrl } from "@/lib/indexing";
import {
  fetchSitemapFloors,
  parseSitemapFileName,
  sitemapPart,
  urlsetXml,
  xmlResponse,
} from "@/lib/sitemap";

export const dynamic = "force-dynamic";

const notFound = () => new Response("Not Found", { status: 404 });

/** 시군구별 층 페이지 사이트맵 `/sitemaps/{시군구}-{n}.xml`. 색인이 꺼져 있으면 404 (docs/40 §9, T-035) */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ file: string }> },
): Promise<Response> {
  const siteUrl = indexingSiteUrl();
  const parsed = parseSitemapFileName((await params).file);
  if (siteUrl === null || parsed === null) return notFound();
  const floors = sitemapPart(await fetchSitemapFloors(parsed.code), parsed.part);
  if (floors.length === 0) return notFound();
  return xmlResponse(urlsetXml(siteUrl, floors));
}
