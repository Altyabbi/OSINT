"""日报中心页：触发生成日报（完整流水线 + 数字校验），浏览历史报告。"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import common
from pipelines.llm_client import LLMClient
from pipelines.report import generate_daily_report

REPORT_GLOB = "daily_report_*.md"
REPORT_PREFIX = "daily_report_"


def list_history_reports(report_dir: Path) -> list[str]:
    """列出 outputs/reports/ 下已有报告的日期（倒序）。"""
    if not report_dir.exists():
        return []
    dates = []
    for p in report_dir.glob(REPORT_GLOB):
        day_s = p.stem.replace(REPORT_PREFIX, "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_s):
            dates.append(day_s)
    return sorted(dates, reverse=True)


def strip_image_lines(markdown: str) -> str:
    """去掉 Markdown 中的图片行（PNG 由 st.image 单独渲染，避免相对路径破图）。"""
    return "\n".join(
        line for line in markdown.splitlines() if not line.strip().startswith("![")
    )


def run_report(day: date) -> Path:
    """页面生成日报的后端调用（与 CLI 共用 pipelines.report 完整流水线）。"""
    settings = common.get_app_settings()
    with common.new_session() as s:
        return generate_daily_report(s, day, settings=settings, llm=LLMClient(settings))


def show_report(report_dir: Path, day_s: str) -> None:
    """渲染一份报告：Markdown 正文 + 图表 PNG + folium 热力图。"""
    md_path = report_dir / f"{REPORT_PREFIX}{day_s}.md"
    if not md_path.exists():
        st.warning(f"报告文件不存在：{md_path}")
        return
    st.markdown(strip_image_lines(md_path.read_text(encoding="utf-8")))

    pngs = sorted(report_dir.glob(f"daily_{day_s}_*.png"))
    if pngs:
        cols = st.columns(len(pngs))
        for col, png in zip(cols, pngs):
            col.image(str(png), caption=png.name)
    heat = report_dir / f"daily_{day_s}_heatmap.html"
    if heat.exists():
        components.html(heat.read_text(encoding="utf-8"), height=520, scrolling=True)


def render() -> None:
    st.header("日报中心")
    settings = common.get_app_settings()
    report_dir = settings.report_path
    st.caption(
        "日报走完整流水线（统计 → 图表 → LLM/fallback 撰写 → 数字校验），"
        "报告中所有数字由代码计算并与数据库对账，对不上即拦截。"
        + ("当前未配置 LLM key，解读文字使用确定性 fallback 模板。"
           if not settings.llm_available else "当前使用 LLM 撰写解读。")
    )

    c1, c2 = st.columns([1, 2])
    day = c1.date_input("报告日期", value=date(2024, 6, 15))
    if c2.button("生成日报", type="primary"):
        with st.spinner(f"正在生成 {day} 日报（含图表渲染与数字校验）……"):
            try:
                path = run_report(day)
            except Exception as exc:
                st.error(f"日报生成被拦截/失败：{exc}")
                return
        common.refresh_caches()
        st.success(f"日报已生成并通过数字校验：{path}")

    history = list_history_reports(report_dir)
    if not history:
        st.info("尚无历史报告。")
        return
    default_idx = history.index(day.isoformat()) if day.isoformat() in history else 0
    day_s = st.selectbox("浏览报告（含历史）", history, index=default_idx)
    st.divider()
    show_report(report_dir, day_s)
