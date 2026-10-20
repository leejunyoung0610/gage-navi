/**
 * 방문 측정·"도움이 됐나요" 이벤트 (T-104, ADR-027, docs/40 §10, docs/70 §5).
 *
 * - 서버에 방문자 식별자를 보내지 않는다. 본문은 `{event, date}`뿐이고 쿠키·Referer를 보내지 않는다
 * - 브라우저에는 첫 방문 날짜, "이미 보냈음" 표시 둘, 측정 끄기 표시만 저장한다(`/privacy`에 같은 목록)
 * - 측정 끄기를 켰거나, 봇으로 보이거나, 저장소를 쓸 수 없으면 아무 이벤트도 보내지 않는다
 * - User-Agent는 봇 판별에만 쓰고 저장·로그·전송하지 않는다
 * - 보내는 곳은 `apiBaseUrl()`뿐이다(고정 주소 없음 — e2e·로컬은 가상 API·로컬 API로 간다)
 */
import { apiBaseUrl } from "@/lib/api-base";
import type { components } from "@/lib/api/types";

export type MeasureEvent = components["schemas"]["MeasureEventIn"]["event"];
export type SendResult = "sent" | "rejected" | "failed";
export type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;
export type NavigatorLike = Pick<Navigator, "userAgent"> & { webdriver?: boolean };

export const MEASURE_KEYS = {
  firstVisit: "gn.visit.first",
  firstSent: "gn.visit.first_sent",
  revisitSent: "gn.visit.revisit_sent",
  off: "gn.measure.off",
} as const;

const FLAG = "1";
// 재방문은 첫 방문 다음 날부터 7일 안의 다른 날 (docs/70 §5)
const REVISIT_WINDOW_DAYS = 7;
const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

/** 알려진 봇·자동화 브라우저의 User-Agent 조각 (대소문자 무시) */
const BOT_USER_AGENT =
  /bot|crawl|spider|slurp|headless|lighthouse|yeti|daumoa|bingpreview|facebookexternalhit/i;

/** 봇으로 볼 브라우저인가. 결과(참/거짓)만 쓰고 User-Agent 값은 어디에도 남기지 않는다 */
export function isLikelyBot(nav: NavigatorLike | undefined): boolean {
  if (!nav) return true;
  if (nav.webdriver === true) return true;
  return BOT_USER_AGENT.test(nav.userAgent ?? "");
}

/** 한국 시간 날짜 `YYYY-MM-DD` (한국은 일광 절약 시간이 없다) */
export function kstDate(now: Date): string {
  return new Date(now.getTime() + KST_OFFSET_MS).toISOString().slice(0, 10);
}

/** `from`에서 `to`까지 날짜 수 (`to − from`) */
export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS);
}

/** 이 브라우저의 `localStorage`. 쓸 수 없으면 `null` (속성을 읽기만 해도 예외가 나는 브라우저가 있다) */
export function browserStorage(): StorageLike | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function read(storage: StorageLike, key: string): string | null {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

/** 쓰고 다시 읽어 같으면 성공 */
function write(storage: StorageLike, key: string, value: string): boolean {
  try {
    storage.setItem(key, value);
    return storage.getItem(key) === value;
  } catch {
    return false;
  }
}

export function isMeasureOff(storage: StorageLike): boolean {
  return read(storage, MEASURE_KEYS.off) === FLAG;
}

/** 측정 끄기 표시를 켜거나 끈다. 저장하지 못하면 `false` */
export function setMeasureOff(storage: StorageLike, off: boolean): boolean {
  if (off) return write(storage, MEASURE_KEYS.off, FLAG);
  try {
    storage.removeItem(MEASURE_KEYS.off);
    return !isMeasureOff(storage);
  } catch {
    return false;
  }
}

/** 이벤트를 보내도 되는 브라우저인가: 저장소가 있고, 측정 끄기가 아니고, 봇이 아니다 */
export function canMeasure(
  storage: StorageLike | null,
  nav: NavigatorLike | undefined,
): storage is StorageLike {
  return storage !== null && !isMeasureOff(storage) && !isLikelyBot(nav);
}

/** 이벤트 하나를 보낸다. 2xx는 `sent`, 422(날짜 범위 밖 — 다시 보내도 같다)는 `rejected` */
export async function sendMeasureEvent(event: MeasureEvent, date: string): Promise<SendResult> {
  const body: components["schemas"]["MeasureEventIn"] = { event, date };
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/measure/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer", // 보던 페이지 주소를 보내지 않는다
    });
    if (response.ok) return "sent";
    return response.status === 422 ? "rejected" : "failed";
  } catch {
    return "failed";
  }
}

export interface MeasureDeps {
  storage: StorageLike | null;
  nav: NavigatorLike | undefined;
  now: Date;
  send: (event: MeasureEvent, date: string) => Promise<SendResult>;
}

function browserDeps(): MeasureDeps {
  return {
    storage: browserStorage(),
    nav: typeof navigator === "undefined" ? undefined : navigator,
    now: new Date(),
    send: sendMeasureEvent,
  };
}

/**
 * 첫 방문·7일 안 재방문 이벤트를 각각 브라우저당 한 번만 보낸다 (docs/40 §10).
 * 보내지 못하면(2xx·422 외) 표시를 남기지 않아 다음 방문 때 다시 보낸다.
 */
export async function runVisitMeasure(deps: MeasureDeps): Promise<void> {
  const { storage, nav, now, send } = deps;
  if (!canMeasure(storage, nav)) return;
  const today = kstDate(now);
  let first = read(storage, MEASURE_KEYS.firstVisit);
  if (first === null || !DATE_PATTERN.test(first)) {
    // 저장하지 못하면 매번 첫 방문으로 세지므로 보내지 않는다
    if (!write(storage, MEASURE_KEYS.firstVisit, today)) return;
    first = today;
  }
  if (read(storage, MEASURE_KEYS.firstSent) !== FLAG) {
    if ((await send("first_visit", first)) !== "failed") {
      write(storage, MEASURE_KEYS.firstSent, FLAG);
    }
    return;
  }
  if (read(storage, MEASURE_KEYS.revisitSent) === FLAG) return;
  const days = daysBetween(first, today);
  if (days < 1 || days > REVISIT_WINDOW_DAYS) return;
  if ((await send("revisit_7d", first)) !== "failed") {
    write(storage, MEASURE_KEYS.revisitSent, FLAG);
  }
}

let started: Promise<void> | null = null;

/** 페이지를 열 때 한 번만 실행한다(개발 모드에서 효과가 두 번 돌아도 한 번) */
export function startVisitMeasure(deps: MeasureDeps = browserDeps()): Promise<void> {
  started ??= runVisitMeasure(deps);
  return started;
}

/** 테스트용: `startVisitMeasure`의 한 번 실행 상태를 지운다 */
export function resetVisitMeasureForTest(): void {
  started = null;
}

/** `measure_off`: 측정 끄기를 켰다. `unavailable`: 봇으로 보이거나 저장소를 쓸 수 없다 */
export type HelpfulResult = "sent" | "measure_off" | "unavailable";

/** "도움이 됐나요" 예/아니오. 보내도 되는 브라우저가 아니면 보내지 않고 그 이유를 돌려준다 */
export function sendHelpful(
  answer: "yes" | "no",
  deps: MeasureDeps = browserDeps(),
): HelpfulResult {
  if (!canMeasure(deps.storage, deps.nav)) {
    return deps.storage !== null && isMeasureOff(deps.storage) ? "measure_off" : "unavailable";
  }
  void deps.send(answer === "yes" ? "helpful_yes" : "helpful_no", kstDate(deps.now));
  return "sent";
}
