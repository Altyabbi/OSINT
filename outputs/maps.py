"""folium 地理分布热力图渲染（HTML）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import folium
from folium.plugins import HeatMap

# 乌克兰战区大致中心
DEFAULT_CENTER = (48.6, 36.5)


def render_heatmap(points: list[dict[str, float]], path: Path,
                   center: tuple[float, float] = DEFAULT_CENTER, zoom: int = 6) -> Path | None:
    """渲染热力图；无坐标点时返回 None。"""
    if not points:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    lat_mean = sum(p["lat"] for p in points) / len(points)
    lon_mean = sum(p["lon"] for p in points) / len(points)
    fmap = folium.Map(location=[lat_mean, lon_mean] if points else list(center), zoom_start=zoom)
    HeatMap([[p["lat"], p["lon"]] for p in points], radius=12, blur=15, max_zoom=8).add_to(fmap)
    fmap.save(str(path))
    return path
