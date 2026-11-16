"""数据查询页：多维筛选 + 明细表格 + CSV 导出 + 聚合图表。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import streamlit as st

import common
from analytics import stats

DISPLAY_LIMIT = 1000
STATUS_OPTIONS = ["(全部)", "Destroyed", "Damaged", "Abandoned", "Captured"]


def _records_to_df(records: list[Any]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "id": ev.id,
            "date": ev.date.isoformat(),
            "type": ev.type,
            "model": ev.model,
            "status": ev.status,
            "lost_by": ev.lost_by,
            "nearest_location": ev.nearest_location,
            "latitude": ev.latitude,
            "longitude": ev.longitude,
            "unit": ev.unit,
            "tags": ev.tags,
        }
        for ev in records
    ])


def render() -> None:
    st.header("数据查询")
    lo_s, hi_s = common.cached_date_range()
    if lo_s is None or hi_s is None:
        st.warning("数据库为空，请先在「数据采集」页采集数据。")
        return
    lo, hi = date.fromisoformat(lo_s), date.fromisoformat(hi_s)

    with st.expander("筛选条件", expanded=True):
        r1c1, r1c2, r1c3, r1c4 = st.columns(4)
        date_from = r1c1.date_input("开始日期", value=max(lo, hi - timedelta(days=29)),
                                    min_value=lo, max_value=hi)
        date_to = r1c2.date_input("结束日期", value=hi, min_value=lo, max_value=hi)
        type_options = ["(全部)"] + common.cached_options("type")
        type_sel = r1c3.selectbox("装备类别", type_options)
        status_sel = r1c4.selectbox("损失状态", STATUS_OPTIONS)
        r2c1, r2c2 = st.columns(2)
        model_kw = r2c1.text_input("型号关键词（模糊匹配，如 T-90M）", value="")
        region_kw = r2c2.text_input("地名关键词（匹配最近地点）", value="")

    type_ = None if type_sel == "(全部)" else type_sel
    status = None if status_sel == "(全部)" else status_sel
    model = model_kw.strip() or None
    region = region_kw.strip() or None

    if date_from > date_to:
        st.error("开始日期不能晚于结束日期。")
        return

    with common.new_session() as s:
        total = stats.total_losses(s, date_from, date_to, type_, model, status, region)
        records = stats.fetch_records(s, date_from, date_to, type_, model, status, region,
                                      limit=DISPLAY_LIMIT)
        by_type = stats.count_by_field(s, "type", date_from, date_to, model=model,
                                       status=status, region=region)
        by_status = stats.count_by_field(s, "status", date_from, date_to, type_,
                                         model=model, region=region)
        top_models = stats.count_by_field(s, "model", date_from, date_to, type_,
                                          status=status, region=region, limit=10)

    st.caption(f"命中 {total} 条记录"
               + (f"，表格显示前 {DISPLAY_LIMIT} 条（CSV 导出同表格范围）" if total > DISPLAY_LIMIT else ""))

    df = _records_to_df(records)
    st.dataframe(df, use_container_width=True, height=420)
    st.download_button(
        "导出 CSV",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"losses_{date_from}_{date_to}.csv",
        mime="text/csv",
        disabled=df.empty,
    )

    st.subheader("统计聚合")
    left, right = st.columns(2)
    with left:
        st.markdown("**按类别**")
        if by_type:
            st.bar_chart(pd.DataFrame(by_type).set_index("key"))
    with right:
        st.markdown("**按状态**")
        if by_status:
            st.bar_chart(pd.DataFrame(by_status).set_index("key"))
    st.markdown("**型号 TOP 10**")
    if top_models:
        st.dataframe(pd.DataFrame(top_models), use_container_width=True)
