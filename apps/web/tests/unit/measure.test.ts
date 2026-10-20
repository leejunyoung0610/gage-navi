// @vitest-environment jsdom
/**
 * 방문 측정 (docs/40 §10, docs/70 §5, ADR-027). 날짜·주소는 가상 예시다.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  MEASURE_KEYS,
  daysBetween,
  isLikelyBot,
  kstDate,
  runVisitMeasure,
  sendHelpful,
  sendMeasureEvent,
  setMeasureOff,
  type MeasureDeps,
  type MeasureEvent,
  type SendResult,
  type StorageLike,
} from "@/lib/measure";

const API = "http://api.example.test"; // 가상 예시
const CHROME_MOBILE =
  "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36";
const HUMAN = { userAgent: CHROME_MOBILE, webdriver: false };

function memoryStorage(): StorageLike & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => void data.set(key, value),
    removeItem: (key) => void data.delete(key),
  };
}

/** 한국 시간 `YYYY-MM-DD` 정오 */
const at = (day: string) => new Date(`${day}T12:00:00+09:00`);

function deps(storage: StorageLike | null, day: string, result: SendResult = "sent") {
  const sent: [MeasureEvent, string][] = [];
  const value: MeasureDeps = {
    storage,
    nav: HUMAN,
    now: at(day),
    send: async (event, date) => {
      sent.push([event, date]);
      return result;
    },
  };
  return { value, sent };
}

describe("isLikelyBot", () => {
  it.each([
    ["Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"],
    ["Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 HeadlessChrome/126.0 Safari/537.36"],
    ["Mozilla/5.0 (compatible; Yeti/1.1)"],
    ["Mozilla/5.0 (compatible; bingbot/2.0)"],
  ])("알려진 봇 UA는 봇: %s", (userAgent) => {
    expect(isLikelyBot({ userAgent, webdriver: false })).toBe(true);
  });

  it("webdriver가 참이면 봇", () => {
    expect(isLikelyBot({ userAgent: CHROME_MOBILE, webdriver: true })).toBe(true);
  });

  it("일반 브라우저는 봇이 아니다", () => {
    expect(isLikelyBot(HUMAN)).toBe(false);
    expect(isLikelyBot({ userAgent: CHROME_MOBILE })).toBe(false);
  });
});

describe("날짜 (한국 시간)", () => {
  it("UTC 15시는 한국 시간 다음 날", () => {
    expect(kstDate(new Date("2026-11-01T14:59:59Z"))).toBe("2026-11-01");
    expect(kstDate(new Date("2026-11-01T15:00:00Z"))).toBe("2026-11-02");
  });

  it("날짜 차이", () => {
    expect(daysBetween("2026-11-01", "2026-11-08")).toBe(7);
    expect(daysBetween("2026-10-31", "2026-11-01")).toBe(1);
  });
});

