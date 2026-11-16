"""采集流水线：按日循环 → 拉取 → raw 快照存档 → 幂等 upsert → 采集日志。"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from config import Settings, get_settings
from ingestion.client import WarSpottingClient
from ingestion.parse import RawLoss, parse_loss
from storage.models import IngestionLog, LossEvent, utcnow

logger = logging.getLogger(__name__)

BACKFILL_START = date(2022, 2, 24)  # 俄乌冲突爆发日，全量回溯起点


def save_raw_snapshot(raw_dir: Path, day: date, losses: list[dict]) -> Path:
    """原始 JSON 快照存档到磁盘。"""
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{day.isoformat()}.json"
    payload = {"fetched_at": datetime.now(timezone.utc).isoformat(), "date": day.isoformat(), "losses": losses}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _loss_to_row(loss: RawLoss, lat: float | None, lon: float | None, raw: dict) -> dict:
    return {
        "id": loss.id,
        "date": loss.date,
        "type": loss.type,
        "model": loss.model,
        "status": loss.status,
        "lost_by": loss.lost_by,
        "nearest_location": loss.nearest_location,
        "latitude": lat,
        "longitude": lon,
        "unit": loss.unit,
        "tags": loss.tags,
        "comment": loss.comment,
        "sources": json.dumps(loss.sources, ensure_ascii=False) if loss.sources else None,
        "photos": json.dumps(loss.photos, ensure_ascii=False) if loss.photos else None,
        "raw_json": json.dumps(raw, ensure_ascii=False),
    }


_TRACKED_FIELDS = (
    "date", "type", "model", "status", "lost_by", "nearest_location",
    "latitude", "longitude", "unit", "tags", "comment", "sources", "photos", "raw_json",
)


def upsert_losses(session: Session, raw_records: list[dict]) -> tuple[int, int]:
    """幂等 upsert：以 WarSpotting id 为主键。返回 (新增数, 更新数)。

    重复采集同一批数据时两者均为 0；若已有记录字段发生变化（如状态
    abandoned → captured），则更新字段并在 status_history 中追加流转记录。
    """
    new_count = 0
    updated_count = 0
    for raw in raw_records:
        loss, lat, lon = parse_loss(raw)
        row = _loss_to_row(loss, lat, lon, raw)
        existing = session.get(LossEvent, row["id"])
        if existing is None:
            session.add(LossEvent(**row, status_history="[]", first_seen_at=utcnow(), last_seen_at=utcnow()))
            new_count += 1
            continue
        changed = False
        old_status = existing.status
        for field in _TRACKED_FIELDS:
            if getattr(existing, field) != row[field]:
                setattr(existing, field, row[field])
                changed = True
        if changed:
            if old_status != row["status"]:
                history = json.loads(existing.status_history or "[]")
                history.append({
                    "from": old_status,
                    "to": row["status"],
                    "at": utcnow().isoformat(),
                })
                existing.status_history = json.dumps(history, ensure_ascii=False)
                logger.info("记录 %d 状态流转: %s → %s", existing.id, old_status, row["status"])
            existing.last_seen_at = utcnow()
            updated_count += 1
    session.commit()
    return new_count, updated_count


def ingest_range(
    session_factory: sessionmaker[Session],
    client: WarSpottingClient,
    date_from: date,
    date_to: date,
    settings: Settings | None = None,
) -> IngestionLog:
    """采集 [date_from, date_to] 闭区间内的每日数据，写采集日志。"""
    settings = settings or get_settings()
    days = (date_to - date_from).days + 1
    if days <= 0:
        raise ValueError(f"日期区间非法: {date_from} ~ {date_to}")
    logger.info("开始采集 %s ~ %s（共 %d 天）", date_from, date_to, days)

    with session_factory() as session:
        log = IngestionLog(date_from=date_from, date_to=date_to, status="running")
        session.add(log)
        session.commit()
        log_id = log.id

    errors: list[str] = []
    fetched = new_total = updated_total = days_ok = days_failed = 0
    day = date_from
    while day <= date_to:
        try:
            losses = client.fetch_day(day)
            save_raw_snapshot(settings.raw_path, day, losses)
            with session_factory() as session:
                new, updated = upsert_losses(session, losses)
            fetched += len(losses)
            new_total += new
            updated_total += updated
            days_ok += 1
            logger.info("%s：拉取 %d 条，新增 %d，更新 %d", day, len(losses), new, updated)
        except Exception as exc:  # 单日失败不中断整体任务
            days_failed += 1
            errors.append(f"{day.isoformat()}: {exc}")
            logger.error("采集 %s 失败: %s", day, exc)
        day += timedelta(days=1)

    with session_factory() as session:
        log = session.get(IngestionLog, log_id)
        assert log is not None
        log.finished_at = utcnow()
        log.records_fetched = fetched
        log.records_new = new_total
        log.records_updated = updated_total
        log.days_ok = days_ok
        log.days_failed = days_failed
        log.status = "success" if days_failed == 0 else ("partial" if days_ok > 0 else "failed")
        log.error = "\n".join(errors) if errors else None
        session.commit()
        session.refresh(log)
        result = log

    logger.info(
        "采集完成 %s ~ %s：状态=%s，拉取=%d，新增=%d，更新=%d，失败天数=%d",
        date_from, date_to, result.status, fetched, new_total, updated_total, days_failed,
    )
    return result
