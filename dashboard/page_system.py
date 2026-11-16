"""系统信息页：当前配置、数据口径声明、来源署名。"""
from __future__ import annotations

import streamlit as st

import common


def _db_kind(database_url: str) -> str:
    if database_url.startswith("sqlite"):
        return "SQLite（本地/演示）"
    if database_url.startswith("postgresql"):
        return "PostgreSQL + PostGIS（生产）"
    return database_url.split(":", 1)[0]


def render() -> None:
    st.header("系统信息")
    settings = common.get_app_settings()

    st.subheader("当前配置")
    rows = [
        ("数据库", f"{_db_kind(settings.database_url)}（{settings.database_url}）"),
        ("WarSpotting API", settings.warspotting_base_url),
        ("采集限速", f"{settings.request_interval_seconds} 秒/请求，最多重试 {settings.max_retries} 次"),
        ("LLM", (f"已配置（{settings.openai_model} @ {settings.openai_base_url}）"
                 if settings.llm_available else "未配置 —— 日报/问答走确定性 fallback 降级路径")),
        ("原始快照目录", settings.raw_dir),
        ("报告输出目录", settings.report_dir),
        ("定时采集", f"每天 {settings.scheduler_hour:02d}:{settings.scheduler_minute:02d}"
                     "（python -m ingestion.scheduler）"),
    ]
    st.table({"配置项": [r[0] for r in rows], "值": [r[1] for r in rows]})

    st.subheader("数字可信机制")
    st.markdown(
        "- 报告/回答中的**所有数字由代码计算产出**（`analytics` 纯代码统计层），LLM 只写文字解读；\n"
        "- 输出前由 `evals.number_check` 将文本中的每个数字与数据库统计结果对账，**对不上即拦截**；\n"
        "- 报告中的数据附 WarSpotting 记录 ID 来源；原始 API 响应按日存档于 `data/raw/`。"
    )

    st.subheader("口径与声明")
    st.warning(
        "**口径声明**：本数据为目视确认损失，实际损失高于统计数字。\n\n"
        "**数据来源**：WarSpotting（https://warspotting.net）。\n\n"
        "**开源数据、仅供参考。** 本项目仅供研究用途，分析结论不构成任何确定性军事情报判断。"
    )
