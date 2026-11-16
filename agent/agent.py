"""数据问答 agent：LLM 工具调用模式；无 key 时降级为关键词路由（确定性）。

降级路径说明：未配置 OPENAI_API_KEY 时，用关键词/正则识别意图与参数
（时间段、类别、型号、单位），路由到同一组语义化工具函数，回答中的数字
同样经过 evals.number_check 对账。路由无法识别时给出明确报错提示。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Any, Callable

from sqlalchemy.orm import Session

from agent import tools
from analytics.stats import date_range_in_db
from config import Settings, get_settings
from evals.number_check import check_text_numbers, collect_numbers
from pipelines.llm_client import LLMClient

logger = logging.getLogger(__name__)

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_losses",
            "description": "按类别/型号/状态/时间段/地理区域查询战损统计（结构化数据）",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "装备类别（英文，如 Tanks）"},
                    "model": {"type": "string", "description": "型号关键词（如 T-90M），模糊匹配"},
                    "status": {"type": "string", "enum": ["Destroyed", "Damaged", "Abandoned", "Captured"]},
                    "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                    "region": {"type": "string", "description": "地名关键词（匹配 nearest_location）"},
                    "lat": {"type": "number"}, "lon": {"type": "number"},
                    "radius_km": {"type": "number"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_periods",
            "description": "对比两个时间段的损失总量与类别分布",
            "parameters": {
                "type": "object",
                "properties": {
                    "a_from": {"type": "string"}, "a_to": {"type": "string"},
                    "b_from": {"type": "string"}, "b_to": {"type": "string"},
                    "type": {"type": "string"}, "model": {"type": "string"},
                },
                "required": ["a_from", "a_to", "b_from", "b_to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trend",
            "description": "时间趋势：按日/周/月聚合的损失数量序列",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string"}, "date_to": {"type": "string"},
                    "granularity": {"type": "string", "enum": ["day", "week", "month"]},
                    "type": {"type": "string"}, "model": {"type": "string"},
                },
                "required": ["date_from", "date_to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_unit_history",
            "description": "按部队/单位名称查询损失历史",
            "parameters": {
                "type": "object",
                "properties": {"unit": {"type": "string"}},
                "required": ["unit"],
            },
        },
    },
]

AGENT_SYSTEM_PROMPT = (
    "你是军事开源情报分析系统的问答助手。回答用户关于俄军装备战损的问题时，"
    "必须先调用提供的工具函数获取结构化统计数据，回答中的数字只能来自工具返回结果，"
    "绝不允许自己估算。回答用中文，结尾注明数据来源（WarSpotting，目视确认损失口径，开源数据仅供参考），"
    "并引用关键记录 ID。"
)

# 中文类别关键词 → WarSpotting 英文类别（用于降级路由）
TYPE_KEYWORDS = {
    "坦克": "Tanks",
    "装甲车": "Armoured fighting vehicles",
    "步战车": "Infantry fighting vehicles",
    "火炮": "Artillery",
    "无人机": "Drones",
    "雷达": "Radars, jammers",
    "电子战": "Radars, jammers",
    "防空": "Anti-aircraft warfare",
    "飞机": "Aircraft",
    "直升机": "Helicopters",
    "车辆": "Vehicles",
    "工程": "Engineering vehicles",
}


class OsintAgent:
    def __init__(self, session: Session, settings: Settings | None = None,
                 llm: LLMClient | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.llm = llm or LLMClient(self.settings)
        self._dispatch: dict[str, Callable[..., dict[str, Any]]] = {
            "query_losses": lambda **kw: tools.query_losses(self.session, **kw),
            "compare_periods": lambda **kw: tools.compare_periods(self.session, **kw),
            "get_trend": lambda **kw: tools.get_trend(self.session, **kw),
            "get_unit_history": lambda **kw: tools.get_unit_history(self.session, **kw),
        }

    # ---------- LLM 工具调用路径 ----------

    def _ask_with_llm(self, question: str) -> dict[str, Any]:
        assert self.llm.available
        client = self.llm._client  # OpenAI 兼容 client，需 tools 参数
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        used_tools: list[str] = []
        tool_results: list[dict[str, Any]] = []
        for _ in range(6):  # 工具调用循环上限
            resp = client.chat.completions.create(
                model=self.settings.openai_model,
                temperature=self.settings.llm_temperature,
                messages=messages,
                tools=TOOL_SPECS,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                answer = msg.content or ""
                self._verify_answer(answer, tool_results)
                return {"answer": answer, "used_tools": used_tools, "fallback": False}
            messages.append(msg.model_dump(exclude_none=True))
            for call in msg.tool_calls:
                name = call.function.name
                args = json.loads(call.function.arguments or "{}")
                if name not in self._dispatch:
                    result = {"error": f"未知工具: {name}"}
                else:
                    try:
                        result = self._dispatch[name](**args)
                    except Exception as exc:
                        result = {"error": str(exc)}
                used_tools.append(name)
                tool_results.append(result)
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": json.dumps(result, ensure_ascii=False)})
        return {"answer": "工具调用次数超限，未能生成回答。", "used_tools": used_tools, "fallback": False}

    # ---------- 降级路径：关键词路由 ----------

    def _reference_date(self) -> date:
        """离线模式的'今天'：以库内最新数据日期为参照。"""
        _, max_date = date_range_in_db(self.session)
        return max_date or date.today()

    def _parse_time_range(self, question: str) -> tuple[str | None, str | None]:
        ref = self._reference_date()
        dates = re.findall(r"(\d{4})-(\d{1,2})-(\d{1,2})", question)
        if len(dates) >= 2:
            a = date(int(dates[0][0]), int(dates[0][1]), int(dates[0][2]))
            b = date(int(dates[1][0]), int(dates[1][1]), int(dates[1][2]))
            return a.isoformat(), b.isoformat()
        if len(dates) == 1:
            d = date(int(dates[0][0]), int(dates[0][1]), int(dates[0][2]))
            return d.isoformat(), d.isoformat()
        m = re.search(r"近\s*(\d+)\s*天", question)
        if m:
            n = int(m.group(1))
            return (ref - timedelta(days=n - 1)).isoformat(), ref.isoformat()
        if "近两周" in question or "最近两周" in question:
            return (ref - timedelta(days=13)).isoformat(), ref.isoformat()
        if "近一周" in question or "最近一周" in question or "上周" in question:
            return (ref - timedelta(days=6)).isoformat(), ref.isoformat()
        if "上个月" in question or "上月" in question:
            first = ref.replace(day=1)
            last_of_prev = first - timedelta(days=1)
            return last_of_prev.replace(day=1).isoformat(), last_of_prev.isoformat()
        if "当月" in question or "本月" in question or "这个月" in question:
            return ref.replace(day=1).isoformat(), ref.isoformat()
        return None, None  # 全库范围

    def _parse_type(self, question: str) -> str | None:
        for kw, en in TYPE_KEYWORDS.items():
            if kw in question:
                return en
        return None

    def _parse_model(self, question: str) -> str | None:
        m = re.search(r"\b([A-Za-z]+-\d+[A-Za-z0-9-]*|BMP-\d+|BTR-\w+)\b", question)
        return m.group(1) if m else None

    def _fallback_ask(self, question: str) -> dict[str, Any]:
        date_from, date_to = self._parse_time_range(question)
        type_ = self._parse_type(question)
        model = self._parse_model(question)

        if "部队" in question or "单位" in question:
            m = re.search(r"[\"'“]([^\"'”]+)[\"'”]", question)
            if not m:
                return {"answer": "降级模式：未能从问题中识别单位名称，请用引号标注单位名。",
                        "used_tools": [], "fallback": True}
            result = tools.get_unit_history(self.session, m.group(1))
            answer = self._render_unit_answer(result)
            return {"answer": answer, "used_tools": ["get_unit_history"], "fallback": True,
                    "tool_result": result}

        if "趋势" in question:
            if not date_from:
                ref = self._reference_date()
                date_from, date_to = (ref - timedelta(days=29)).isoformat(), ref.isoformat()
            granularity = "week" if ("周" in question and "两周" not in question) else "day"
            result = tools.get_trend(self.session, date_from, date_to, granularity, type_, model)
            answer = self._render_trend_answer(result)
            return {"answer": answer, "used_tools": ["get_trend"], "fallback": True,
                    "tool_result": result}

        result = tools.query_losses(self.session, type=type_, model=model,
                                    date_from=date_from, date_to=date_to)
        answer = self._render_query_answer(result, question)
        return {"answer": answer, "used_tools": ["query_losses"], "fallback": True,
                "tool_result": result}

    def _render_query_answer(self, r: dict[str, Any], question: str) -> str:
        f = r["filters"]
        scope = []
        if f["date_from"]:
            scope.append(f"{f['date_from']} 至 {f['date_to']}")
        else:
            scope.append("库内全部时间段")
        if f["type"]:
            scope.append(f"类别 {f['type']}")
        if f["model"]:
            scope.append(f"型号含 {f['model']}")
        ids = [rec["id"] for rec in r.get("records", [])]
        status_text = "、".join(f"{d['key']} {d['count']} 台" for d in r.get("by_status", []))
        text = (
            f"根据 WarSpotting 数据，{'，'.join(scope)}范围内俄军目视确认损失共 {r['total']} 台/套"
            + (f"（{status_text}）" if status_text else "")
            + f"。引用记录 ID：{('、'.join(str(i) for i in ids)) if ids else '无'}。"
            + "数据来源：WarSpotting，目视确认损失口径，开源数据仅供参考。"
        )
        self._verify_answer(text, [r])
        return text

    def _render_trend_answer(self, r: dict[str, Any]) -> str:
        points = r["points"]
        peak = max(points, key=lambda p: p["count"]) if points else None
        text = (
            f"{r['date_from']} 至 {r['date_to']} 期间（粒度：{r['granularity']}），"
            f"目视确认损失合计 {r['total']} 台/套"
            + (f"，峰值出现在 {peak['period']}（{peak['count']} 台）" if peak else "")
            + "。数据来源：WarSpotting，目视确认损失口径，开源数据仅供参考。"
        )
        self._verify_answer(text, [r])
        return text

    def _render_unit_answer(self, r: dict[str, Any]) -> str:
        ids = [rec["id"] for rec in r.get("records", [])]
        text = (
            f"单位 {r['unit']} 关联的目视确认损失记录共 {r['total']} 条"
            f"（记录 ID：{('、'.join(str(i) for i in ids)) if ids else '无'}）。"
            "数据来源：WarSpotting，目视确认损失口径，开源数据仅供参考。"
        )
        self._verify_answer(text, [r])
        return text

    # ---------- 公共 ----------

    def _verify_answer(self, answer: str, tool_results: list[dict[str, Any]]) -> None:
        allowed: set[str] = set()
        for r in tool_results:
            allowed |= collect_numbers(r)
        result = check_text_numbers(answer, allowed)
        if not result.ok:
            logger.error("回答数字校验失败：%s", result)
            raise RuntimeError(f"回答未通过数字一致性校验，已拦截：{result.violations}")
        logger.info("回答数字校验通过（%d 个数字）", result.checked)

    def ask(self, question: str) -> dict[str, Any]:
        """问答主入口。返回 {answer, used_tools, fallback, ...}。"""
        if self.llm.available:
            logger.info("使用 LLM 工具调用模式回答")
            return self._ask_with_llm(question)
        logger.info("未配置 LLM key，使用关键词路由降级模式回答")
        return self._fallback_ask(question)
