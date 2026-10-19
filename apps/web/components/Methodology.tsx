import type { ReactNode } from "react";

import { SCALE_LABELS, bucketLabel } from "@/components/BaseRateCard";
import { SigunguOrPlot } from "@/components/SigunguOrPlot";
import {
  formatCount,
  formatDate,
  formatFloatRate,
  formatFloatRateRange,
  formatPValue,
  formatRate,
  formatRateRange,
  formatSnapshotLabel,
  formatStat,
  formatStatRange,
} from "@/lib/format";
import {
  bucketOf,
  holds,
  type BucketOut,
  type ModelCard,
  type ModelCardData,
  type ScaleResult,
  type SearchMatch,
  type SettingResult,
} from "@/lib/methodology";

/**
 * 방법론 페이지 본문 (docs/40 §4.9, T-034). 숫자는 모두 `/stats/model-card` 응답에서 만든다.
 * 정의 문장의 고정값(1,095일 등)만 글로 쓴다(docs/40 §4.9).
 */

const NOT_READY = "아직 계산하지 않았어요.";

const FAILURE_LABELS: Record<SearchMatch["failures"][number]["type"], string> = {
  keyword_error: "검색어 오류",
  transport_error: "통신 오류",
  no_result: "결과 없음",
  jibun_changed: "지번 변경(추정)",
  other: "기타",
};
const NO_OPEN_DATE_BAND = "개업일 없음";

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-3">
      <h2 id={id} className="text-lg font-bold">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** 좁은 화면에서는 표만 가로로 밀린다(페이지는 밀리지 않는다) */
