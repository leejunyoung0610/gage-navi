"""인허가 좌표(`좌표정보(X)`, `좌표정보(Y)`) → WGS84 (ADR-026)."""

import math
from functools import lru_cache

from pyproj import Transformer

# 원천 좌표계. 서로 다른 구 20건을 지도와 대조해 정했다 (ADR-026)
SOURCE_EPSG = 5174
WGS84_EPSG = 4326


@lru_cache(maxsize=1)
def _transformer() -> Transformer:
    return Transformer.from_crs(SOURCE_EPSG, WGS84_EPSG, always_xy=True)


def to_wgs84(x: float, y: float) -> tuple[float, float]:
    """원천 평면 좌표 (X=동쪽, Y=북쪽, m) → (위도, 경도).

    변환할 수 없는 값이면 `ValueError`. 빈 좌표는 호출하는 쪽에서 걸러 `None`으로 둔다.
    """
    lng, lat = _transformer().transform(x, y)
    if not (math.isfinite(lat) and math.isfinite(lng)):
        raise ValueError(f"WGS84로 변환할 수 없는 좌표: x={x!r}, y={y!r}")
    return lat, lng
