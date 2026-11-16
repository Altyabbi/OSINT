"""日报 workflow：节点化流水线。

节点顺序固定：collect（拉取+统计）→ render_charts → render_map → write（LLM/fallback）
→ assemble（组装 Markdown）→ verify（数字对账，不过则拦截）。
硬性要求：报告中所有数字由代码计算产出，撰写层只写文字解读。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from analytics import stats
from config import Settings, get_settings
from evals.number_check import NumberCheckResult, assert_numbers, collect_numbers
from outputs import charts, maps
from pipelines.llm_client import LLMClient
from pipelines.writer import write_interpretation

logger = logging.getLogger(__name__)

DISCLAIMER_SCOPE = "本数据为目视确认损失，实际损失高于统计数字"
DISCLAIMER_OSI = "开源数据、仅供参考"
SOURCE_CREDIT = "WarSpotting（https://warspotting.net）"
MAX_IDS_IN_TEXT = 100  # 正文中内联引用的记录 ID 上限


@dataclass
class ReportContext:
    """报告统计上下文：报告中出现的所有数字都来自这里（数字校验的 allowed 集合）。"""

    date: date
    snapshot_at: datetime
    window_short: int = 7
    window_long: int = 30
    total: int = 0
    by_type: list[dict[str, Any]] = field(default_factory=list)
    by_status: list[dict[str, Any]] = field(default_factory=list)
    top_models: list[dict[str, Any]] = field(default_factory=list)
    top_locations: list[dict[str, Any]] = field(default_factory=list)
    geo_point_count: int = 0
    record_ids: list[int] = field(default_factory=list)
    trend_long: list[dict[str, Any]] = field(default_factory=list)
    baseline: dict[str, Any] = field(default_factory=dict)

    def to_stats_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "snapshot_at": self.snapshot_at.isoformat(),
            "total": self.total,
            "by_type": self.by_type,
            "by_status": self.by_status,
            "top_models": self.top_models,
            "top_locations": self.top_locations,
            "geo_point_count": self.geo_point_count,
            "record_ids": self.record_ids,
            "baseline": self.baseline,
        }


# ---------- 节点 1：拉取当日数据 + 代码统计 ----------

def node_collect(session: Session, day: date, window_long: int = 30) -> ReportContext:
    summary = stats.period_summary(session, day, day)
    trend = stats.daily_counts(session, day - timedelta(days=window_long - 1), day)
    baseline = stats.baseline_compare(session, day)
    ctx = ReportContext(
        date=day,
        snapshot_at=datetime.now(timezone.utc),
        total=summary["total"],
        by_type=summary["by_type"],
        by_status=summary["by_status"],
        top_models=summary["top_models"],
        top_locations=summary["top_locations"],
        geo_point_count=summary["geo_point_count"],
        record_ids=summary["record_ids"],
        trend_long=trend,
        baseline=baseline,
    )
    logger.info("节点 collect 完成：%s 当日 %d 条，坐标点 %d 个", day, ctx.total, ctx.geo_point_count)
    return ctx


# ---------- 节点 2/3：图表与热力图 ----------

def node_render_charts(ctx: ReportContext, out_dir: Path) -> dict[str, Path]:
    day_s = ctx.date.isoformat()
    paths = {
        "by_type": charts.chart_by_category(ctx.by_type, out_dir / f"daily_{day_s}_by_type.png",
                                            title=f"Losses by category ({day_s})"),
        "by_status": charts.chart_by_status(ctx.by_status, out_dir / f"daily_{day_s}_by_status.png",
                                            title=f"Losses by status ({day_s})"),
        "trend": charts.chart_trend(ctx.trend_long, out_dir / f"daily_{day_s}_trend{ctx.window_long}d.png",
                                    title=f"Daily losses, last {ctx.window_long} days ({day_s})"),
    }
    logger.info("节点 render_charts 完成：%s", {k: str(v) for k, v in paths.items()})
    return paths


def node_render_map(session: Session, ctx: ReportContext, out_dir: Path) -> Path | None:
    day_s = ctx.date.isoformat()
    points = stats.geo_points(session, ctx.date - timedelta(days=ctx.window_long - 1), ctx.date)
    path = maps.render_heatmap(points, out_dir / f"daily_{day_s}_heatmap.html")
    logger.info("节点 render_map 完成：%s（近 %d 天 %d 个坐标点）", path, ctx.window_long, len(points))
    return path


# ---------- 节点 4：LLM/fallback 撰写 ----------

def node_write(ctx: ReportContext, llm: LLMClient) -> tuple[str, str]:
    text, mode = write_interpretation(ctx, llm)
    logger.info("节点 write 完成：撰写方式=%s", mode)
    return text, mode


# ---------- 节点 5：组装 Markdown ----------

def _md_table(rows: list[dict[str, Any]], header: tuple[str, str]) -> str:
    lines = [f"| {header[0]} | {header[1]} |", "| --- | ---: |"]
    lines += [f"| {r['key']} | {r['count']} |" for r in rows]
    return "\n".join(lines) if rows else "（无数据）"


def node_assemble(ctx: ReportContext, interpretation: str, write_mode: str,
                  chart_paths: dict[str, Path], map_path: Path | None, out_dir: Path) -> str:
    day_s = ctx.date.isoformat()
    b = ctx.baseline
    ids = ctx.record_ids[:MAX_IDS_IN_TEXT]
    ids_text = "、".join(str(i) for i in ids) if ids else "无"

    lines: list[str] = []
    lines.append(f"# 俄军装备战损日报（{day_s}）")
    lines.append("")
    lines.append(f"> **口径声明**：{DISCLAIMER_SCOPE}。")
    lines.append(f"> **数据来源**：{SOURCE_CREDIT}，{DISCLAIMER_OSI}。")
    lines.append(f"> **数据快照时间**：{ctx.snapshot_at.strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append("")
    lines.append("## 一、当日新增战损统计")
    lines.append("")
    lines.append(f"当日新增目视确认损失共 **{ctx.total}** 台/套（记录 ID：{ids_text}）。")
    lines.append("")
    lines.append("### 按装备类别")
    lines.append(_md_table(ctx.by_type, ("类别", "数量")))
    lines.append("")
    lines.append("### 按损失状态")
    lines.append(_md_table(ctx.by_status, ("状态", "数量")))
    lines.append("")
    lines.append(f"## 二、与近 {ctx.window_short} 日 / 近 {ctx.window_long} 日均值对比")
    lines.append("")
    lines.append(f"- 当日总量：{b['day_total']} 台；近 {ctx.window_short} 日均值：{b['avg7']:.1f} 台；"
                 f"近 {ctx.window_long} 日均值：{b['avg30']:.1f} 台。")
    if b["pct_change_7d"] is not None:
        lines.append(f"- 较近 {ctx.window_short} 日均值变化：{b['pct_change_7d']:+.1f}%；"
                     f"较近 {ctx.window_long} 日均值变化：{b['pct_change_30d']:+.1f}%。")
    else:
        lines.append(f"- 近 {ctx.window_short} 日与近 {ctx.window_long} 日均值均为 0，无法计算变化率。")
    if b["anomalies"]:
        lines.append("- 异常点：")
        for a in b["anomalies"]:
            lines.append(f"  - 总量较{a['window']}均值（{a['window_mean']:.1f} 台）"
                         f"{a['direction']} {a['pct_change']:+.1f}%")
    else:
        lines.append("- 异常点：当日总量处于基线正常波动区间内。")
    if b["category_anomalies"]:
        lines.append("- 类别异常：")
        for ca in b["category_anomalies"]:
            lines.append(f"  - {ca['type']}：当日 {ca['day_count']} 台，近 {ctx.window_long} 日均值 "
                         f"{ca['window_mean']:.1f} 台（{ca['pct_change']:+.1f}%）")
    lines.append("")
    lines.append("## 三、地理分布")
    lines.append("")
    if map_path is not None:
        lines.append(f"当日有坐标记录 {ctx.geo_point_count} 条；近 {ctx.window_long} 日损失分布热力图："
                     f"[{map_path.name}]({map_path.name})")
    else:
        lines.append(f"当日有坐标记录 {ctx.geo_point_count} 条，数据不足，未生成热力图。")
    lines.append("")
    lines.append("热点地点（按记录数）：")
    lines.append(_md_table(ctx.top_locations[:5], ("地点", "记录数")))
    lines.append("")
    lines.append("## 四、重点型号动态")
    lines.append("")
    lines.append(_md_table(ctx.top_models[:5], ("型号", "数量")))
    lines.append("")
    lines.append(f"## 五、解读（撰写方式：{write_mode}）")
    lines.append("")
    lines.append(interpretation)
    lines.append("")
    lines.append("## 附图")
    lines.append("")
    for key in ("by_type", "by_status", "trend"):
        p = chart_paths[key]
        lines.append(f"![{key}]({p.name})")
        lines.append("")
    return "\n".join(lines)


# ---------- 节点 6：数字对账 + 落盘 ----------

def node_verify(markdown: str, ctx: ReportContext) -> NumberCheckResult:
    allowed = collect_numbers(ctx)
    result = assert_numbers(markdown, allowed)
    logger.info("节点 verify 完成：%s", result)
    return result


def generate_daily_report(session: Session, day: date, settings: Settings | None = None,
                          llm: LLMClient | None = None, report_dir: Path | None = None) -> Path:
    """日报 workflow 主入口：依次执行各节点，数字校验不过则拦截（抛 NumberMismatchError）。"""
    settings = settings or get_settings()
    llm = llm or LLMClient(settings)
    out_dir = report_dir or settings.report_path
    out_dir.mkdir(parents=True, exist_ok=True)

    ctx = node_collect(session, day)
    chart_paths = node_render_charts(ctx, out_dir)
    map_path = node_render_map(session, ctx, out_dir)
    interpretation, write_mode = node_write(ctx, llm)
    markdown = node_assemble(ctx, interpretation, write_mode, chart_paths, map_path, out_dir)
    node_verify(markdown, ctx)

    report_path = out_dir / f"daily_report_{day.isoformat()}.md"
    report_path.write_text(markdown, encoding="utf-8")
    logger.info("日报已生成：%s", report_path)
    return report_path
