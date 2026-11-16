"""evals 数字一致性校验单元测试。"""
from datetime import date, datetime, timezone

import pytest

from evals.number_check import (
    NumberMismatchError,
    assert_numbers,
    check_text_numbers,
    collect_numbers,
    extract_numbers,
)


def test_extract_numbers():
    assert extract_numbers("当日 15 台，均值 12.3 台，变化 +22.0%") == ["15", "12.3", "22.0"]


def test_check_pass():
    allowed = {"15", "12.3", "22.0", "2024"}
    result = check_text_numbers("2024-06-15 共 15 台，均值 12.3，+22.0%", allowed)
    # 06、15 不在 allowed 中 → 违规
    assert not result.ok
    allowed |= {"06"}
    result2 = check_text_numbers("共 15 台，均值 12.3，+22.0%", allowed)
    assert result2.ok and result2.checked == 3


def test_check_blocks_hallucinated_number():
    allowed = {"15"}
    result = check_text_numbers("共 15 台，其中 3 辆坦克", allowed)
    assert not result.ok
    assert result.violations == ["3"]


def test_collect_numbers_nested():
    data = {
        "total": 15,
        "avg": 12.34,
        "pct": -25.5,
        "ids": [27530, 27531],
        "date_str": "2024-06-15",
        "day": date(2024, 6, 15),
        "ts": datetime(2026, 10, 6, 8, 30, tzinfo=timezone.utc),
        "nested": [{"count": 3}],
    }
    allowed = collect_numbers(data)
    assert "15" in allowed and "12.3" in allowed
    assert "25.5" in allowed  # 负数放行绝对值形式
    assert "27530" in allowed and "27531" in allowed
    assert "2024" in allowed and "06" in allowed  # 字符串与 date 对象均可
    assert "8" in allowed and "30" in allowed  # datetime 时分
    assert "3" in allowed


def test_assert_raises():
    with pytest.raises(NumberMismatchError):
        assert_numbers("损失 999 台", {"10"})
