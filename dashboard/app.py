"""军事开源情报（OSINT）分析系统 — Streamlit Web 入口。

启动方式：
    conda run -n nli streamlit run dashboard/app.py
    或：conda run -n nli python run.py dashboard
"""
from __future__ import annotations

import streamlit as st

import common
import page_chat
import page_ingest
import page_overview
import page_query
import page_reports
import page_system

st.set_page_config(
    page_title="军事开源情报分析系统",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

PAGES = {
    "概览 Dashboard": page_overview.render,
    "数据查询": page_query.render,
    "数据采集": page_ingest.render,
    "日报中心": page_reports.render,
    "智能问答": page_chat.render,
    "系统信息": page_system.render,
}


def main() -> None:
    st.sidebar.title("军事 OSINT 分析系统")
    choice = st.sidebar.radio("功能导航", list(PAGES.keys()))
    st.sidebar.divider()
    st.sidebar.caption(common.DISCLAIMER)
    PAGES[choice]()


main()
