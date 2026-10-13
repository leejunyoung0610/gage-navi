"""기준율·민감도 리포트 (`reports/base_rates.md`, docs/10 §7.3). 모형 카드에서 글만 만든다."""

from decimal import Decimal

from app.location.stats.card import BucketOut, ModelCardPayload, SettingResult

AXIS_LABELS = {
    "bulk_exclusion": "급증일",
    "convenience_store": "편의점",
    "exclude_stale": "신고 지연",
    "floor_unknown": "층 미상",
}
VALUE_LABELS = {
    ("bulk_exclusion", "none"): "제외 없음",
    ("bulk_exclusion", "surge_rule"): "새 규칙",
    ("bulk_exclusion", "w0_citywide_100"): "W0 정의(서울 전체 하루 100건)",
    ("convenience_store", "excluded"): "제외",
    ("convenience_store", "included"): "포함",
    ("exclude_stale", "none"): "제외 없음",
    ("exclude_stale", "same_ho"): "같은 호만 제외",
    ("exclude_stale", "same_ho_or_area"): "같은 호 또는 면적 제외",
    ("floor_unknown", "all"): "전체",
    (
        "floor_unknown",
        "exclude_parcels_with_floorless_closure",
    ): "층 미상 폐업 기록이 있는 필지 제외",
}


def _pct(value: Decimal | float) -> str:
    return f"{Decimal(str(value)) * 100:.2f}%"


def _rate(bucket: BucketOut | None) -> str:
    if bucket is None:
        return "—"
    return f"{_pct(bucket.rate)} ({_pct(bucket.ci[0])}~{_pct(bucket.ci[1])})"


def _mark(passed: bool) -> str:
    return "유지" if passed else "**깨짐**"


def _bucket(result: SettingResult, name: str) -> BucketOut | None:
    return next((bucket for bucket in result.buckets if bucket.bucket == name), None)


def variants(card: ModelCardPayload) -> list[tuple[str, str, SettingResult]]:
    """기본 설정 한 줄 + 한 항목씩 바꾼 설정들."""
    if card.sensitivity is None:
        return []
    rows: list[tuple[str, str, SettingResult]] = []
    for axis in AXIS_LABELS:
        for value, result in getattr(card.sensitivity, axis):
            if not result.is_default:
                rows.append((AXIS_LABELS[axis], VALUE_LABELS[(axis, value)], result))
            elif not rows or not rows[0][2].is_default:
                rows.insert(0, ("기본", "(기본 설정)", result))
    return rows


