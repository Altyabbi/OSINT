"""报告文字撰写：LLM 写作 + 确定性 fallback writer。

硬性约束：所有数字由代码计算（见 analytics 与 ReportContext），撰写层只产出
文字解读。LLM 产出的文字会经过 evals.number_check 对账，出现任何不在统计
结果中的数字即拦截并自动降级到 fallback。
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from evals.number_check import check_text_numbers, collect_numbers

if TYPE_CHECKING:
    from pipelines.llm_client import LLMClient
    from pipelines.report import ReportContext

logger = logging.getLogger(__name__)

LLM_SYSTEM_PROMPT = (
    "你是军事开源情报分析系统的报告撰写员。你会收到一份 JSON 格式的统计数据（所有数字已由代码计算完成）。"
    "你的任务只是写中文文字解读。严格规则：\n"
    "1. 只允许使用 JSON 中出现过的数字，绝不允许计算、估算或引入任何新数字；\n"
    "2. 不做政治立场判断，保持客观中立；\n"
    "3. 不得给出确定性军事情报结论，结尾注明数据为目视确认损失口径；\n"
    "4. 输出 3-5 句连贯的段落，不要列表、不要标题。"
)


def _fmt_pct(pct: float | None) -> str:
    if pct is None:
        return "（基线均值为 0，无法计算变化率）"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def fallback_interpretation(ctx: "ReportContext") -> str:
    """确定性模板化解读：每个数字都来自 ReportContext，可 100% 通过数字校验。"""
    b = ctx.baseline
    parts: list[str] = []
    parts.append(
        f"{ctx.date.isoformat()} 当日 WarSpotting 新增目视确认俄军装备损失 {ctx.total} 台/套，"
        f"近 7 日均值为 {b['avg7']:.1f} 台，近 30 日均值为 {b['avg30']:.1f} 台，"
        f"相对变化分别为 {_fmt_pct(b['pct_change_7d'])} 与 {_fmt_pct(b['pct_change_30d'])}。"
    )
    if ctx.by_type:
        top = ctx.by_type[0]
        parts.append(f"当日损失最多的装备类别为 {top['key']}（{top['count']} 台）。")
    status_text = "、".join(f"{d['key']} {d['count']} 台" for d in ctx.by_status)
    if status_text:
        parts.append(f"损失状态分布：{status_text}。")
    if b["anomalies"]:
        a = b["anomalies"][0]
        parts.append(
            f"当日总量较{a['window']}均值（{a['window_mean']:.1f} 台）{a['direction']}"
            f"{_fmt_pct(a['pct_change'])}，属异常波动，可能与当日交战强度变化有关。"
        )
    else:
        parts.append("当日总量处于近 7 日与近 30 日均值的正常波动区间内，未见显著异常。")
    if b["category_anomalies"]:
        ca = b["category_anomalies"][0]
        parts.append(
            f"类别层面，{ca['type']} 当日 {ca['day_count']} 台，高于其近 30 日均值 "
            f"{ca['window_mean']:.1f} 台，值得持续跟踪。"
        )
    if ctx.top_locations and ctx.top_locations[0]["key"] != "(未知)":
        loc = ctx.top_locations[0]
        parts.append(f"地理分布上，{loc['key']} 方向报告损失最为集中（{loc['count']} 条记录）。")
    if ctx.top_models:
        m = ctx.top_models[0]
        parts.append(f"重点型号方面，{m['key']} 当日出现 {m['count']} 次，为当日最频繁型号。")
    parts.append("以上数字均为目视确认损失口径，实际损失高于统计数字，结论仅供参考。")
    return "".join(parts)


def write_interpretation(ctx: "ReportContext", llm: "LLMClient") -> tuple[str, str]:
    """返回 (解读文字, 撰写方式)。LLM 产出未通过数字校验时自动降级 fallback。"""
    allowed = collect_numbers(ctx)
    if not llm.available:
        logger.info("LLM 不可用，日报解读使用 fallback 模板撰写")
        return fallback_interpretation(ctx), "fallback"
    stats_json = json.dumps(ctx.to_stats_dict(), ensure_ascii=False, indent=1)
    user = f"请基于以下统计数据撰写当日战损日报的解读段落：\n{stats_json}"
    try:
        text = llm.chat(LLM_SYSTEM_PROMPT, user).strip()
    except Exception as exc:
        logger.warning("LLM 调用失败（%s），降级 fallback", exc)
        return fallback_interpretation(ctx), "fallback"
    result = check_text_numbers(text, allowed)
    if not result.ok:
        logger.warning("LLM 文字未通过数字校验（%s），拦截并降级 fallback", result.violations)
        return fallback_interpretation(ctx), "fallback"
    return text, "llm"
