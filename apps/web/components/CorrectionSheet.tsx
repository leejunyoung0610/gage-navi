"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { CorrectionError, submitCorrection, type CorrectionIn } from "@/lib/place";

/** 정정 요청 본문 검증 (docs/30 §2 `corrections`: 메시지 1~1,000자) */
export const MESSAGE_MAX_LENGTH = 1000;
const messageSchema = z.string().trim().min(1).max(MESSAGE_MAX_LENGTH);

const KINDS: { value: CorrectionIn["kind"]; label: string }[] = [
  { value: "wrong_info", label: "정보가 틀렸어요" },
  { value: "remove_request", label: "기록을 내려 주세요" },
  { value: "other", label: "기타" },
];

const TEXT = {
  title: "정보 정정 요청",
  recordNote: "고른 기록에 대한 요청이에요.",
  privacy:
    "연락처 같은 개인정보는 적지 말아 주세요. 답장은 드리지 않고, 확인한 뒤 화면에 반영해요.",
  messageLabel: "무엇이 잘못됐나요?",
  messageRequired: "내용을 적어 주세요.",
  messageTooLong: `${MESSAGE_MAX_LENGTH.toLocaleString("ko-KR")}자까지 적을 수 있어요.`,
  submit: "보내기",
  sending: "보내는 중이에요",
  close: "닫기",
  done: "정정 요청을 받았어요. 확인한 뒤 반영할게요.",
  rateLimited: "요청이 많아요. 잠시 후 다시 시도해 주세요.",
  failed: "요청을 보내지 못했어요. 잠시 후 다시 시도해 주세요.",
} as const;

interface Target {
  recordId: number | null;
}

type Open = (recordId?: number) => void;
const CorrectionContext = createContext<Open | null>(null);

/** 정정 요청 시트를 여는 함수. 시트 밖(제공자 없음)에서는 `null` — 버튼을 그리지 않는다 */
export function useCorrection(): Open | null {
  return useContext(CorrectionContext);
}

/** 이 필지(·층)의 정정 요청 시트를 아래 컴포넌트에 연결한다 (docs/40 §4.4-6) */
export function CorrectionProvider({
  pnu,
  floor,
  children,
}: {
  pnu: string;
  floor: string | null;
  children: ReactNode;
}) {
  const [target, setTarget] = useState<Target | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const open = useCallback<Open>((recordId) => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setTarget({ recordId: recordId ?? null });
  }, []);
  const close = useCallback(() => {
    setTarget(null);
    opener.current?.focus();
  }, []);
  return (
    <CorrectionContext.Provider value={open}>
      {children}
      {target && (
        <CorrectionSheet pnu={pnu} floor={floor} recordId={target.recordId} onClose={close} />
      )}
    </CorrectionContext.Provider>
  );
}

/** "정보가 잘못됐나요?" 버튼 */
export function CorrectionButton() {
  const open = useCorrection();
  if (!open) return null;
  return (
    <button
      type="button"
      className="border-line min-h-touch w-full rounded-lg border px-3"
      onClick={() => open()}
    >
      정보가 잘못됐나요?
    </button>
  );
}

interface FormValues {
  kind: CorrectionIn["kind"];
  message: string;
}

type Status = "editing" | "done" | "rate_limited" | "failed";

function CorrectionSheet({
  pnu,
  floor,
  recordId,
  onClose,
}: {
  pnu: string;
  floor: string | null;
  recordId: number | null;
  onClose: () => void;
}) {
  const titleId = useId();
  const messageId = useId();
  const errorId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<Status>("editing");
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ defaultValues: { kind: "wrong_info", message: "" } });

  useEffect(() => {
    panel.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const onSubmit = async (values: FormValues) => {
    const body: CorrectionIn = { kind: values.kind, message: values.message.trim() };
    // 층 페이지에서 고른 기록이면 층·기록을 함께 보낸다. 층 미상 기록은 층 없이 기록만
    if (floor !== null) body.floor = floor;
    if (recordId !== null) body.record_id = recordId;
    try {
      await submitCorrection(pnu, body);
      setStatus("done");
    } catch (error) {
      setStatus(
        error instanceof CorrectionError && error.status === 429 ? "rate_limited" : "failed",
      );
    }
  };

  const messageError = errors.message?.message;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40" onClick={onClose}>
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="max-w-page max-h-[90dvh] w-full overflow-y-auto rounded-t-2xl bg-white p-4"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-2">
          <h2 id={titleId} className="text-lg font-bold">
            {TEXT.title}
          </h2>
          <button type="button" className="min-h-touch px-2 underline" onClick={onClose}>
            {TEXT.close}
          </button>
        </div>
        {status === "done" ? (
          <p role="status" className="mt-4">
            {TEXT.done}
          </p>
        ) : (
          <form className="mt-3 space-y-3" noValidate onSubmit={handleSubmit(onSubmit)}>
            {recordId !== null && <p className="text-muted text-sm">{TEXT.recordNote}</p>}
            <fieldset>
              <legend className="font-bold">요청 종류</legend>
              {KINDS.map((kind) => (
                <label key={kind.value} className="min-h-touch flex items-center gap-2">
                  <input type="radio" value={kind.value} {...register("kind")} />
                  {kind.label}
                </label>
              ))}
            </fieldset>
            <div>
              <label htmlFor={messageId} className="font-bold">
                {TEXT.messageLabel}
              </label>
              <p className="text-muted text-sm">{TEXT.privacy}</p>
              <textarea
                id={messageId}
                rows={4}
                aria-invalid={messageError ? true : undefined}
                aria-describedby={messageError ? errorId : undefined}
                className="border-line mt-1 w-full rounded-lg border p-3"
                {...register("message", {
                  validate: (value) => {
                    const result = messageSchema.safeParse(value);
                    if (result.success) return true;
                    return value.trim().length === 0 ? TEXT.messageRequired : TEXT.messageTooLong;
                  },
                })}
              />
              {messageError && (
                <p id={errorId} className="text-sm text-red-700">
                  {messageError}
                </p>
              )}
            </div>
            {status === "rate_limited" && <p role="alert">{TEXT.rateLimited}</p>}
            {status === "failed" && <p role="alert">{TEXT.failed}</p>}
            <button
              type="submit"
              disabled={isSubmitting}
              className="bg-brand min-h-touch w-full rounded-lg px-3 font-bold text-white"
            >
              {isSubmitting ? TEXT.sending : TEXT.submit}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
