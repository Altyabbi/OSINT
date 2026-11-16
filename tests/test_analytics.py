"""analytics 统计计算单元测试（SQLite 内存假数据）。"""
from datetime import date, timedelta

import pytest

from analytics import stats
from ingestion.pipeline import upsert_losses
from storage.db import get_engine, init_db, session_factory


def rec(id_: int, day: date, type_: str = "Tanks", model: str = "T-72B3",
        status: str = "Destroyed", loc: str | None = "Avdiivka",
        geo: str | None = "48.15,37.75") -> dict:
    return {"id": id_, "type": type_, "model": model, "status": status,
            "lost_by": "Russia", "date": day.isoformat(), "nearest_location": loc,
            "geo": geo, "unit": None, "tags": None}


@pytest.fixture()
def session():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    factory = session_factory(engine)
    s = factory()
    base = date(2024, 6, 1)
    records = []
    rid = 1
    for i in range(14):  # 14 天，每天 2 条坦克
        for _ in range(2):
            records.append(rec(rid, base + timedelta(days=i)))
            rid += 1
    # 第 14 天（6-15）额外加 3 条：1 无人机、2 坦克 damaged
    records.append(rec(rid, date(2024, 6, 14), type_="Drones", model="Orlan-10",
                       status="Captured", loc="Kharkiv", geo="50.0,36.2"))
    rid += 1
    for _ in range(3):
        records.append(rec(rid, date(2024, 6, 14), status="Damaged", loc=None, geo=None))
        rid += 1
    upsert_losses(s, records)
    yield s
    s.close()


def test_total_and_filters(session):
    assert stats.total_losses(session, date(2024, 6, 1), date(2024, 6, 14)) == 32
    assert stats.total_losses(session, date(2024, 6, 1), date(2024, 6, 14), type_="Tanks") == 31
    assert stats.total_losses(session, date(2024, 6, 1), date(2024, 6, 14), model="orlan") == 1
    assert stats.total_losses(session, region="kharkiv") == 1


def test_count_by_field(session):
    by_type = stats.count_by_field(session, "type", date(2024, 6, 1), date(2024, 6, 14))
    assert {d["key"]: d["count"] for d in by_type} == {"Tanks": 31, "Drones": 1}
    by_status = stats.count_by_field(session, "status", date(2024, 6, 14), date(2024, 6, 14))
    assert {d["key"]: d["count"] for d in by_status} == {"Destroyed": 2, "Damaged": 3, "Captured": 1}


def test_daily_counts_fills_zeros(session):
    daily = stats.daily_counts(session, date(2024, 6, 14), date(2024, 6, 16))
    assert [d["count"] for d in daily] == [6, 0, 0]


def test_trend_granularities(session):
    weekly = stats.trend(session, date(2024, 6, 1), date(2024, 6, 14), "week")
    assert sum(p["count"] for p in weekly) == 32
    assert weekly[0]["period"] == "2024-W22"
    monthly = stats.trend(session, date(2024, 6, 1), date(2024, 6, 14), "month")
    assert monthly == [{"period": "2024-06", "count": 32}]
    with pytest.raises(ValueError):
        stats.trend(session, date(2024, 6, 1), date(2024, 6, 14), "year")


def test_geo_and_radius(session):
    points = stats.geo_points(session)
    assert len(points) == 29  # 3 条无坐标
    # Avdiivka (48.15, 37.75) 半径 20km 内的 28 条；Kharkiv 点在 150km+ 外
    hits = stats.losses_in_radius(session, 48.15, 37.75, 20.0)
    assert len(hits) == 28
    # 23km 外的空点 + 5km 半径 → 无命中
    assert stats.losses_in_radius(session, 48.0, 37.6, 5.0) == []


def test_baseline_compare(session):
    b = stats.baseline_compare(session, date(2024, 6, 15))
    assert b["day_total"] == 0
    assert b["avg7"] == 2.6  # (2*6 + 6) / 7
    assert b["pct_change_7d"] == -100.0
    b2 = stats.baseline_compare(session, date(2024, 6, 14))
    assert b2["day_total"] == 6
    assert b2["avg7"] == 2.0
    assert any(a["direction"] == "偏高" for a in b2["anomalies"])


def test_haversine():
    assert stats.haversine_km(48.15, 37.75, 48.15, 37.75) == 0.0
    d = stats.haversine_km(50.45, 30.52, 48.15, 37.75)  # 基辅 → 阿夫迪夫卡
    assert 550 < d < 650
