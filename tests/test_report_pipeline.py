"""日报流水线端到端测试（fallback 撰写 + 数字校验 + 文件产出）。"""
from datetime import date, timedelta

import pytest

from agent.agent import OsintAgent
from ingestion.pipeline import upsert_losses
from pipelines.llm_client import LLMClient
from pipelines.report import DISCLAIMER_SCOPE, generate_daily_report
from storage.db import get_engine, init_db, session_factory


def rec(id_: int, day: date, type_: str = "Tanks", model: str = "T-90M",
        status: str = "Destroyed", geo: str | None = "48.15,37.75") -> dict:
    return {"id": id_, "type": type_, "model": model, "status": status,
            "lost_by": "Russia", "date": day.isoformat(),
            "nearest_location": "Avdiivka, Pokrovsk raion", "geo": geo,
            "unit": None, "tags": None}


@pytest.fixture()
def session():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    factory = session_factory(engine)
    s = factory()
    day0 = date(2024, 6, 1)
    records, rid = [], 1
    for i in range(40):  # 40 天基线，每天 1-2 条
        for _ in range(1 + i % 2):
            records.append(rec(rid, day0 + timedelta(days=i)))
            rid += 1
    target = day0 + timedelta(days=40)  # 2024-07-11
    for _ in range(5):  # 报告日 5 条
        records.append(rec(rid, target))
        rid += 1
    upsert_losses(s, records)
    yield s, target
    s.close()


class _NoLLM(LLMClient):
    def __init__(self) -> None:
        self._client = None


def test_generate_daily_report_fallback(session, tmp_path):
    s, target = session
    report_path = generate_daily_report(s, target, llm=_NoLLM(), report_dir=tmp_path)
    md = report_path.read_text(encoding="utf-8")

    assert DISCLAIMER_SCOPE in md
    assert "WarSpotting" in md
    assert "开源数据、仅供参考" in md
    assert "数据快照时间" in md
    assert "撰写方式：fallback" in md
    assert "**5** 台/套" in md  # 当日 5 条
    assert "T-90M" in md

    # 图表与热力图已产出
    day_s = target.isoformat()
    assert (tmp_path / f"daily_{day_s}_by_type.png").exists()
    assert (tmp_path / f"daily_{day_s}_by_status.png").exists()
    assert (tmp_path / f"daily_{day_s}_trend30d.png").exists()
    assert (tmp_path / f"daily_{day_s}_heatmap.html").exists()


def test_report_empty_day(session, tmp_path):
    s, target = session
    empty_day = target + timedelta(days=5)
    report_path = generate_daily_report(s, empty_day, llm=_NoLLM(), report_dir=tmp_path)
    md = report_path.read_text(encoding="utf-8")
    assert "**0** 台/套" in md  # 空日也能出报告且数字校验通过


def test_agent_fallback_query(session):
    s, target = session
    agent = OsintAgent(s, llm=_NoLLM())
    result = agent.ask(f"{target.isoformat()} 俄军损失了多少辆 T-90M？")
    assert result["fallback"] is True
    assert result["used_tools"] == ["query_losses"]
    assert "5 台/套" in result["answer"]
    assert "WarSpotting" in result["answer"]


def test_agent_fallback_trend(session):
    s, target = session
    agent = OsintAgent(s, llm=_NoLLM())
    result = agent.ask("近7天装甲损失趋势？")
    assert result["used_tools"] == ["get_trend"]
    assert "峰值" in result["answer"]


def test_agent_fallback_unit_history(session):
    s, target = session
    agent = OsintAgent(s, llm=_NoLLM())
    result = agent.ask('单位"第114旅"的损失历史？')
    assert result["used_tools"] == ["get_unit_history"]
    assert "0 条" in result["answer"]


def test_agent_fallback_unit_without_name(session):
    s, target = session
    agent = OsintAgent(s, llm=_NoLLM())
    result = agent.ask("某部队的损失历史？")
    assert "降级模式" in result["answer"]  # 无法识别单位名时给出明确提示
