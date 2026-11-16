"""dashboard 页面纯函数与后端调用单元测试（不打外网）。"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))

from page_reports import list_history_reports, strip_image_lines  # noqa: E402

from analytics import stats  # noqa: E402
from ingestion.pipeline import upsert_losses  # noqa: E402
from storage.db import get_engine, init_db, session_factory  # noqa: E402


def test_list_history_reports(tmp_path):
    (tmp_path / "daily_report_2024-06-15.md").write_text("# x", encoding="utf-8")
    (tmp_path / "daily_report_2026-10-04.md").write_text("# x", encoding="utf-8")
    (tmp_path / "daily_report_bad.md").write_text("# x", encoding="utf-8")  # 非日期名应被忽略
    (tmp_path / "daily_2024-06-15_by_type.png").write_bytes(b"")
    assert list_history_reports(tmp_path) == ["2026-10-04", "2024-06-15"]
    assert list_history_reports(tmp_path / "nonexistent") == []


def test_strip_image_lines():
    md = "# 标题\n\n![by_type](a.png)\n\n正文 [link](b.html)\n\n![trend](c.png)\n"
    stripped = strip_image_lines(md)
    assert "![" not in stripped
    assert "# 标题" in stripped and "[link](b.html)" in stripped


def test_fetch_records_filters():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    factory = session_factory(engine)
    with factory() as s:
        day0 = date(2024, 6, 10)
        records = [
            {"id": i, "type": "Tanks" if i % 2 else "Drones", "model": "T-90M",
             "status": "Destroyed", "lost_by": "Russia",
             "date": (day0 + timedelta(days=i)).isoformat(),
             "nearest_location": "Avdiivka", "geo": "48.15,37.75", "unit": None, "tags": None}
            for i in range(1, 8)
        ]
        upsert_losses(s, records)
        all_recs = stats.fetch_records(s, day0, day0 + timedelta(days=7))
        assert len(all_recs) == 7
        assert all_recs[0].date >= all_recs[-1].date  # 日期倒序
        tanks = stats.fetch_records(s, type_="Tanks")
        assert len(tanks) == 4 and all(r.type == "Tanks" for r in tanks)
        limited = stats.fetch_records(s, limit=2)
        assert len(limited) == 2
        region = stats.fetch_records(s, region="avdii")
        assert len(region) == 7
