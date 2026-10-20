// @vitest-environment jsdom
/**
 * 측정 끄기 플래그·봇 판별이 켜진 브라우저는 이벤트 요청을 보내지 않는다 (T-104 수용 기준,
 * docs/40 §4.4-6·§10, ADR-027). 날짜·주소는 가상 예시다.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HelpfulPrompt } from "@/components/HelpfulPrompt";
import { MeasureSwitch } from "@/components/MeasureSwitch";
import { VisitMeasure } from "@/components/VisitMeasure";
import { MEASURE_KEYS, resetVisitMeasureForTest } from "@/lib/measure";

const API = "http://api.example.test"; // 가상 예시
const CHROME_MOBILE =
  "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36";
const fetchMock = vi.fn();

function setBrowser({ userAgent = CHROME_MOBILE, webdriver = false } = {}) {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(userAgent);
  Object.defineProperty(navigator, "webdriver", { configurable: true, get: () => webdriver });
}

const sentBodies = () =>
  fetchMock.mock.calls.map(([, init]) => JSON.parse(init.body as string) as unknown);

/** 이벤트 요청이 나갈 기회를 준 뒤 확인한다 */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-01T12:00:00+09:00"));
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", API);
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation(async () => new Response(null, { status: 204 }));
  localStorage.clear();
  resetVisitMeasureForTest();
  setBrowser();
});

afterEach(() => {
  cleanup();
  fetchMock.mockReset();
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("VisitMeasure", () => {
  it("일반 브라우저는 첫 방문을 한 번만 보낸다 (두 번 그려도)", async () => {
    render(
      <>
        <VisitMeasure />
        <VisitMeasure />
      </>,
    );
    await waitFor(() => expect(localStorage.getItem(MEASURE_KEYS.firstSent)).toBe("1"));
    expect(sentBodies()).toEqual([{ event: "first_visit", date: "2026-11-01" }]);
    expect(fetchMock.mock.calls[0]![0]).toBe(`${API}/api/v1/measure/events`);
  });

  it("측정 끄기 플래그를 켠 브라우저는 요청을 보내지 않는다", async () => {
    localStorage.setItem(MEASURE_KEYS.off, "1");
    render(<VisitMeasure />);
    await settle();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(localStorage.getItem(MEASURE_KEYS.firstVisit)).toBeNull();
  });

  it.each([
    ["webdriver", { webdriver: true }],
    ["Googlebot", { userAgent: "Mozilla/5.0 (compatible; Googlebot/2.1)" }],
    ["HeadlessChrome", { userAgent: "Mozilla/5.0 (X11) HeadlessChrome/126.0 Safari/537.36" }],
  ])("봇(%s)은 요청을 보내지 않는다", async (_, browser) => {
    setBrowser(browser);
    render(<VisitMeasure />);
    await settle();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("HelpfulPrompt", () => {
  it("예를 누르면 날짜만 담아 한 번 보내고 버튼을 닫는다", async () => {
    render(<HelpfulPrompt />);
    fireEvent.click(screen.getByRole("button", { name: "예" }));
    expect(await screen.findByText("알려 주셔서 고마워요.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "예" })).toBeNull();
    expect(sentBodies()).toEqual([{ event: "helpful_yes", date: "2026-11-01" }]);
    const [, init] = fetchMock.mock.calls[0]!;
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
  });

  it("아니오는 helpful_no", async () => {
    render(<HelpfulPrompt />);
    fireEvent.click(screen.getByRole("button", { name: "아니오" }));
    await screen.findByText("알려 주셔서 고마워요.");
    expect(sentBodies()).toEqual([{ event: "helpful_no", date: "2026-11-01" }]);
  });

  it("측정 끄기 플래그를 켠 브라우저는 요청을 보내지 않고 그렇게 알린다", async () => {
    localStorage.setItem(MEASURE_KEYS.off, "1");
    render(<HelpfulPrompt />);
    fireEvent.click(screen.getByRole("button", { name: "예" }));
    expect(
      await screen.findByText("통계에서 빠지기를 켜 두어서 응답을 보내지 않았어요."),
    ).toBeTruthy();
    await settle();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("봇은 요청을 보내지 않고, 측정 끄기와 다른 문구로 알린다", async () => {
    setBrowser({ webdriver: true });
    render(<HelpfulPrompt />);
    fireEvent.click(screen.getByRole("button", { name: "아니오" }));
    expect(
      await screen.findByText("이 브라우저에서는 응답을 보낼 수 없어서 보내지 않았어요."),
    ).toBeTruthy();
    expect(screen.queryByText(/통계에서 빠지기/)).toBeNull();
    await settle();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("MeasureSwitch", () => {
  it("켜면 플래그를 저장하고, 끄면 지운다", async () => {
    render(<MeasureSwitch />);
    const toggle = await screen.findByRole("switch", { name: /통계에서 빠지기/ });
    await waitFor(() => expect(toggle.getAttribute("aria-checked")).toBe("false"));
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    expect(localStorage.getItem(MEASURE_KEYS.off)).toBe("1");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(localStorage.getItem(MEASURE_KEYS.off)).toBeNull();
  });

  it("켠 뒤에는 방문 측정이 요청을 보내지 않는다", async () => {
    render(<MeasureSwitch />);
    fireEvent.click(await screen.findByRole("switch", { name: /통계에서 빠지기/ }));
    cleanup();
    render(<VisitMeasure />);
    await settle();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
