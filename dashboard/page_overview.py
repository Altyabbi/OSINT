"""概览页：核心指标卡、近期趋势图、地理分布热力图。"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import func, select

import common
from analytics import stats
from outputs.maps import DEFAULT_CENTER
from storage.models import IngestionLog, LossEvent

import folium
from folium.plugins import HeatMap


def render() -> None:
    st.header("系统概览")
    with common.new_session() as s:
        total = stats.total_losses(s)
        lo, hi = stats.date_range_in_db(s)
        geo_cnt = int(s.scalar(
            select(func.count(LossEvent.id)).where(LossEvent.latitude.is_not(None))
        ) or 0)
        last_ingest = s.scalar(select(func.max(IngestionLog.finished_at)))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("战损记录总数", total)
    c2.metric("数据日期范围", f"{lo} ~ {hi}" if lo else "无数据")
    c3.metric("有坐标记录", geo_cnt)
    c4.metric("最近采集时间", last_ingest.strftime("%Y-%m-%d %H:%M UTC") if last_ingest else "从未采集")

    if lo is None or hi is None:
        st.warning("数据库为空。请到「数据采集」页采集，或运行 "
                   "`python run.py ingest --from 2024-06-15 --to 2024-06-15`。")
        return

    st.subheader("近 30 天损失趋势")
    trend_from = max(lo, hi - timedelta(days=29))
    with common.new_session() as s:
        trend_data = stats.daily_counts(s, trend_from, hi)
    df = pd.DataFrame(trend_data)
    st.line_chart(df.set_index("date"))

    st.subheader("近 90 天地理分布热力图")
    heat_from = max(lo, hi - timedelta(days=89))
    with common.new_session() as s:
        points = stats.geo_points(s, heat_from, hi)
    if points:
        lat_mean = sum(p["lat"] for p in points) / len(points)
        lon_mean = sum(p["lon"] for p in points) / len(points)
        fmap = folium.Map(location=[lat_mean, lon_mean], zoom_start=6)
        HeatMap([[p["lat"], p["lon"]] for p in points], radius=12, blur=15).add_to(fmap)
        components.html(fmap._repr_html_(), height=520)
        st.caption(f"共 {len(points)} 个坐标点（{heat_from} ~ {hi}）")
    else:
        st.info("该时段无带坐标的记录。")
