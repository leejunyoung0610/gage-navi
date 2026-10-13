"""모형 카드의 로지스틱 회귀·시군구별 적합·시간 외 검증 (docs/10 §7.3). 순수 계산만 한다.

사양은 `analysis/w0_location_signal.py`와 같다. 설계 행렬을 직접 만든다(더미는 첫 수준을 뺀다).
"""

import math
import warnings
from dataclasses import dataclass
from functools import partial

import numpy as np
import numpy.typing as npt
import pandas as pd
import statsmodels.api as sm
from statsmodels.tools.sm_exceptions import ConvergenceWarning

SPEC = (
    "event ~ min(prior,5) + 개업연도 + 업태(상위10+기타) + log(면적) + 시군구"
    " + 지하여부 + 2층이상여부"
)
SE = "층키 클러스터"
PRIOR_CAP = 5
TOP_CATEGORIES = 10
OTHER = "기타"
TRAIN_UNTIL, TEST_FROM, TEST_UNTIL = 2014, 2015, 2020
MAX_ITERATIONS = 100
_Z = 1.96


@dataclass(frozen=True)
class LogitFit:
    n: int
    or_per_prior: float
    ci_low: float
    ci_high: float
    p: float
    or_other_floor: float | None = None


@dataclass(frozen=True)
class SigunguFit:
    sigungu: str
    n: int
    fit: LogitFit | None  # 적합하지 못했으면 None


@dataclass(frozen=True)
class OutOfTime:
    n_train: int
    n_test: int
    auc_base: float
    auc_with_prior: float


def model_frame(cohort: pd.DataFrame) -> pd.DataFrame:
    """로지스틱 표본: 코호트 중 면적이 0보다 크고 시군구가 있는 기록, 변수 파생."""
    rows = cohort[(cohort["area_m2"] > 0) & cohort["sigungu_code"].notna()]
    category = rows["biz_category"].fillna("")
    top = category.value_counts().index[:TOP_CATEGORIES]
    floor = rows["floor"].astype(str)
    return pd.DataFrame(
        {
            "event": rows["event"].astype(int),
            "k": rows["prior"].clip(upper=PRIOR_CAP).astype("float64"),
            "other_floor": rows["other_floor"].astype("float64"),
            "area_l": np.log(rows["area_m2"]),
            "yr": rows["opened_on"].dt.year,
            "biz": category.where(category.isin(top), OTHER),
            "sigungu": rows["sigungu_code"].astype(str),
            "basement": floor.str.startswith("B").astype("float64"),
            "upper": (
                floor.str.fullmatch(r"\d+") & (pd.to_numeric(floor, errors="coerce") >= 2)
            ).astype("float64"),
            "cluster": rows.groupby(["pnu", "floor"], sort=False).ngroup(),
        }
    )


def _design(
    frame: pd.DataFrame, numeric: list[str], categorical: list[str], fit_rows: "pd.Series[bool]"
) -> pd.DataFrame:
    """상수 + 숫자 변수 + 더미. 적합에 쓰는 행에서 값이 하나뿐인 열은 뺀다."""
    dummies = [
        pd.get_dummies(frame[name], prefix=name, drop_first=True, dtype="float64")
        for name in categorical
    ]
    design = pd.concat([frame[numeric].astype("float64"), *dummies], axis=1)
    varying = design.loc[fit_rows].nunique() > 1
    design = design.loc[:, varying[varying].index]
    design.insert(0, "const", 1.0)
    return design


def fit_logit(
    frame: pd.DataFrame,
    *,
    other_floor: bool = False,
    by_sigungu: bool = True,
    cluster: bool = True,
    require_convergence: bool = True,
) -> LogitFit | None:
    """`k`(과거 폐업 1회)의 오즈비. 수렴하지 않거나 적합할 수 없으면 `None`."""
    numeric = ["k", *(["other_floor"] if other_floor else []), "area_l", "basement", "upper"]
    categorical = ["yr", "biz", *(["sigungu"] if by_sigungu else [])]
    design = _design(frame, numeric, categorical, pd.Series(True, index=frame.index))
    if "k" not in design.columns or (other_floor and "other_floor" not in design.columns):
        return None
    if frame["event"].nunique() < 2 or (cluster and frame["cluster"].nunique() < 2):
        return None
    options = (
        {"cov_type": "cluster", "cov_kwds": {"groups": frame["cluster"].to_numpy()}}
        if cluster
        else {}
    )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)  # 아래에서 직접 확인한다
            result = sm.Logit(frame["event"].to_numpy(), design).fit(
                disp=0, maxiter=MAX_ITERATIONS, **options
            )
    except (np.linalg.LinAlgError, ValueError, sm.tools.sm_exceptions.PerfectSeparationError):
        return None
    if require_convergence and not bool(result.mle_retvals["converged"]):
        return None
    beta, se = float(result.params["k"]), float(result.bse["k"])
    if not (math.isfinite(beta) and math.isfinite(se)):
        return None
    return LogitFit(
        n=int(result.nobs),
        or_per_prior=math.exp(beta),
        ci_low=math.exp(beta - _Z * se),
        ci_high=math.exp(beta + _Z * se),
        p=float(result.pvalues["k"]),
        or_other_floor=math.exp(float(result.params["other_floor"])) if other_floor else None,
    )


def fit_by_sigungu(frame: pd.DataFrame, *, cluster: bool = True) -> list[SigunguFit]:
    """시군구마다 따로 적합 (시군구 더미 없음).

    드문 업태·연도 더미 때문에 수렴 판정이 안 나는 구도 값을 낸다 (W0 스크립트와 같다. 판정에
    쓰는 값이 아니다).
    """
    fit = partial(fit_logit, by_sigungu=False, cluster=cluster, require_convergence=False)
    return [
        SigunguFit(str(code), len(rows), fit(rows))
        for code, rows in frame.groupby("sigungu", sort=True)
    ]


def auc(outcome: npt.NDArray[np.int64], score: npt.NDArray[np.float64]) -> float:
    """순위 합으로 구한 AUC (W0 스크립트와 같은 식)."""
    ranks = np.empty(len(score))
    ranks[np.argsort(score, kind="stable")] = np.arange(1, len(score) + 1)
    positive = outcome == 1
    n_pos, n_neg = int(positive.sum()), int((~positive).sum())
    return float((ranks[positive].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def out_of_time(frame: pd.DataFrame) -> OutOfTime | None:
    """2005–2014 개업으로 학습해 2015–2020 개업의 3년 내 폐업을 예측한 AUC."""
    train = frame["yr"] <= TRAIN_UNTIL
    test = (frame["yr"] >= TEST_FROM) & (frame["yr"] <= TEST_UNTIL)
    outcome = frame["event"].to_numpy(dtype=np.int64)
    if not train.any() or len(set(outcome[test.to_numpy()])) < 2:
        return None
    scores = []
    for numeric in (
        ["area_l", "basement", "upper", "yr"],
        ["area_l", "basement", "upper", "yr", "k"],
    ):
        design = _design(frame.astype({"yr": "float64"}), numeric, ["biz", "sigungu"], train)
        try:
            result = sm.Logit(outcome[train.to_numpy()], design[train]).fit(disp=0)
        except (np.linalg.LinAlgError, ValueError, sm.tools.sm_exceptions.PerfectSeparationError):
            return None
        predicted = np.asarray(result.predict(design[test]), dtype=np.float64)
        scores.append(auc(outcome[test.to_numpy()], predicted))
    return OutOfTime(int(train.sum()), int(test.sum()), scores[0], scores[1])