function DataTable({
  caption,
  headers,
  rows,
}: {
  caption: string;
  headers: readonly string[];
  rows: readonly (readonly ReactNode[])[];
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-max border-collapse text-sm">
        <caption className="text-muted mb-1 text-left">{caption}</caption>
        <thead>
          <tr className="border-line border-b">
            {headers.map((header) => (
              <th key={header} scope="col" className="px-2 py-1 text-left font-bold">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((cells, i) => (
            <tr key={i} className="border-line border-b">
              {cells.map((cell, j) =>
                j === 0 ? (
                  <th key={j} scope="row" className="px-2 py-1 text-left font-normal">
                    {cell}
                  </th>
                ) : (
                  <td key={j} className="px-2 py-1">
                    {cell}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function rateCell(bucket: BucketOut | null): string {
  return bucket === null ? "-" : `${formatRate(bucket.rate)} (${formatRateRange(bucket.ci)})`;
}

function orCell(logit: SettingResult["logit"]): string {
  return logit === null
    ? "계산하지 못했어요"
    : `${formatStat(logit.or_per_prior)} (${formatStatRange(logit.ci)})`;
}

/** 0회·4회 이상 버킷과 1회당 오즈비 — 설정·층 규모 표가 같이 쓴다 */
function comparisonCells(result: SettingResult | ScaleResult): ReactNode[] {
  return [
    formatCount(result.n),
    rateCell(bucketOf(result.buckets, "0")),
    rateCell(bucketOf(result.buckets, "4+")),
    orCell(result.logit),
  ];
}

const COMPARISON_HEADERS = [
  "대상 가게",
  "과거 폐업 0회",
  "과거 폐업 4회 이상",
  "1회당 오즈비 (95%)",
];

export function Methodology({ data }: { data: ModelCardData }) {
  const card = data.model_card;
  const match = data.search_match;
  return (
    <div className="space-y-10">
      <Sources card={card} />
      <SearchAccuracy match={match} />
      <PlaceDefinition />
      <ClosureDefinition card={card} />
      <SurgeDays card={card} />
      <Sensitivity card={card} />
      <Results card={card} />
      <Limits card={card} />
      <Updates card={card} methodVersion={data.method_version} match={match} />
    </div>
  );
}

function Sources({ card }: { card: ModelCard | null }) {
  return (
    <Section id="sources" title="데이터 출처와 기준일">
      <ul className="list-disc space-y-1 pl-5">
        <li>
          행정안전부 지방행정 인허가 데이터 중 서울의 식품 업소 세
          종류(일반음식점·휴게음식점·제과점영업)를 공공데이터포털에서 받아 써요. 영업 중인 곳과
          폐업한 곳이 모두 들어 있어요.
        </li>
        <li>주소 검색은 행정안전부 도로명주소 검색 API, 지명은 국토교통부 법정동 코드를 써요.</li>
        <li>지도는 카카오 지도를 써요.</li>
      </ul>
      <p>
        {card === null
          ? `통계 기준일: ${NOT_READY}`
          : `통계 기준일은 ${formatDate(card.data.as_of)}이에요(${formatSnapshotLabel(card.data.snapshot_label)} 데이터).`}
      </p>
    </Section>
  );
}

function SearchAccuracy({ match }: { match: SearchMatch | null }) {
  return (
    <Section id="search-match" title="주소 검색으로 필지를 찾는 정확도">
      <p>
        주소를 검색하면 도로명주소 검색 결과를 필지 하나로 연결해요. 이 연결이 인허가 기록의 필지와
        얼마나 맞는지, 기록을 미리 정한 방법으로 뽑아 직접 검색해 봤어요. 결과가 좋든 나쁘든 싣기로
        미리 정했어요.
      </p>
      {match === null ? <p>{NOT_READY}</p> : <SearchMatchResult match={match} />}
    </Section>
  );
}

function SearchMatchResult({ match }: { match: SearchMatch }) {
  const bands = match.by_open_year.filter((band) => band.band !== NO_OPEN_DATE_BAND);
  const oldest = bands[0];
  const newest = bands[bands.length - 1];
  const changed = match.failures.find((failure) => failure.type === "jibun_changed");
  return (
    <>
      <p className="text-muted text-sm">
        {formatDate(match.measured_on)}에 측정, 대상 기록 {formatCount(match.population)}건 중{" "}
        {formatCount(match.sample_size)}건
      </p>
      <dl className="space-y-3">
        <div>
          <dt>같은 건물의 필지를 찾은 비율</dt>
          <dd>
            <span className="text-xl font-bold">{formatRate(match.judged.rate)}</span>{" "}
            <span className="text-muted">({formatRateRange(match.judged.ci)})</span>
            <p className="text-muted text-sm">
              검색 결과의 대표 지번이 기록의 필지와 같거나, 같은 건물의 관련 지번에 기록의 지번이
              있으면 찾은 것으로 셌어요. 괄호는 95% 신뢰구간(Wilson)이에요.
            </p>
          </dd>
        </div>
        <div>
          <dt>검색 결과를 눌러 바로 그 기록의 필지로 가는 비율</dt>
          <dd>
            <span className="text-xl font-bold">{formatRate(match.reference.rate)}</span>{" "}
            <span className="text-muted">({formatRateRange(match.reference.ci)})</span>
            <p className="text-muted text-sm">
              대표 지번만 셌어요. 같은 건물의 다른 필지에 기록이 있던{" "}
              {formatCount(match.related_only.count)}건({formatRate(match.related_only.share)})은
              필지 페이지의 &ldquo;같은 건물의 다른 필지 기록&rdquo;에서 찾을 수 있어요.
            </p>
          </dd>
        </div>
      </dl>
      {oldest && newest && oldest !== newest ? (
        <p>
          오래된 기록일수록 지금 주소와 덜 연결돼요. {oldest.band} 개업 기록은{" "}
          {formatRate(oldest.rate)}, {newest.band} 개업 기록은 {formatRate(newest.rate)}였어요.
          오래된 가게의 이력은 빠져 보일 수 있어요.
        </p>
      ) : null}
      <DataTable
        caption="개업연도별 (같은 건물의 필지를 찾은 비율)"
        headers={["개업연도", "기록", "찾은 비율 (95%)", "바로 가는 비율"]}
        rows={match.by_open_year.map((band) => [
          band.band,
          formatCount(band.n),
          `${formatRate(band.rate)} (${formatRateRange(band.ci)})`,
          formatRate(band.reference_rate),
        ])}
      />
      {changed ? (
        <p>
          <strong>지번 변경(추정)</strong>: 같은 건물을 찾았지만 기록의 지번이 대표 지번·관련 지번
          어디에도 없는 경우가 {formatCount(changed.count)}건({formatRate(changed.share)})이었어요.
          지번이 실제로 바뀌었는지, 기록의 지번이 틀렸는지는 이 측정으로 가를 수 없어요.
        </p>
      ) : null}
      <DataTable
        caption="찾지 못한 기록의 유형"
        headers={["유형", "기록", "비율"]}
        rows={match.failures.map((failure) => [
          FAILURE_LABELS[failure.type],
          formatCount(failure.count),
          formatRate(failure.share),
        ])}
      />
    </>
  );
}

function PlaceDefinition() {
  return (
    <Section id="place" title="자리(층)를 어떻게 정했나요">
      <ul className="list-disc space-y-1 pl-5">
        <li>
          자리는 필지(지번) 하나의 층 하나예요. 인허가 기록의 지번주소에서 필지를, 주소 뒤의 상세
          표기에서 층을 읽어요.
        </li>
        <li>같은 층의 호수는 표기가 제각각이라 나누지 않아요.</li>
        <li>
          층을 읽을 수 없는 기록은 층 이력과 통계에 넣지 않고, 필지 페이지에 따로 보여 드려요.
        </li>
        <li>
          층 규모: 그 층에서 영업 기간이 30일 넘게 겹친 가게 수의 최댓값으로 나눠요.{" "}
          {SCALE_LABELS.single}(1곳), {SCALE_LABELS.small}, {SCALE_LABELS.large}. 통계에서는 각
          가게가 문을 연 날까지의 이력으로만 세요.
        </li>
      </ul>
    </Section>
  );
}

function ClosureDefinition({ card }: { card: ModelCard | null }) {
  return (
    <Section id="definitions" title="과거 폐업 횟수와 3년 내 폐업">
      <ul className="list-disc space-y-1 pl-5">
        <li>
          <strong>과거 폐업 횟수</strong>: 가게가 문을 연 날보다 전에 같은 층에서 폐업한 가게
          수예요. 같은 날 폐업·개업은 세지 않고, 폐업 처리가 몰린 날(아래)의 폐업도 세지 않아요.
          0회, 1회, 2회, 3회, 4회 이상으로 나눠요.
        </li>
        <li>
          <strong>3년 내 폐업</strong>: 문을 연 날부터 1,095일 안에 폐업한 경우예요.
        </li>
        <li>
          <strong>대상</strong>:{" "}
          {card === null
            ? NOT_READY
            : `${formatDate(card.data.cohort_from)}부터 ${formatDate(card.data.cohort_to)}까지 문을 연 가게 ${formatCount(card.data.n)}건이에요. 3년이 지나 결과를 알 수 있는 가게만 넣었어요.`}{" "}
          편의점은 대상에서 빼요.
        </li>
        <li>
          비율의 95% 신뢰구간은 Wilson 방법으로 계산해요. 층 페이지에는 비슷한 자리가 200곳 이상일
          때만 보여 드려요.
        </li>
      </ul>
    </Section>
  );
}

function SurgeDays({ card }: { card: ModelCard | null }) {
  const sensitivity = card?.sensitivity ?? null;
  return (
    <Section id="surge" title="폐업 처리가 몰린 날">
      <p>
        한 관할에서 하루에 폐업이 30건 이상, 평소(폐업이 있던 날의 중앙값)의 10배 이상 처리된 날을
        &ldquo;폐업 처리 몰린 날&rdquo;로 봐요. 실제로 문을 닫은 날은 더 이를 수 있어서, 기본
        설정에서는 이날 폐업한 가게를 대상과 과거 폐업 횟수에서 빼요. 왜 몰렸는지는 데이터로 확인할
        수 없어요.
      </p>
      {sensitivity === null ? (
        <p>{NOT_READY}</p>
      ) : (
        <>
          <DataTable
            caption="처리 방법 세 가지 비교 (서울 전체)"
            headers={["처리 방법", ...COMPARISON_HEADERS]}
            rows={[
              ["빼지 않음", ...comparisonCells(sensitivity.bulk_exclusion.none)],
              [
                "몰린 날 규칙으로 뺌 (기본)",
                ...comparisonCells(sensitivity.bulk_exclusion.surge_rule),
              ],
              [
                "서울 전체 하루 100건 이상인 날의 일반음식점 폐업을 뺌",
                ...comparisonCells(sensitivity.bulk_exclusion.w0_citywide_100),
              ],
            ]}
          />
          <CensoredNote censored={sensitivity.bulk_as_censored} />
        </>
      )}
    </Section>
  );
}

function CensoredNote({
  censored,
}: {
  censored: NonNullable<ModelCard["sensitivity"]>["bulk_as_censored"];
}) {
  const zero = censored.buckets.find((bucket) => bucket.bucket === "0");
  const many = censored.buckets.find((bucket) => bucket.bucket === "4+");
  if (!zero || !many) return null;
  return (
    <p className="text-sm">
      참고: 몰린 날의 폐업을 빼지 않고 &ldquo;그날까지 영업했다&rdquo;고만 보면(중도절단,
      Kaplan–Meier) 3년 내 폐업률은 과거 폐업 0회 {formatFloatRate(zero.rate)} (
      {formatFloatRateRange(zero.ci)}), 4회 이상 {formatFloatRate(many.rate)} (
      {formatFloatRateRange(many.ci)})예요.
    </p>
  );
}

function Sensitivity({ card }: { card: ModelCard | null }) {
  const sensitivity = card?.sensitivity ?? null;
  const robustness = card?.robustness ?? null;
  return (
    <Section id="sensitivity" title="설정을 하나씩 바꿔 본 결과">
      <p>
        결론 &ldquo;과거 폐업이 많은 층에 새로 연 가게의 3년 내 폐업률이 더 높다&rdquo;가 설정을
        바꿔도 유지되는지 봤어요. 기본 설정에서 한 번에 한 가지만 바꿨고, 아래 두 기준을 결과를 보기
        전에 정했어요.
      </p>
      <ol className="list-decimal space-y-1 pl-5 text-sm">
        <li>과거 폐업 4회 이상 자리의 폐업률 신뢰구간이 0회 자리보다 위에 있고 겹치지 않아요.</li>
        <li>
          개업연도·업태·면적·시군구·층을 함께 고려한 로지스틱 회귀에서 과거 폐업 1회당 오즈비의 95%
          신뢰구간 하한이 1보다 커요.
        </li>
      </ol>
      {sensitivity === null || robustness === null ? (
        <p>{NOT_READY}</p>
      ) : (
        <>
          <p className="font-bold">
            {robustness.holds
              ? "모든 설정에서 두 기준을 함께 만족했어요."
              : "두 기준을 만족하지 못한 설정이 있어요."}
          </p>
          <DataTable
            caption="설정별 결과 (서울 전체)"
            headers={["설정", ...COMPARISON_HEADERS, "결론"]}
            rows={settingRows(sensitivity).map(([label, result]) => [
              label,
              ...comparisonCells(result),
              holds(result) ? "유지" : "유지 안 됨",
            ])}
          />
          <DataTable
            caption="참고: 인허가 종류별 (판정에 쓰지 않아요)"
            headers={["종류", ...COMPARISON_HEADERS]}
            rows={[
              ["일반음식점", ...comparisonCells(sensitivity.license_type.general_restaurant)],
              ["휴게음식점", ...comparisonCells(sensitivity.license_type.rest_restaurant)],
              ["제과점영업", ...comparisonCells(sensitivity.license_type.bakery)],
            ]}
          />
        </>
      )}
    </Section>
  );
}

function settingRows(
  sensitivity: NonNullable<ModelCard["sensitivity"]>,
): [string, SettingResult][] {
  return [
    ["기본 설정", sensitivity.bulk_exclusion.surge_rule],
    ["폐업 처리 몰린 날: 빼지 않음", sensitivity.bulk_exclusion.none],
    ["폐업 처리 몰린 날: 서울 전체 하루 100건 기준", sensitivity.bulk_exclusion.w0_citywide_100],
    ["편의점 포함", sensitivity.convenience_store.included],
    ["신고 지연 의심 제외: 같은 호", sensitivity.exclude_stale.same_ho],
    ["신고 지연 의심 제외: 같은 호 또는 면적", sensitivity.exclude_stale.same_ho_or_area],
    [
      "층 미상 폐업이 있는 필지 제외",
      sensitivity.floor_unknown.exclude_parcels_with_floorless_closure,
    ],
  ];
}

function Results({ card }: { card: ModelCard | null }) {
  return (
    <Section id="results" title="결과">
      {card === null ? (
        <p>{NOT_READY}</p>
      ) : (
        <>
          <p>
            대상 {formatCount(card.data.n)}건 중 3년 안에 폐업한 비율은{" "}
            {formatRate(card.data.event_rate)}예요.
          </p>
          <DataTable
            caption="과거 폐업 횟수별 3년 내 폐업률 (서울 전체, 기본 설정)"
            headers={["과거 폐업", "대상 가게", "3년 내 폐업률", "95% 신뢰구간"]}
            rows={card.base_rates.map((bucket) => [
              bucketLabel(bucket.bucket),
              formatCount(bucket.n),
              formatRate(bucket.rate),
              formatRateRange(bucket.ci),
            ])}
          />
          <LogitResult logit={card.logit} />
          <FloorScaleResult scales={card.by_floor_scale} />
          <SigunguResult card={card} />
          <OutOfTime outOfTime={card.out_of_time} />
        </>
      )}
    </Section>
  );
}

function LogitResult({ logit }: { logit: ModelCard["logit"] }) {
  if (logit === null) return null;
  const other = logit.with_other_floor_control;
  return (
    <div className="space-y-1">
      <h3 className="font-bold">로지스틱 회귀</h3>
      <p>
        개업연도·업태·면적·시군구·지하 여부·2층 이상 여부를 함께 고려해도 과거 폐업이 1회 많을
        때마다 3년 내 폐업의 오즈가 {formatStat(logit.or_per_prior)}배였어요(95% 신뢰구간{" "}
        {formatStatRange(logit.ci)}, p {formatPValue(logit.p)}, {formatCount(logit.n)}건). 같은 층
        가게끼리 묶어 표준오차를 계산했어요. 면적이나 시군구가 없는 기록은 빠져요.
      </p>
      {other ? (
        <p className="text-sm">
          같은 필지 다른 층의 과거 폐업 수를 함께 넣어도 1회당 오즈비는{" "}
          {formatStat(other.or_per_prior)}({formatStatRange(other.ci)})이고, 다른 층 폐업 1회당은{" "}
          {formatStat(other.or_other_floor)}배였어요.
        </p>
      ) : null}
    </div>
  );
}

function FloorScaleResult({ scales }: { scales: ModelCard["by_floor_scale"] }) {
  if (scales === null) return null;
  const rows: [keyof typeof SCALE_LABELS, ScaleResult][] = [
    ["single", scales.single],
    ["small", scales.small],
    ["large", scales.large],
  ];
  const failed = rows.filter(([, result]) => !result.holds);
  return (
    <div className="space-y-2">
      <h3 className="font-bold">층 규모별</h3>
      <p>
        층 페이지의 기준율 카드는 그 층의 규모에 맞는 값을 써요. 규모마다 위 두 기준을 다시 봤어요.
      </p>
      <DataTable
        caption="층 규모별 결과 (서울 전체)"
        headers={["층 규모", ...COMPARISON_HEADERS, "검증 기준"]}
        rows={rows.map(([scale, result]) => [
          SCALE_LABELS[scale],
          ...comparisonCells(result),
          result.holds ? "통과" : "통과 못 함",
        ])}
      />
      {failed.length > 0 ? (
        <p className="text-sm">
          {failed.map(([scale]) => SCALE_LABELS[scale]).join(", ")}에서는 검증 기준을 통과하지
          못해서, 이 규모의 층 페이지에는 기준율 카드 대신 그 사실만 보여 드려요.
        </p>
      ) : null}
    </div>
  );
}

function SigunguResult({ card }: { card: ModelCard }) {
  const items = card.by_sigungu;
  if (items.length === 0) return null;
  const above = items.filter((item) => item.or !== null && item.or > 1).length;
  const lowerAbove = items.filter((item) => item.ci !== null && item.ci[0] > 1).length;
  return (
    <div className="space-y-2">
      <h3 className="font-bold">시군구별</h3>
      <p>
        시군구 {formatCount(items.length)}곳 중 {formatCount(above)}곳에서 1회당 오즈비가 1보다
        컸고, 그중 95% 신뢰구간 하한까지 1보다 큰 곳은 {formatCount(lowerAbove)}곳이에요.
      </p>
      <SigunguOrPlot items={items} />
    </div>
  );
}

function OutOfTime({ outOfTime }: { outOfTime: ModelCard["out_of_time"] }) {
  if (outOfTime === null) return null;
  return (
    <div className="space-y-1">
      <h3 className="font-bold">개별 예측력은 매우 작아요</h3>
      <p>
        {outOfTime.train}년에 문을 연 가게로 모형을 만들고 {outOfTime.test}년에 문을 연 가게로
        확인했어요(시간 외 검증). 과거 폐업 횟수를 넣어도 시간 외 검증 AUC가{" "}
        {formatStat(outOfTime.auc_base)} → {formatStat(outOfTime.auc_with_prior)}예요. AUC는 0.5면
        동전 던지기, 1이면 완벽하게 가려낸다는 뜻이에요.
      </p>
      <p>
        한 가게가 3년 안에 폐업할지를 가려내는 힘은 매우 작아요. 이 숫자로 개별 가게의 앞날을
        예측하지 않아요. 그래서 가게내비는 점수나 확률을 만들지 않고, 비슷한 자리들의 실제 결과만
        신뢰구간과 함께 보여 드려요.
      </p>
    </div>
  );
}

function Limits({ card }: { card: ModelCard | null }) {
  const large = card?.by_floor_scale?.large ?? null;
  const largeMany = large ? bucketOf(large.buckets, "4+") : null;
  return (
    <Section id="limits" title="한계">
      <ul className="list-disc space-y-1 pl-5">
        <li>
          데이터에는 신고된 사실만 있어요. 실제로 언제까지 영업했는지, 왜 폐업했는지는 알 수 없어요.
        </li>
        <li>
          폐업 신고가 늦어지면 폐업일이 실제보다 늦게 적혀요. 같은 호수로 나중에 다른 가게가 영업
          신고를 한 기록을 빼 본 결과는 위 설정별 결과에 있어요.
        </li>
        <li>
          층을 읽을 수 없는 기록(특히 2005년 전 기록)은 통계에 들어가지 않아요. 그래서 과거 폐업
          횟수가 실제보다 적게 세어졌을 수 있어요.
        </li>
        {large && largeMany && large.n > 0 ? (
          <li>
            {SCALE_LABELS.large}은 대상 {formatCount(large.n)}건 중{" "}
            {formatFloatRate(largeMany.n / large.n)}가 과거 폐업 4회 이상이에요. 과거 폐업 횟수의
            폭이 넓어 &ldquo;1회당 오즈비&rdquo;가 관계를 잘 담지 못할 수 있어요.
          </li>
        ) : null}
        <li>
          주소 검색이 필지를 못 찾거나 다른 필지로 연결하면 이력이 빠져 보일 수 있어요(위 정확도
          참고). 오래된 기록일수록 더 그래요.
        </li>
        <li>이 통계는 이 자리에 열 가게의 성패를 예측하지 않아요. 참고 통계예요.</li>
      </ul>
    </Section>
  );
}

function Updates({
  card,
  methodVersion,
  match,
}: {
  card: ModelCard | null;
  methodVersion: string | null;
  match: SearchMatch | null;
}) {
  return (
    <Section id="updates" title="갱신 주기">
      <p>인허가 데이터를 새로 받으면 통계를 다시 계산해요(월 1회).</p>
      <ul className="list-disc space-y-1 pl-5 text-sm">
        <li>
          지금 통계:{" "}
          {card === null || methodVersion === null
            ? NOT_READY
            : `${formatSnapshotLabel(card.data.snapshot_label)} 데이터, 계산 방법 버전 ${methodVersion}`}
        </li>
        <li>
          검색 정확도:{" "}
          {match === null ? NOT_READY : `${formatDate(match.measured_on)}에 한 번 잰 값이에요.`}
        </li>
      </ul>
    </Section>
  );
}
