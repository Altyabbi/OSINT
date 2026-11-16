"""问答 agent 的语义化工具集。不向 LLM 开放任意 SQL，只允许这些结构化工具函数。"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from analytics import stats
from storage.models import LossEvent

SOURCE = "WarSpotting（https://warspotting.net），目视确认损失口径，开源数据仅供参考"
MAX_RECORDS_RETURNED = 50


def _records_brief(session: Session, date_from: date | None, date_to: date | None,
                   type_: str | None, model: str | None, status: str | None,
                   region: str | None) -> list[dict[str, Any]]:
    ids = stats.record_ids(session, date_from, date_to, type_, model, status, region,
                           limit=MAX_RECORDS_RETURNED)
    if not ids:
        return []
    rows = session.execute(
        select(LossEvent).where(LossEvent.id.in_(ids)).order_by(LossEvent.date)
    ).scalars().all()
    return [
        {"id": ev.id, "date": ev.date.isoformat(), "type": ev.type, "model": ev.model,
         "status": ev.status, "nearest_location": ev.nearest_location}
        for ev in rows
    ]


def query_losses(session: Session, type: str | None = None, model: str | None = None,  # noqa: A002
                 status: str | None = None, date_from: str | None = None,
                 date_to: str | None = None, region: str | None = None,
                 lat: float | None = None, lon: float | None = None,
                 radius_km: float | None = None) -> dict[str, Any]:
    """按类别/型号/状态/时间段/地理区域（地名或半径）查询损失统计。"""
    df = date.fromisoformat(date_from) if date_from else None
    dt = date.fromisoformat(date_to) if date_to else None
    result: dict[str, Any] = {
        "filters": {"type": type, "model": model, "status": status,
                    "date_from": date_from, "date_to": date_to,
                    "region": region, "lat": lat, "lon": lon, "radius_km": radius_km},
        "source": SOURCE,
    }
    if lat is not None and lon is not None and radius_km is not None:
        events = stats.losses_in_radius(session, lat, lon, radius_km, df, dt)
        result["total"] = len(events)
        result["records"] = [
            {"id": ev.id, "date": ev.date.isoformat(), "type": ev.type, "model": ev.model,
             "status": ev.status, "nearest_location": ev.nearest_location}
            for ev in events[:MAX_RECORDS_RETURNED]
        ]
        return result
    result["total"] = stats.total_losses(session, df, dt, type, model, status, region)
    result["by_status"] = stats.count_by_field(session, "status", df, dt, type, model, status, region)
    result["by_type"] = stats.count_by_field(session, "type", df, dt, type, model, status, region)
    result["records"] = _records_brief(session, df, dt, type, model, status, region)
    return result


def compare_periods(session: Session, a_from: str, a_to: str, b_from: str, b_to: str,
                    type: str | None = None, model: str | None = None) -> dict[str, Any]:  # noqa: A002
    """对比两个时间段的损失总量与类别分布。"""
    af, at = date.fromisoformat(a_from), date.fromisoformat(a_to)
    bf, bt = date.fromisoformat(b_from), date.fromisoformat(b_to)
    total_a = stats.total_losses(session, af, at, type, model)
    total_b = stats.total_losses(session, bf, bt, type, model)
    change = None
    if total_b > 0:
        change = round((total_a - total_b) / total_b * 100, 1)
    return {
        "period_a": {"from": a_from, "to": a_to, "total": total_a,
                     "by_type": stats.count_by_field(session, "type", af, at, type, model)},
        "period_b": {"from": b_from, "to": b_to, "total": total_b,
                     "by_type": stats.count_by_field(session, "type", bf, bt, type, model)},
        "pct_change_a_vs_b": change,
        "record_ids_a": stats.record_ids(session, af, at, type, model),
        "record_ids_b": stats.record_ids(session, bf, bt, type, model),
        "source": SOURCE,
    }


def get_trend(session: Session, date_from: str, date_to: str, granularity: str = "day",
              type: str | None = None, model: str | None = None) -> dict[str, Any]:  # noqa: A002
    """时间趋势：按日/周/月聚合。"""
    df, dt = date.fromisoformat(date_from), date.fromisoformat(date_to)
    points = stats.trend(session, df, dt, granularity, type, model)
    return {
        "date_from": date_from, "date_to": date_to, "granularity": granularity,
        "type": type, "model": model,
        "points": points,
        "total": sum(p["count"] for p in points),
        "source": SOURCE,
    }


def get_unit_history(session: Session, unit: str) -> dict[str, Any]:
    """按部队/单位字段查询损失历史。"""
    total = stats.total_losses(session, unit=unit)
    rows = session.execute(
        select(LossEvent).where(LossEvent.unit.ilike(f"%{unit}%"))
        .order_by(LossEvent.date).limit(MAX_RECORDS_RETURNED)
    ).scalars().all()
    return {
        "unit": unit,
        "total": total,
        "by_status": stats.count_by_field(session, "status", unit=unit),
        "by_type": stats.count_by_field(session, "type", unit=unit),
        "records": [
            {"id": ev.id, "date": ev.date.isoformat(), "type": ev.type, "model": ev.model,
             "status": ev.status, "nearest_location": ev.nearest_location}
            for ev in rows
        ],
        "source": SOURCE,
    }
