"""to_wgs84 (T-014, ADR-026).

기대값은 `reports/crs_candidates.md`의 EPSG:5174 열이다. 사람이 카카오맵에서 핀이
주소 건물 위에 찍히는 것을 확인한 기록이다(ADR-026 결과표).
"""

import math

import pytest
from pyproj import Geod

from app.location.normalize.coords import SOURCE_EPSG, to_wgs84

# (구, 원천 X, 원천 Y, 위도, 경도)
VERIFIED = [
    ("강서구", 186317.207, 451462.350, 37.565341, 126.845916),
    ("노원구", 204790.425, 458749.281, 37.631086, 127.055057),
    ("영등포구", 191718.772, 446186.527, 37.517871, 126.907115),
    ("강동구", 212600.561, 449206.845, 37.545037, 127.143372),
    ("금천구", 190493.816, 439864.973, 37.460902, 126.893341),
    ("종로구", 197698.745, 452100.518, 37.571190, 126.974738),
]
# 표의 좌표는 소수 6자리(약 0.1m)로 적혀 있다
TOLERANCE_DEG = 1e-6
_GEOD = Geod(ellps="WGS84")


def test_source_crs_is_epsg_5174() -> None:
    assert SOURCE_EPSG == 5174


@pytest.mark.parametrize(("gu", "x", "y", "lat", "lng"), VERIFIED)
def test_matches_map_verified_records(gu: str, x: float, y: float, lat: float, lng: float) -> None:
    got_lat, got_lng = to_wgs84(x, y)
    assert got_lat == pytest.approx(lat, abs=TOLERANCE_DEG)
    assert got_lng == pytest.approx(lng, abs=TOLERANCE_DEG)


def test_returns_latitude_first() -> None:
    lat, lng = to_wgs84(197698.745, 452100.518)
    assert 37 < lat < 38
    assert 126 < lng < 128


def test_x_is_east_and_y_is_north_in_metres() -> None:
    lat, lng = to_wgs84(200000.0, 450000.0)
    east_lat, east_lng = to_wgs84(200100.0, 450000.0)
    north_lat, north_lng = to_wgs84(200000.0, 450100.0)

    assert east_lng > lng
    assert north_lat > lat
    _, _, east_m = _GEOD.inv(lng, lat, east_lng, east_lat)
    _, _, north_m = _GEOD.inv(lng, lat, north_lng, north_lat)
    assert east_m == pytest.approx(100.0, abs=0.1)
    assert north_m == pytest.approx(100.0, abs=0.1)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_rejects_non_finite_input(bad: float) -> None:
    with pytest.raises(ValueError):
        to_wgs84(bad, 450000.0)
    with pytest.raises(ValueError):
        to_wgs84(200000.0, bad)
