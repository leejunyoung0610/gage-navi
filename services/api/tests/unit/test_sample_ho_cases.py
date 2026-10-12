"""호 기대값 표본 추출 (T-013). 여기의 주소 문자열은 모두 가상 예시다."""

from jobs.sample_ho_cases import has_ho, is_tricky, sample_cases

PAIRS = [(f"가상상가 1층 {n}호", f"1층 {n}호") for n in range(101, 131)] + [
    (f"가상빌딩 지하1층 B0{n}호", "") for n in range(1, 10)
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
    for case in cases:
        pair = (str(case["tail"]), str(case["road_detail"]))
        assert has_ho(pair) if case["stratum"] == "random" else is_tricky(pair)
    assert all(case["expected"] is None for case in cases)


def test_tricky_patterns() -> None:
    for text in [
        "가상역 2호선",
        "505호일부",
        "214~215호",
        "101,102호",
        "201-5호",
        "A105호",
        "101B호",
        "B01호",
        "1층 121",
        "101,102,103",
    ]:
        assert is_tricky((text, "")), text
        assert is_tricky(("", text)), text
    assert not is_tricky(("가상상가 1층 101호", "(가상동, 가상빌딩)"))
    assert has_ho(("", "1층 101 호"))
    assert not has_ho(("가상상가 1층", ""))
