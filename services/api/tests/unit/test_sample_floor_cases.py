"""층 기대값 표본 추출 (T-012). 여기의 주소 문자열은 모두 가상 예시다."""

from jobs.sample_floor_cases import is_tricky, sample_cases

PAIRS = [(f"가상상가 {n}층", f"{n}층") for n in range(1, 31)] + [
    (f"가상빌딩 지하{n}층 B10{n}호", "") for n in range(1, 10)
]


def test_same_seed_same_sample_regardless_of_order() -> None:
    first = sample_cases(PAIRS, seed=7, per_stratum=4)
    assert sample_cases(reversed(PAIRS + PAIRS), seed=7, per_stratum=4) == first
    assert sample_cases(PAIRS, seed=8, per_stratum=4) != first


def test_strata_sizes_and_no_duplicates() -> None:
    cases = sample_cases(PAIRS, seed=7, per_stratum=4)
    assert [case["no"] for case in cases] == list(range(1, 9))
    assert sum(case["stratum"] == "tricky" for case in cases) == 4
    assert len({(case["tail"], case["road_detail"]) for case in cases}) == 8
    assert all(
        is_tricky((str(case["tail"]), str(case["road_detail"])))
        for case in cases
        if case["stratum"] == "tricky"
    )
    assert all(case["expected"] is None for case in cases)


def test_tricky_patterns() -> None:
    for text in ["지하", "지층 일부", "상가B1", "2F", "1~2층", "2,3층", "옥탑", "옥상", "101호"]:
        assert is_tricky((text, "")), text
        assert is_tricky(("", text)), text
    assert not is_tricky(("가상상가 1층", "(가상동, 가상빌딩)"))
