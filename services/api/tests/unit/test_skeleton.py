"""저장소 골격: docs/01 §3의 패키지가 모두 import된다."""

import importlib

import pytest
from fastapi import FastAPI

PACKAGES = [
    "app.core",
    "app.common",
    "app.address",
    "app.location.ingest",
    "app.location.normalize",
    "app.location.history",
    "app.location.stats",
    "app.location.matching",
    "app.rules.dsl",
    "app.rules.engine",
    "app.rules.extraction",
    "app.rules.review",
    "app.rules.eval",
    "app.funding",
    "app.closure",
    "app.admin",
    "jobs",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_importable(name: str) -> None:
    importlib.import_module(name)


def test_app_is_fastapi() -> None:
    from app.main import app

    assert isinstance(app, FastAPI)
