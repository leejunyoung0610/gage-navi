/**
 * API 주소 (T-030, docker-compose.yml `web`). 서버 컴포넌트(SSR/ISR)는 컨테이너 내부 주소 `API_INTERNAL_URL`,
 * 브라우저는 `NEXT_PUBLIC_API_BASE_URL`(빌드할 때 번들에 들어간다)을 쓴다. 값이 없으면 기본값으로 채우지 않고 오류.
 */
export function apiBaseUrl(): string {
  const onServer = typeof window === "undefined";
  const name = onServer ? "API_INTERNAL_URL" : "NEXT_PUBLIC_API_BASE_URL";
  // NEXT_PUBLIC_*는 빌드 때 글자 그대로 치환되므로 `process.env[name]`이 아니라 이름을 직접 쓴다
  const value = onServer ? process.env.API_INTERNAL_URL : process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!value) throw new Error(`${name}가 설정되지 않았어요`);
  return value.replace(/\/+$/, "");
}
