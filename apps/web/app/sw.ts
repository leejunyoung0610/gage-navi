/**
 * 서비스 워커 (docs/40 §8). `next build` 때 Serwist가 `public/sw.js`로 묶는다.
 * - 평가 요청 `/api/v1/*\/evaluate`: 캐시 금지
 * - 자리 페이지 `/place/*`: 네트워크 우선, 실패하면 캐시
 * - 정적 자산: 캐시 우선 (빌드 산출물은 precache)
 */
import type { PrecacheEntry, SerwistGlobalConfig } from "serwist";
import { CacheFirst, ExpirationPlugin, NetworkFirst, NetworkOnly, Serwist } from "serwist";

declare global {
  interface WorkerGlobalScope extends SerwistGlobalConfig {
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined;
  }
}

declare const self: ServiceWorkerGlobalScope;

const EVALUATE_PATH = /^\/api\/v1\/[^/]+\/evaluate$/;

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching: [
    {
      matcher: ({ url }) => EVALUATE_PATH.test(url.pathname),
      method: "POST",
      handler: new NetworkOnly(),
    },
    {
      matcher: ({ url }) => EVALUATE_PATH.test(url.pathname),
      handler: new NetworkOnly(),
    },
    {
      matcher: ({ url, sameOrigin }) => sameOrigin && url.pathname.startsWith("/place/"),
      handler: new NetworkFirst({
        cacheName: "place-pages",
        // 마지막으로 본 자리 페이지들만 남긴다
        plugins: [new ExpirationPlugin({ maxEntries: 50 })],
      }),
    },
    {
      matcher: ({ request, sameOrigin }) =>
        sameOrigin && ["style", "script", "font", "image"].includes(request.destination),
      handler: new CacheFirst({
        cacheName: "static-assets",
        plugins: [new ExpirationPlugin({ maxEntries: 200 })],
      }),
    },
  ],
});

serwist.addEventListeners();