describe("runVisitMeasure", () => {
  it("첫 방문은 한 번만 보내고 저장 값은 날짜와 표시뿐이다", async () => {
    const storage = memoryStorage();
    const first = deps(storage, "2026-11-01");
    await runVisitMeasure(first.value);
    await runVisitMeasure(first.value);
    expect(first.sent).toEqual([["first_visit", "2026-11-01"]]);
    expect(Object.fromEntries(storage.data)).toEqual({
      [MEASURE_KEYS.firstVisit]: "2026-11-01",
      [MEASURE_KEYS.firstSent]: "1",
    });
  });

  it("다음 날부터 7일 안의 다른 날에 재방문을 한 번만 보낸다", async () => {
    const storage = memoryStorage();
    await runVisitMeasure(deps(storage, "2026-11-01").value);
    const sameDay = deps(storage, "2026-11-01");
    await runVisitMeasure(sameDay.value);
    expect(sameDay.sent).toEqual([]);
    const day7 = deps(storage, "2026-11-08");
    await runVisitMeasure(day7.value);
    await runVisitMeasure(day7.value);
    expect(day7.sent).toEqual([["revisit_7d", "2026-11-01"]]);
    expect(storage.data.get(MEASURE_KEYS.revisitSent)).toBe("1");
  });

  it("8일째 이후에는 재방문을 보내지 않는다", async () => {
    const storage = memoryStorage();
    await runVisitMeasure(deps(storage, "2026-11-01").value);
    const day8 = deps(storage, "2026-11-09");
    await runVisitMeasure(day8.value);
    expect(day8.sent).toEqual([]);
  });

  it("보내지 못하면 표시를 남기지 않고 다음 방문 때 다시 보낸다", async () => {
    const storage = memoryStorage();
    const failed = deps(storage, "2026-11-01", "failed");
    await runVisitMeasure(failed.value);
    expect(storage.data.has(MEASURE_KEYS.firstSent)).toBe(false);
    const retry = deps(storage, "2026-11-01");
    await runVisitMeasure(retry.value);
    expect(retry.sent).toEqual([["first_visit", "2026-11-01"]]);
  });

  it("422(날짜 범위 밖)는 다시 보내지 않는다", async () => {
    const storage = memoryStorage();
    await runVisitMeasure(deps(storage, "2026-11-01", "rejected").value);
    expect(storage.data.get(MEASURE_KEYS.firstSent)).toBe("1");
  });

  it("측정 끄기를 켜면 아무것도 보내지 않고 저장하지 않는다", async () => {
    const storage = memoryStorage();
    setMeasureOff(storage, true);
    const off = deps(storage, "2026-11-01");
    await runVisitMeasure(off.value);
    expect(off.sent).toEqual([]);
    expect([...storage.data.keys()]).toEqual([MEASURE_KEYS.off]);
  });

  it("봇이면 보내지 않는다", async () => {
    const storage = memoryStorage();
    const bot = deps(storage, "2026-11-01");
    await runVisitMeasure({ ...bot.value, nav: { userAgent: CHROME_MOBILE, webdriver: true } });
    expect(bot.sent).toEqual([]);
    expect(storage.data.size).toBe(0);
  });

  it("저장소를 쓸 수 없으면 보내지 않는다 (매번 첫 방문으로 세지지 않게)", async () => {
    const none = deps(null, "2026-11-01");
    await runVisitMeasure(none.value);
    const broken: StorageLike = {
      getItem: () => null,
      setItem: () => {
        throw new Error("가상 저장 공간 초과");
      },
      removeItem: () => undefined,
    };
    const full = deps(broken, "2026-11-01");
    await runVisitMeasure(full.value);
    expect([...none.sent, ...full.sent]).toEqual([]);
  });
});

describe("sendHelpful", () => {
  it("보내면 sent, 날짜는 오늘", () => {
    const ok = deps(memoryStorage(), "2026-11-01");
    expect(sendHelpful("yes", ok.value)).toBe("sent");
    expect(ok.sent).toEqual([["helpful_yes", "2026-11-01"]]);
  });

  it("보내지 않은 이유를 구분한다: 측정 끄기 / 봇 / 저장소 없음", () => {
    const storage = memoryStorage();
    setMeasureOff(storage, true);
    const off = deps(storage, "2026-11-01");
    expect(sendHelpful("yes", off.value)).toBe("measure_off");
    const bot = deps(memoryStorage(), "2026-11-01");
    expect(sendHelpful("no", { ...bot.value, nav: { userAgent: "Googlebot/2.1" } })).toBe(
      "unavailable",
    );
    const none = deps(null, "2026-11-01");
    expect(sendHelpful("yes", none.value)).toBe("unavailable");
    expect([...off.sent, ...bot.sent, ...none.sent]).toEqual([]);
  });
});

describe("sendMeasureEvent", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", API);
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("설정된 API 주소로 날짜와 이벤트 이름만 보낸다", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    expect(await sendMeasureEvent("first_visit", "2026-11-01")).toBe("sent");
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe(`${API}/api/v1/measure/events`);
    expect(init).toMatchObject({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "omit",
      referrerPolicy: "no-referrer",
    });
    expect(JSON.parse(init.body as string)).toEqual({ event: "first_visit", date: "2026-11-01" });
  });

  it.each([
    [422, "rejected"],
    [429, "failed"],
    [503, "failed"],
  ])("응답 %i → %s", async (status, result) => {
    fetchMock.mockResolvedValue(new Response(null, { status }));
    expect(await sendMeasureEvent("helpful_no", "2026-11-01")).toBe(result);
  });

  it("네트워크 오류는 failed", async () => {
    fetchMock.mockRejectedValue(new TypeError("가상 네트워크 오류"));
    expect(await sendMeasureEvent("helpful_yes", "2026-11-01")).toBe("failed");
  });

  it("API 주소가 없으면 보내지 않는다 (기본 주소로 채우지 않는다)", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    expect(await sendMeasureEvent("first_visit", "2026-11-01")).toBe("failed");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("측정 모듈에 고정된 서버 주소가 없다 (e2e·로컬이 운영 API로 보내지 않게)", () => {
    const source = readFileSync(join(process.cwd(), "lib/measure.ts"), "utf8");
    expect(source).not.toMatch(/https?:\/\//);
    expect(source).toContain("apiBaseUrl()");
  });
});
