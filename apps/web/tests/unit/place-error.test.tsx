// @vitest-environment jsdom
/** 필지·층 페이지 오류 화면 (docs/40 §7, ADR-031): 사람이 읽는 문장 + 다시 시도 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PlaceError from "@/app/place/error";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

afterEach(() => {
  cleanup();
  refresh.mockReset();
});

describe("PlaceError", () => {
  it("잠시 후 다시 열라는 문장과 홈 링크", () => {
    render(<PlaceError error={new Error("장소 API 오류 (429)")} reset={() => {}} />);
    expect(screen.getByRole("heading", { name: "지금은 이 페이지를 열 수 없어요" })).toBeTruthy();
    expect(screen.getByText(/1분쯤 뒤에 다시 열어 주세요/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "홈으로" }).getAttribute("href")).toBe("/");
  });

  it("오류 내용을 화면에 내보내지 않는다", () => {
    const { container } = render(
      <PlaceError error={new Error("장소 API 오류 (429)")} reset={() => {}} />,
    );
    expect(container.textContent).not.toContain("429");
  });

  it("다시 시도는 서버 데이터를 새로 받고 다시 그린다", () => {
    const reset = vi.fn();
    render(<PlaceError error={new Error("x")} reset={reset} />);
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(refresh).toHaveBeenCalledOnce();
    expect(reset).toHaveBeenCalledOnce();
  });
});