def render(card: ModelCardPayload, method_version: str, saved: bool) -> str:
    data = card.data
    lines = [
        "# 기준율·민감도 리포트 (T-019)",
        "",
        "`python -m jobs.compute_base_rates`가 만든다. 정의와 판정 기준은 docs/10 §7.2·§7.3.",
        "",
        f"- method_version `{method_version}`, 스냅샷 `{data.snapshot_label}`, 기준일 {data.as_of}",
        f"- 코호트: {data.cohort_from} ~ {data.cohort_to} 개업, {data.n:,}건,"
        f" 3년 내 폐업률 {_pct(data.event_rate)}",
    ]
    if card.default_setting is not None:
        setting = card.default_setting
        lines.append(
            "- 기본 설정: "
            + ", ".join(
                f"{AXIS_LABELS[axis]} = {VALUE_LABELS[(axis, getattr(setting, axis))]}"
                for axis in AXIS_LABELS
            )
        )
    if card.robustness is not None:
        lines += ["", "## 판정", ""]
        if card.robustness.holds:
            lines.append("모든 설정에서 (a)(b)가 유지됐다. 기본 설정의 기준율을 저장했다.")
        else:
            lines.append("**깨진 설정이 있다. `base_rate`·`model_card`를 쓰지 않았다.**")
            lines += [
                f"- {failure.axis} = {failure.value}, ({failure.criterion}): {failure.detail}"
                for failure in card.robustness.failures
            ]
        if card.robustness.holds != saved:
            lines.append(f"(저장 여부: {saved})")

    lines += ["", "## 기본 설정의 기준율 (서울 전체)", ""]
    lines += ["| 과거 폐업 | n | 3년 내 폐업 | 비율 | Wilson 95% |", "|---|---|---|---|---|"]
    lines += [
        f"| {b.bucket} | {b.n:,} | {b.events:,} | {_pct(b.rate)} |"
        f" {_pct(b.ci[0])}~{_pct(b.ci[1])} |"
        for b in card.base_rates
    ]

    rows = variants(card)
    if rows:
        base = _bucket(rows[0][2], "4+")
        lines += ["", "## 설정별 결과 (기본에서 한 항목씩)", ""]
        lines += [
            "| 축 | 설정 | n | 0 버킷 | 4+ 버킷 | 1회당 OR (95%) | (a) | (b) |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for axis, label, result in rows:
            logit = result.logit
            odds = (
                "적합 실패"
                if logit is None
                else f"{logit.or_per_prior:.3f} ({logit.ci[0]:.3f}~{logit.ci[1]:.3f})"
            )
            lines.append(
                f"| {axis} | {label} | {result.n:,} | {_rate(_bucket(result, '0'))} |"
                f" {_rate(_bucket(result, '4+'))} | {odds} | {_mark(result.criterion_a)} |"
                f" {_mark(result.criterion_b)} |"
            )
        lines += ["", "## 4+ 버킷 폐업률이 설정마다 움직인 폭", ""]
        lines += [
            "| 축 | 설정 | 4+ n | 4+ 폐업률 | Wilson 95% | 기본 대비 | 0 버킷 | 4+ − 0 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for axis, label, result in rows:
            four, zero = _bucket(result, "4+"), _bucket(result, "0")
            if four is None or zero is None or base is None:
                lines.append(f"| {axis} | {label} | — | — | — | — | — | — |")
                continue
            lines.append(
                f"| {axis} | {label} | {four.n:,} | {_pct(four.rate)} |"
                f" {_pct(four.ci[0])}~{_pct(four.ci[1])} |"
                f" {(four.rate - base.rate) * 100:+.2f}%p | {_pct(zero.rate)} |"
                f" {(four.rate - zero.rate) * 100:+.2f}%p |"
            )
        fours = [b.rate for b in (_bucket(result, "4+") for _, _, result in rows) if b is not None]
        if fours:
            lines += [
                "",
                f"4+ 버킷 폐업률의 범위: {_pct(min(fours))} ~ {_pct(max(fours))}"
                f" (폭 {(max(fours) - min(fours)) * 100:.2f}%p)",
            ]

    if card.sensitivity is not None:
        censored = card.sensitivity.bulk_as_censored
        lines += ["", "## 참고: 급증일 폐업을 중도절단으로 (판정에 넣지 않는다)", ""]
        lines.append(
            f"기본 설정에서 급증일 폐업 기록을 코호트에 두고({censored.n:,}건) 그 폐업을"
            " 중도절단으로 본 Kaplan–Meier 1,095일 내 폐업 비율."
        )
        lines += [
            "",
            "| 과거 폐업 | n | 중도절단 | 비율 | 95% (Greenwood) |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {b.bucket} | {b.n:,} | {b.censored:,} | {_pct(b.rate)} |"
            f" {_pct(b.ci[0])}~{_pct(b.ci[1])} |"
            for b in censored.buckets
        ]

    lines += ["", "## 로지스틱 (기본 설정)", ""]
    if card.logit is None:
        lines.append("적합 실패.")
    else:
        logit = card.logit
        lines += [
            f"- 사양: `{logit.spec}`, 표준오차: {logit.se}, n = {logit.n:,}",
            f"- 과거 폐업 1회당 OR {logit.or_per_prior:.3f}"
            f" ({logit.ci[0]:.3f}~{logit.ci[1]:.3f}), p = {logit.p:.1e}",
        ]
        other = logit.with_other_floor_control
        if other is not None:
            lines.append(
                f"- 같은 필지 다른 층 폐업 통제: OR {other.or_per_prior:.3f}"
                f" ({other.ci[0]:.3f}~{other.ci[1]:.3f}), 다른 층 폐업 1회당 OR"
                f" {other.or_other_floor:.3f}"
            )
    if card.out_of_time is not None:
        oot = card.out_of_time
        lines.append(
            f"- 시간 외 검증({oot.train} 학습 → {oot.test} 개업): AUC {oot.auc_base:.4f} →"
            f" {oot.auc_with_prior:.4f} (과거 폐업 횟수를 더했을 때)"
        )
    if card.by_sigungu:
        fitted = [item for item in card.by_sigungu if item.or_ is not None and item.ci is not None]
        above = sum(1 for item in fitted if item.ci is not None and item.ci[0] > 1)
        below = sum(1 for item in fitted if item.ci is not None and item.ci[1] < 1)
        lines += [
            "",
            "## 시군구별 (구마다 따로 적합)",
            "",
            f"{len(card.by_sigungu)}곳 중 OR > 1: "
            f"{sum(1 for item in fitted if item.or_ is not None and item.or_ > 1)}곳,"
            f" 95% 구간 하한 > 1: {above}곳, 상한 < 1: {below}곳.",
            "",
            "| 시군구 | n | OR | 95% |",
            "|---|---|---|---|",
        ]
        for item in sorted(card.by_sigungu, key=lambda item: (item.or_ is None, item.or_ or 0)):
            if item.or_ is None or item.ci is None:
                lines.append(f"| {item.sigungu} | {item.n:,} | 적합 실패 | — |")
            else:
                lines.append(
                    f"| {item.sigungu} | {item.n:,} | {item.or_:.3f} |"
                    f" {item.ci[0]:.3f}~{item.ci[1]:.3f} |"
                )
    return "\n".join(lines) + "\n"
