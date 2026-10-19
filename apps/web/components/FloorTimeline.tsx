"use client";

import { useMemo, useState } from "react";

import { useCorrection } from "@/components/CorrectionSheet";
import { formatCount, formatMonths, formatYearMonth, monthsBetween } from "@/lib/format";
import { hoMarks, type HoGroup, type HoMark, type PlaceRecord } from "@/lib/place";

/** 처음 그릴 건수 (docs/40 §4.4-5, T-033). 나머지는 "전체 보기"로 그린다. 데이터는 다 받는다 */
export const INITIAL_COUNT = 20;

/** 층 이력(`FloorRecord`)과 층 미상 기록(`PlaceRecord`, `stale_suspect` 없음)을 함께 받는다 */
export type TimelineRecord = PlaceRecord & { stale_suspect?: boolean };

const LICENSE_LABELS: Record<string, string> = {
  general_restaurant: "일반음식점",
  rest_restaurant: "휴게음식점",
  bakery: "제과점",
};

const STATUS_BADGES: Record<string, string> = {
  open: "영업 중",
  suspended: "휴업",
};

const TEXT = {
  bulk: "폐업 처리 몰린 날",
  stale: "같은 호수에 새 신고",
  staleNote:
    "같은 호수로 나중에 다른 가게가 영업 신고를 했어요. 이 가게의 폐업 신고가 늦어졌을 수 있어요.",
  now: "지금",
  unknownDate: "날짜 미상",
  unknownOpened: "개업일 미상",
  correct: "이 기록 정정 요청",
} as const;

function bulkNote(record: TimelineRecord): string | null {
  const detail = record.bulk_closure_detail;
  if (!record.bulk_closure || !detail) return null;
  // 해석("행정 일괄 정리")이 아니라 사실만 (ADR-020). 관할 이름·건수는 API 값만 쓴다
  const where = detail.jurisdiction_label ? `${detail.jurisdiction_label}에서 ` : "";
  return `이날 ${where}평소보다 훨씬 많은 폐업이 한꺼번에 처리됐어요(${formatCount(detail.closure_count)}건). 실제로 문을 닫은 날은 더 이를 수 있어요.`;
}

/** 기간 `2011.03 – 2013.08`과 기간 길이 `2년 5개월` (docs/40 §4.4-5) */
function period(record: TimelineRecord, dataAsOf: string): { text: string; length: string | null } {
  if (record.opened_on === null) return { text: TEXT.unknownOpened, length: null };
  let end: string | null = record.closed_on;
  let endText: string;
  if (end !== null) {
    endText = formatYearMonth(end);
  } else if (record.status in STATUS_BADGES) {
    end = dataAsOf;
    endText = TEXT.now;
  } else {
    endText = TEXT.unknownDate;
  }
  const length = end === null ? null : formatMonths(monthsBetween(record.opened_on, end));
  return { text: `${formatYearMonth(record.opened_on)} – ${endText}`, length };
}

function Badge({ children }: { children: string }) {
  return (
    <span className="border-line inline-block rounded-full border px-2 text-sm">{children}</span>
  );
}

function HoDots({ marks }: { marks: HoMark[] }) {
  return (
    <div className="mt-1 space-y-0.5">
      {marks.map((mark) => (
        <p key={mark.ho} className="flex items-center gap-1.5 text-sm" data-ho={mark.ho}>
          <span
            aria-hidden="true"
            data-testid="ho-dot"
            className="inline-block h-3 w-3 shrink-0 rounded-full"
            style={{ backgroundColor: mark.color }}
          />
          같은 호수({mark.ho}호)로 신고된 기록
        </p>
      ))}
    </div>
  );
}

function Item({
  record,
  marks,
  dataAsOf,
}: {
  record: TimelineRecord;
  marks: HoMark[];
  dataAsOf: string;
}) {
  const correct = useCorrection();
  const { text, length } = period(record, dataAsOf);
  const category = record.biz_category ?? LICENSE_LABELS[record.license_type] ?? null;
  const statusBadge = STATUS_BADGES[record.status];
  const bulk = bulkNote(record);
  return (
    <li className="border-line relative border-l-2 pb-4 pl-4">
      <span
        aria-hidden="true"
        className="bg-brand absolute top-2 -left-[5px] h-2 w-2 rounded-full"
      />
      <p className="font-bold break-words">{record.name}</p>
      {category && <p className="text-muted text-sm">{category}</p>}
      <p className="text-sm">
        {text}
        {length && <span className="text-muted"> · {length}</span>}
      </p>
      {(statusBadge || record.bulk_closure || record.stale_suspect) && (
        <div className="mt-1 flex flex-wrap gap-1">
          {statusBadge && <Badge>{statusBadge}</Badge>}
          {record.bulk_closure && <Badge>{TEXT.bulk}</Badge>}
          {record.stale_suspect && <Badge>{TEXT.stale}</Badge>}
        </div>
      )}
      {bulk && <p className="text-muted mt-1 text-sm">{bulk}</p>}
      {record.stale_suspect && <p className="text-muted mt-1 text-sm">{TEXT.staleNote}</p>}
      {marks.length > 0 && <HoDots marks={marks} />}
      {correct && (
        <button
          type="button"
          className="text-muted min-h-touch text-sm underline"
          onClick={() => correct(record.record_id)}
        >
          {TEXT.correct}
        </button>
      )}
    </li>
  );
}

/**
 * 세로 타임라인, 오래된 순(API 순서 그대로) (docs/40 §4.4-5, §4.3). 처음 {@link INITIAL_COUNT}건만 그리고
 * 나머지는 "전체 보기". 같은 호수 그룹 색은 전체 목록 기준이라 펼쳐도 같다
 */
export function FloorTimeline({
  history,
  hoGroups = [],
  dataAsOf,
  label,
}: {
  history: readonly TimelineRecord[];
  hoGroups?: readonly HoGroup[];
  dataAsOf: string;
  label: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const marks = useMemo(() => hoMarks(hoGroups), [hoGroups]);
  const shown = expanded ? history : history.slice(0, INITIAL_COUNT);
  return (
    <div>
      <ol aria-label={label} className="ml-1">
        {shown.map((record) => (
          <Item
            key={record.record_id}
            record={record}
            marks={marks.get(record.record_id) ?? []}
            dataAsOf={dataAsOf}
          />
        ))}
      </ol>
      {!expanded && history.length > INITIAL_COUNT && (
        <button
          type="button"
          className="border-line min-h-touch w-full rounded-lg border px-3"
          onClick={() => setExpanded(true)}
        >
          전체 보기({formatCount(history.length)}건)
        </button>
      )}
    </div>
  );
}
