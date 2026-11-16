"""统计分析模块：纯代码计算，不经过 LLM。所有函数返回结构化数据（dict/list）。

支持：按时间段/类别/型号/状态聚合、日/周/月趋势、地理分布（热力图数据）、
地名或半径（haversine）区域过滤、基线对比异常检测。
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from storage.models import LossEvent

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点间球面距离（公里）。SQLite/PostgreSQL 通用的区域半径过滤基础。"""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _apply_filters(
    stmt: Select[Any],
    date_from: date | None = None,
    date_to: date | None = None,
    type_: str | None = None,
    model: str | None = None,
    status: str | None = None,
    region: str | None = None,
    unit: str | None = None,
) -> Select[Any]:
    if date_from is not None:
        stmt = stmt.where(LossEvent.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(LossEvent.date <= date_to)
    if type_:
        stmt = stmt.where(func.lower(LossEvent.type) == type_.lower())
    if model:
        stmt = stmt.where(LossEvent.model.ilike(f"%{model}%"))
    if status:
        stmt = stmt.where(func.lower(LossEvent.status) == status.lower())
    if region:
        stmt = stmt.where(LossEvent.nearest_location.ilike(f"%{region}%"))
    if unit:
        stmt = stmt.where(LossEvent.unit.ilike(f"%{unit}%"))
    return stmt


def total_losses(session: Session, date_from: date | None = None, date_to: date | None = None,
                 type_: str | None = None, model: str | None = None, status: str | None = None,
                 region: str | None = None, unit: str | None = None) -> int:
    stmt = _apply_filters(select(func.count(LossEvent.id)), date_from, date_to, type_, model,
                          status, region, unit)
    return int(session.scalar(stmt) or 0)


def count_by_field(session: Session, field: str, date_from: date | None = None, date_to: date | None = None,
                   type_: str | None = None, model: str | None = None, status: str | None = None,
                   region: str | None = None, unit: str | None = None,
                   limit: int | None = None) -> list[dict[str, Any]]:
    """按字段分组计数。field ∈ {type, model, status, nearest_location, unit}。"""
    columns = {
        "type": LossEvent.type,
        "model": LossEvent.model,
        "status": LossEvent.status,
        "nearest_location": LossEvent.nearest_location,
        "unit": LossEvent.unit,
    }
    if field not in columns:
        raise ValueError(f"不支持的分组字段: {field}")
    col = columns[field]
    stmt = select(col, func.count(LossEvent.id)).group_by(col).order_by(func.count(LossEvent.id).desc())
    stmt = _apply_filters(stmt, date_from, date_to, type_, model, status, region, unit)
    if limit:
        stmt = stmt.limit(limit)
    rows = session.execute(stmt).all()
    return [{"key": k if k is not None else "(未知)", "count": int(c)} for k, c in rows]


def daily_counts(session: Session, date_from: date, date_to: date,
                 type_: str | None = None, model: str | None = None) -> list[dict[str, Any]]:
    """逐日计数，无数据的日期补 0。"""
    stmt = (
        select(LossEvent.date, func.count(LossEvent.id))
        .group_by(LossEvent.date)
        .order_by(LossEvent.date)
    )
    stmt = _apply_filters(stmt, date_from, date_to, type_, model)
    rows = {d: int(c) for d, c in session.execute(stmt).all()}
    result = []
    day = date_from
    while day <= date_to:
        result.append({"date": day.isoformat(), "count": rows.get(day, 0)})
        day += timedelta(days=1)
    return result


def trend(session: Session, date_from: date, date_to: date, granularity: str = "day",
          type_: str | None = None, model: str | None = None) -> list[dict[str, Any]]:
    """时间趋势：按日/周（ISO 周）/月聚合。"""
    if granularity not in ("day", "week", "month"):
        raise ValueError(f"不支持的粒度: {granularity}")
    daily = daily_counts(session, date_from, date_to, type_, model)
    if granularity == "day":
        return [{"period": d["date"], "count": d["count"]} for d in daily]
    buckets: dict[str, int] = {}
    for item in daily:
        d = date.fromisoformat(item["date"])
        if granularity == "week":
            iso = d.isocalendar()
            label = f"{iso.year}-W{iso.week:02d}"
        else:
            label = f"{d.year}-{d.month:02d}"
        buckets[label] = buckets.get(label, 0) + item["count"]
    return [{"period": k, "count": v} for k, v in sorted(buckets.items())]


def fetch_records(session: Session, date_from: date | None = None, date_to: date | None = None,
                  type_: str | None = None, model: str | None = None, status: str | None = None,
                  region: str | None = None, limit: int = 1000) -> list[LossEvent]:
    """多维筛选查询战损记录明细（供 Web 数据查询页/导出使用，按日期倒序）。"""
    stmt = select(LossEvent).order_by(LossEvent.date.desc(), LossEvent.id)
    stmt = _apply_filters(stmt, date_from, date_to, type_, model, status, region).limit(limit)
    return list(session.execute(stmt).scalars().all())


def geo_points(session: Session, date_from: date | None = None, date_to: date | None = None,
               type_: str | None = None, model: str | None = None) -> list[dict[str, float]]:
    """热力图点位数据：有坐标的记录。"""
    stmt = select(LossEvent.latitude, LossEvent.longitude).where(
        LossEvent.latitude.is_not(None), LossEvent.longitude.is_not(None)
    )
    stmt = _apply_filters(stmt, date_from, date_to, type_, model)
    return [{"lat": float(lat), "lon": float(lon)} for lat, lon in session.execute(stmt).all()]


def losses_in_radius(session: Session, lat: float, lon: float, radius_km: float,
                     date_from: date | None = None, date_to: date | None = None) -> list[LossEvent]:
    """半径查询：先用索引粗筛经纬度窗口，再用 haversine 精算。"""
    delta_lat = radius_km / 111.32
    delta_lon = radius_km / (111.32 * max(math.cos(math.radians(lat)), 0.01))
    stmt = select(LossEvent).where(
        LossEvent.latitude.between(lat - delta_lat, lat + delta_lat),
        LossEvent.longitude.between(lon - delta_lon, lon + delta_lon),
    )
    stmt = _apply_filters(stmt, date_from, date_to)
    candidates = session.execute(stmt).scalars().all()
    return [
        ev for ev in candidates
        if ev.latitude is not None and ev.longitude is not None
        and haversine_km(lat, lon, ev.latitude, ev.longitude) <= radius_km
    ]


def record_ids(session: Session, date_from: date | None = None, date_to: date | None = None,
               type_: str | None = None, model: str | None = None, status: str | None = None,
               region: str | None = None, limit: int = 500) -> list[int]:
    stmt = select(LossEvent.id).order_by(LossEvent.id)
    stmt = _apply_filters(stmt, date_from, date_to, type_, model, status, region).limit(limit)
    return [int(i) for (i,) in session.execute(stmt).all()]


def baseline_compare(session: Session, day: date) -> dict[str, Any]:
    """当日总数与近 7 日/30 日均值对比，识别异常点（按类别也计算）。"""
    day_total = total_losses(session, day, day)

    def window_stats(days: int) -> dict[str, float]:
        start = day - timedelta(days=days)
        end = day - timedelta(days=1)
        counts = [d["count"] for d in daily_counts(session, start, end)]
        mean = sum(counts) / len(counts) if counts else 0.0
        var = sum((c - mean) ** 2 for c in counts) / len(counts) if counts else 0.0
        return {"mean": mean, "std": math.sqrt(var)}

    w7 = window_stats(7)
    w30 = window_stats(30)

    def pct_change(mean: float) -> float | None:
        if mean <= 0:
            return None
        return round((day_total - mean) / mean * 100, 1)

    anomalies: list[dict[str, Any]] = []
    for label, stats in (("近7日", w7), ("近30日", w30)):
        mean, std = stats["mean"], stats["std"]
        if mean > 0 and (day_total >= mean + 2 * std or day_total >= mean * 1.5):
            anomalies.append({"window": label, "direction": "偏高", "day_total": day_total,
                              "window_mean": round(mean, 1), "pct_change": pct_change(mean)})
        elif mean > 0 and day_total <= max(mean - 2 * std, mean * 0.5):
            anomalies.append({"window": label, "direction": "偏低", "day_total": day_total,
                              "window_mean": round(mean, 1), "pct_change": pct_change(mean)})

    # 类别级异常：当日某类别 ≥ 其近30日均值的 2 倍且均值 ≥ 1
    cat_anomalies: list[dict[str, Any]] = []
    start30, end30 = day - timedelta(days=30), day - timedelta(days=1)
    for item in count_by_field(session, "type", day, day):
        cat = item["key"]
        cat_counts = [d["count"] for d in daily_counts(session, start30, end30, type_=cat)]
        mean = sum(cat_counts) / len(cat_counts) if cat_counts else 0.0
        if mean >= 1 and item["count"] >= mean * 2:
            cat_anomalies.append({"type": cat, "day_count": item["count"],
                                  "window_mean": round(mean, 1),
                                  "pct_change": round((item["count"] - mean) / mean * 100, 1)})

    return {
        "date": day.isoformat(),
        "day_total": day_total,
        "avg7": round(w7["mean"], 1),
        "std7": round(w7["std"], 1),
        "avg30": round(w30["mean"], 1),
        "std30": round(w30["std"], 1),
        "pct_change_7d": pct_change(w7["mean"]),
        "pct_change_30d": pct_change(w30["mean"]),
        "anomalies": anomalies,
        "category_anomalies": cat_anomalies,
    }


def period_summary(session: Session, date_from: date, date_to: date) -> dict[str, Any]:
    """时间段综合统计，供报告与问答复用。"""
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "total": total_losses(session, date_from, date_to),
        "by_type": count_by_field(session, "type", date_from, date_to),
        "by_status": count_by_field(session, "status", date_from, date_to),
        "top_models": count_by_field(session, "model", date_from, date_to, limit=10),
        "top_locations": count_by_field(session, "nearest_location", date_from, date_to, limit=10),
        "geo_point_count": len(geo_points(session, date_from, date_to)),
        "record_ids": record_ids(session, date_from, date_to),
    }


def date_range_in_db(session: Session) -> tuple[date | None, date | None]:
    """库中数据的最早/最晚日期（离线问答的默认参照）。"""
    row = session.execute(select(func.min(LossEvent.date), func.max(LossEvent.date))).one()
    return row[0], row[1]
