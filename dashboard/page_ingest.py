"""数据采集页：页面内触发区间/近 N 天采集，展示结果与采集日志表。

采集为耗时操作（限速下单天约 2 秒），用 st.spinner 同步执行小范围采集；
全量回溯（1600+ 天）请使用命令行，见页面底部说明。
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import select

import common
from ingestion.client import WarSpottingClient
from ingestion.pipeline import ingest_range
from storage.models import IngestionLog

MAX_DAYS_PER_RUN = 30  # 页面采集的单次天数上限，避免长时间阻塞界面


def run_ingestion(date_from: date, date_to: date) -> IngestionLog:
    """页面采集的后端调用（与 CLI 共用 ingestion.pipeline）。"""
    settings = common.get_app_settings()
    client = WarSpottingClient(settings)
    return ingest_range(common.get_factory(), client, date_from, date_to, settings)


def _recent_logs(limit: int = 20) -> pd.DataFrame:
    with common.new_session() as s:
        rows = s.execute(
            select(IngestionLog).order_by(IngestionLog.id.desc()).limit(limit)
        ).scalars().all()
    return pd.DataFrame([
        {
            "id": log.id,
            "started_at": log.started_at.strftime("%Y-%m-%d %H:%M") if log.started_at else None,
            "date_from": log.date_from.isoformat(),
            "date_to": log.date_to.isoformat(),
            "fetched": log.records_fetched,
            "new": log.records_new,
            "updated": log.records_updated,
            "days_ok": log.days_ok,
            "days_failed": log.days_failed,
            "status": log.status,
        }
        for log in rows
    ])


def render() -> None:
    st.header("数据采集")
    yesterday = date.today() - timedelta(days=1)

    mode = st.radio("采集方式", ["日期区间", "近 N 天"], horizontal=True)
    if mode == "日期区间":
        c1, c2 = st.columns(2)
        date_from = c1.date_input("开始日期", value=yesterday - timedelta(days=2), max_value=yesterday)
        date_to = c2.date_input("结束日期", value=yesterday, max_value=yesterday)
    else:
        n = int(st.number_input("采集最近 N 天（截至昨日）", min_value=1, max_value=MAX_DAYS_PER_RUN, value=3))
        date_to = yesterday
        date_from = yesterday - timedelta(days=n - 1)

    days = (date_to - date_from).days + 1
    if days <= 0:
        st.error("开始日期不能晚于结束日期。")
        return
    if days > MAX_DAYS_PER_RUN:
        st.warning(f"页面采集单次最多 {MAX_DAYS_PER_RUN} 天（当前 {days} 天），"
                   "更大范围请使用命令行（见页面底部）。")
        return
    st.caption(f"将采集 {date_from} ~ {date_to}（{days} 天），按限速预估约 {days * 2} 秒。"
               "重复采集是幂等的，不会产生重复数据。")

    if st.button("开始采集", type="primary"):
        with st.spinner(f"正在采集 {date_from} ~ {date_to}，请稍候……"):
            try:
                log = run_ingestion(date_from, date_to)
            except Exception as exc:  # 网络异常等
                st.error(f"采集失败：{exc}")
                return
        common.refresh_caches()
        if log.status == "success":
            st.success("采集完成。")
        elif log.status == "partial":
            st.warning("采集部分完成（有单日失败，明细见采集日志）。")
        else:
            st.error("采集失败。")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("拉取记录", log.records_fetched)
        m2.metric("新增", log.records_new)
        m3.metric("更新", log.records_updated)
        m4.metric("失败天数", log.days_failed)
        if log.error:
            with st.expander("失败明细"):
                st.text(log.error)

    st.subheader("采集日志（最近 20 条）")
    st.dataframe(_recent_logs(), use_container_width=True)

    st.info(
        "全量回溯（2022-02-24 起，1600+ 天，预估 2.5~4 小时）请使用命令行：\n\n"
        "```bash\npython run.py ingest --backfill\n```\n\n"
        "日常增量可用 `python -m ingestion.scheduler`（APScheduler）或系统 cron，详见 README。"
    )
