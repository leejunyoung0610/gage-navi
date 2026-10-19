// @vitest-environment jsdom
/**
 * 정정 요청 시트 (docs/40 §4.4-6, docs/30 §2 `corrections`). PNU·기록·문구는 가상 예시다.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CorrectionButton, CorrectionProvider } from "@/components/CorrectionSheet";
import { FloorTimeline, type TimelineRecord } from "@/components/FloorTimeline";

const API = "http://api.example.test"; // 가상 예시
const PNU = "1121510700100470001"; // 가상 예시

const RECORD: TimelineRecord = {
  record_id: 1032,
  name: "가상분식",
  license_type: "general_restaurant",
  biz_category: "분식",
  opened_on: "2011-03-02",
  closed_on: "2013-08-30",
  status: "closed",
  tenure_days: 912,
  ho_list: [],
  bulk_closure: false,
  bulk_closure_detail: null,
  stale_suspect: false,
};

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", API);
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify({ data: { id: 55 }, meta: { request_id: "가상" } }), {
      status: 201,
    }),
  );
});

afterEach(() => {
  cleanup();
  fetchMock.mockReset();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

function renderFloor(floor: string | null = "1") {
  return render(
    <CorrectionProvider pnu={PNU} floor={floor}>
      <FloorTimeline history={[RECORD]} dataAsOf="2026-11-01" label="층 이력" />
      <CorrectionButton />
    </CorrectionProvider>,
  );
}

const sentBody = () => JSON.parse(fetchMock.mock.calls[0]![1].body as string) as unknown;

describe("CorrectionSheet", () => {
  it("기록에서 열면 층·기록과 함께 보낸다", async () => {
    renderFloor("1");
    fireEvent.click(screen.getByRole("button", { name: "이 기록 정정 요청" }));
    const dialog = screen.getByRole("dialog", { name: "정보 정정 요청" });
    expect(dialog.textContent).toContain("연락처 같은 개인정보는 적지 말아 주세요.");
    fireEvent.click(screen.getByLabelText("기록을 내려 주세요"));
    fireEvent.change(screen.getByLabelText("무엇이 잘못됐나요?"), {
      target: { value: "  가상 예시 메시지  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "보내기" }));
    await screen.findByText("정정 요청을 받았어요. 확인한 뒤 반영할게요.");
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe(`${API}/api/v1/places/${PNU}/corrections`);
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
    expect(sentBody()).toEqual({
      kind: "remove_request",
      message: "가상 예시 메시지",
      floor: "1",
      record_id: 1032,
    });
  });

  it("페이지 버튼으로 열면 기록 없이, 필지 페이지는 층 없이", async () => {
    renderFloor(null);
    fireEvent.click(screen.getByRole("button", { name: "정보가 잘못됐나요?" }));
    fireEvent.change(screen.getByLabelText("무엇이 잘못됐나요?"), {
      target: { value: "가상 예시" },
    });
    fireEvent.click(screen.getByRole("button", { name: "보내기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(sentBody()).toEqual({ kind: "wrong_info", message: "가상 예시" });
  });

  it("빈 내용·1,000자 초과는 보내지 않는다", async () => {
    renderFloor();
    fireEvent.click(screen.getByRole("button", { name: "정보가 잘못됐나요?" }));
    const message = screen.getByLabelText("무엇이 잘못됐나요?");
    fireEvent.change(message, { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "보내기" }));
    await screen.findByText("내용을 적어 주세요.");
    fireEvent.change(message, { target: { value: "가".repeat(1001) } });
    fireEvent.click(screen.getByRole("button", { name: "보내기" }));
    await screen.findByText("1,000자까지 적을 수 있어요.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    [429, "요청이 많아요. 잠시 후 다시 시도해 주세요."],
    [503, "요청을 보내지 못했어요. 잠시 후 다시 시도해 주세요."],
  ])("오류 %i", async (status, text) => {
    fetchMock.mockResolvedValue(new Response("{}", { status }));
    renderFloor();
    fireEvent.click(screen.getByRole("button", { name: "정보가 잘못됐나요?" }));
    fireEvent.change(screen.getByLabelText("무엇이 잘못됐나요?"), { target: { value: "가상" } });
    fireEvent.click(screen.getByRole("button", { name: "보내기" }));
    expect((await screen.findByRole("alert")).textContent).toBe(text);
  });

  it("Esc·닫기로 닫힌다 (브라우저 confirm 없이 앱 안 시트)", () => {
    renderFloor();
    fireEvent.click(screen.getByRole("button", { name: "정보가 잘못됐나요?" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "정보가 잘못됐나요?" }));
    fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
