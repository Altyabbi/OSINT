"""数字一致性校验：把报告/回答文本中出现的数字与代码计算结果对账。

规则：文本中所有数字（整数与小数）必须出现在 allowed 集合中（字符串精确匹配），
否则视为疑似 LLM 幻觉数字，拦截并告警。allowed 集合由 collect_numbers() 从
结构化统计数据自动收集，保证"报告中所有数字由代码计算产出"这一硬性要求可执行。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class NumberCheckResult:
    ok: bool
    checked: int = 0
    violations: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.ok:
            return f"数字校验通过（共核对 {self.checked} 个数字）"
        return f"数字校验失败：{len(self.violations)} 个数字无法对账 -> {self.violations}"


class NumberMismatchError(RuntimeError):
    def __init__(self, result: NumberCheckResult) -> None:
        super().__init__(str(result))
        self.result = result


def extract_numbers(text: str) -> list[str]:
    """抽取文本中的全部数字 token（含小数）。"""
    return NUMBER_RE.findall(text)


def fmt_number(value: int | float) -> set[str]:
    """一个数值在文本中可能出现的格式化形式（与报告写法的约定一致）。

    整数 -> "42"；浮点 -> 保留 1 位小数 "3.5"，若为整数值同时允许 "3"。
    """
    if isinstance(value, bool):
        return set()
    if isinstance(value, int):
        return {str(value), str(abs(value))}
    # 负数在文本中以 "-12.5" 出现，但数字抽取不含负号，故同时放行绝对值形式
    forms = {f"{value:.1f}", f"{abs(value):.1f}"}
    if float(value).is_integer():
        forms.add(str(int(value)))
        forms.add(str(abs(int(value))))
    return forms


def collect_numbers(obj: Any) -> set[str]:
    """递归遍历结构化数据（dataclass/dict/list/tuple/date/datetime），收集全部数字。"""
    allowed: set[str] = set()
    if obj is None or isinstance(obj, bool):
        return allowed
    if isinstance(obj, str):
        # 字符串来自结构化数据（日期、周期标签等），其中的数字 token 予以放行
        return set(NUMBER_RE.findall(obj))
    if isinstance(obj, (int, float)):
        return fmt_number(obj)
    if isinstance(obj, (date, datetime)):
        allowed |= {str(obj.year), f"{obj.month:02d}", str(obj.month), f"{obj.day:02d}", str(obj.day)}
        if isinstance(obj, datetime):
            allowed |= {f"{obj.hour:02d}", str(obj.hour), f"{obj.minute:02d}", str(obj.minute),
                        f"{obj.second:02d}", str(obj.second)}
        return allowed
    if isinstance(obj, dict):
        for v in obj.values():
            allowed |= collect_numbers(v)
        return allowed
    if isinstance(obj, (list, tuple, set)):
        for v in obj:
            allowed |= collect_numbers(v)
        return allowed
    if hasattr(obj, "__dataclass_fields__"):
        for name in obj.__dataclass_fields__:
            allowed |= collect_numbers(getattr(obj, name))
        return allowed
    return allowed


def check_text_numbers(text: str, allowed: set[str]) -> NumberCheckResult:
    """对账：文本中每个数字都必须能在 allowed 中找到。"""
    tokens = extract_numbers(text)
    violations = sorted({t for t in tokens if t not in allowed})
    return NumberCheckResult(ok=not violations, checked=len(tokens), violations=violations)


def assert_numbers(text: str, allowed: set[str]) -> NumberCheckResult:
    """校验失败则抛 NumberMismatchError（拦截输出）。"""
    result = check_text_numbers(text, allowed)
    if not result.ok:
        raise NumberMismatchError(result)
    return result
