"""ingestion upsert 幂等性 + 状态流转追踪测试（SQLite + 假数据，不打外网）。"""
import json
from datetime import date

import pytest
from sqlalchemy import func, select

from ingestion.pipeline import save_raw_snapshot, upsert_losses
from storage.db import get_engine, init_db, session_factory
from storage.models import IngestionLog, LossEvent


def make_record(id_: int, status: str = "Destroyed", day: str = "2024-06-15") -> dict:
    return {
        "id": id_, "type": "Tanks", "model": "T-72B3", "status": status,
        "lost_by": "Russia", "date": day, "nearest_location": "Stepove, Pokrovsk raion",
        "geo": "48.20332,37.68901", "unit": None, "tags": None,
    }


@pytest.fixture()
def factory(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path}/test.db")
    init_db(engine)
    return session_factory(engine)


def test_upsert_idempotent(factory):
    records = [make_record(1001), make_record(1002), make_record(1003)]
    with factory() as session:
        new, updated = upsert_losses(session, records)
    assert (new, updated) == (3, 0)

    # 重复采集同一批数据：不产生脏数据
    with factory() as session:
        new2, updated2 = upsert_losses(session, [dict(r) for r in records])
        total = session.scalar(select(func.count(LossEvent.id)))
    assert (new2, updated2) == (0, 0)
    assert total == 3


def test_upsert_status_transition(factory):
    with factory() as session:
        upsert_losses(session, [make_record(2001, status="Abandoned")])
    # 同一记录状态流转 abandoned -> captured
    with factory() as session:
        new, updated = upsert_losses(session, [make_record(2001, status="Captured")])
        ev = session.get(LossEvent, 2001)
    assert (new, updated) == (0, 1)
    assert ev.status == "Captured"
    history = json.loads(ev.status_history)
    assert len(history) == 1
    assert history[0]["from"] == "Abandoned" and history[0]["to"] == "Captured"


def test_upsert_geo_parsing(factory):
    with factory() as session:
        upsert_losses(session, [make_record(3001)])
        ev = session.get(LossEvent, 3001)
    assert ev.latitude == pytest.approx(48.20332)
    assert ev.longitude == pytest.approx(37.68901)
    assert json.loads(ev.raw_json)["id"] == 3001  # 原始 JSON 整体存档


def test_raw_snapshot(tmp_path):
    path = save_raw_snapshot(tmp_path, date(2024, 6, 15), [make_record(1)])
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["date"] == "2024-06-15"
    assert len(payload["losses"]) == 1
    assert "fetched_at" in payload


def test_ingestion_log_schema(factory):
    with factory() as session:
        log = IngestionLog(date_from=date(2024, 6, 1), date_to=date(2024, 6, 15),
                           status="success", records_new=10)
        session.add(log)
        session.commit()
        assert log.id is not None
