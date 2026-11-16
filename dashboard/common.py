"""Streamlit 看板公共层：路径引导、缓存的数据库资源、公共渲染工具。

所有页面模块都先 import common（完成 sys.path 引导与缓存资源注册）。
缓存策略：engine/session factory 走 st.cache_resource（进程级单例）；
类型/状态/日期范围等慢变选项走 st.cache_data（短 TTL）；
采集或生成报告后调用 refresh_caches() 让数据立刻刷新。
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st
from sqlalchemy.orm import Session, sessionmaker

DASHBOARD_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DASHBOARD_DIR.parent
for _p in (str(PROJECT_ROOT), str(DASHBOARD_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import Settings, get_settings  # noqa: E402
from storage.db import get_engine, init_db, session_factory  # noqa: E402


def get_app_settings() -> Settings:
    return get_settings()


@st.cache_resource
def get_factory() -> sessionmaker[Session]:
    """进程级共享的 session 工厂（engine 单例）。"""
    settings = get_settings()
    engine = get_engine(settings.database_url)
    init_db(engine)
    return session_factory(engine)


def new_session() -> Session:
    return get_factory()()


def refresh_caches() -> None:
    """采集/报告生成后清除数据缓存，让页面读到最新数据。"""
    st.cache_data.clear()


@st.cache_data(ttl=30)
def cached_date_range() -> tuple[str | None, str | None]:
    from analytics.stats import date_range_in_db

    with new_session() as s:
        lo, hi = date_range_in_db(s)
    return (lo.isoformat() if lo else None, hi.isoformat() if hi else None)


@st.cache_data(ttl=30)
def cached_options(field: str) -> list[str]:
    """类别/状态等字段的取值列表（field ∈ {type, status}）。"""
    from analytics.stats import count_by_field

    with new_session() as s:
        return [d["key"] for d in count_by_field(s, field)]


DISCLAIMER = (
    "数据来源：WarSpotting（https://warspotting.net）｜"
    "口径：目视确认损失，实际损失高于统计数字｜开源数据、仅供参考"
)
