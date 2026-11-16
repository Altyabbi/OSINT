"""SQLAlchemy 表结构定义。

说明：需求要求 PostgreSQL + PostGIS 存地理坐标。为保证 SQLite/PostgreSQL 两库通用，
坐标使用 Float 的 latitude/longitude 列 + 索引，半径查询用 haversine 公式计算；
docker-compose 中仍提供 postgis/postgis 镜像，生产环境可直接切换 DATABASE_URL。
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class LossEvent(Base):
    """战损事件表。主键即 WarSpotting 原始记录 ID，幂等 upsert 的锚点。"""

    __tablename__ = "loss_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    date: Mapped[date] = mapped_column(Date, index=True)
    type: Mapped[str] = mapped_column(String(128), index=True)
    model: Mapped[str | None] = mapped_column(String(256), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    lost_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    nearest_location: Mapped[str | None] = mapped_column(String(256), index=True, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, index=True, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, index=True, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(256), index=True, nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 数组文本
    photos: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 数组文本
    raw_json: Mapped[str] = mapped_column(Text)  # 原始 JSON 整体存档
    status_history: Mapped[str] = mapped_column(Text, default="[]")  # 状态流转追踪 JSON
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_loss_events_date_type", "date", "type"),
        Index("ix_loss_events_date_status", "date", "status"),
    )


class IngestionLog(Base):
    """采集日志表：每次采集任务的时间范围、新增/更新记录数、状态。"""

    __tablename__ = "ingestion_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    records_fetched: Mapped[int] = mapped_column(Integer, default=0)
    records_new: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    days_ok: Mapped[int] = mapped_column(Integer, default=0)
    days_failed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running/success/partial/failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
