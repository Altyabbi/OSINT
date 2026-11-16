"""WarSpotting 记录解析：字段校验、经纬度解析。

API 实测返回字段：id, type, model, status, lost_by, date, nearest_location,
geo（"lat,lon" 或 null）, unit, tags。sources/photos/comment 当前 API 未返回，
模型中允许为空，原始 JSON 会整体存档到 raw_json 列。
"""
from __future__ import annotations

import logging
from datetime import date

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class RawLoss(BaseModel):
    """WarSpotting 单条战损记录（容忍未知扩展字段）。"""

    model_config = ConfigDict(extra="allow")

    id: int
    type: str
    model: str | None = None
    status: str
    lost_by: str | None = None
    date: date
    nearest_location: str | None = None
    geo: str | None = None
    unit: str | None = None
    tags: str | None = None
    comment: str | None = None
    sources: list[str] | None = None
    photos: list[str] | None = None


def parse_geo(geo: str | None) -> tuple[float | None, float | None]:
    """解析 "lat,lon" 字符串；非法输入返回 (None, None)。"""
    if not geo:
        return None, None
    try:
        lat_s, lon_s = geo.split(",", 1)
        lat, lon = float(lat_s.strip()), float(lon_s.strip())
    except (ValueError, AttributeError):
        logger.warning("无法解析 geo 字段: %r", geo)
        return None, None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        logger.warning("geo 坐标越界: %r", geo)
        return None, None
    return lat, lon


def parse_loss(raw: dict) -> tuple[RawLoss, float | None, float | None]:
    """解析一条原始记录，返回 (校验后的记录, 纬度, 经度)。"""
    loss = RawLoss.model_validate(raw)
    lat, lon = parse_geo(loss.geo)
    return loss, lat, lon
