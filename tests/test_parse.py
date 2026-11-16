"""ingestion.parse 单元测试。"""
from datetime import date

import pytest

from ingestion.parse import parse_geo, parse_loss

SAMPLE = {
    "id": 27530,
    "type": "Infantry mobility vehicles",
    "model": "ASN-233115 'Tigr-M SpN'",
    "status": "Destroyed",
    "lost_by": "Russia",
    "date": "2024-06-15",
    "nearest_location": "Kreminna, Siverskodonetsk raion",
    "geo": "50.434861,37.056194",
    "unit": None,
    "tags": "KUNG",
}


def test_parse_geo_normal():
    assert parse_geo("50.434861,37.056194") == (50.434861, 37.056194)
    assert parse_geo("47.85386711608142,37.453089553877895") == (47.85386711608142, 37.453089553877895)


def test_parse_geo_null_and_bad():
    assert parse_geo(None) == (None, None)
    assert parse_geo("") == (None, None)
    assert parse_geo("not-a-geo") == (None, None)
    assert parse_geo("999.0,37.0") == (None, None)  # 越界


def test_parse_loss_full():
    loss, lat, lon = parse_loss(SAMPLE)
    assert loss.id == 27530
    assert loss.date == date(2024, 6, 15)
    assert loss.status == "Destroyed"
    assert lat == 50.434861 and lon == 37.056194
    assert loss.sources is None  # 当前 API 未返回 sources，允许为空


def test_parse_loss_nullable_fields():
    raw = {**SAMPLE, "id": 1, "geo": None, "nearest_location": None, "model": None, "tags": None}
    loss, lat, lon = parse_loss(raw)
    assert lat is None and lon is None
    assert loss.model is None


def test_parse_loss_missing_required():
    with pytest.raises(Exception):
        parse_loss({"id": 1, "date": "2024-06-15"})  # 缺 type/status
