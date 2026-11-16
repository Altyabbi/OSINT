"""Web 界面各页面后端调用验证脚本（真实环境实跑，确认不抛异常）。

覆盖：数据查询、小范围真实采集（2026-10-08 ~ 2026-10-09）、日报生成、智能问答。
用法：conda run -n nli python scripts/verify_web_backend.py
"""
from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))

import common  # noqa: E402
import page_chat  # noqa: E402
import page_ingest  # noqa: E402
import page_reports  # noqa: E402
from analytics import stats  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")

    # 1. 数据查询页后端：多维筛选 + 明细
    with common.new_session() as s:
        total = stats.total_losses(s, date(2024, 6, 15), date(2024, 6, 15))
        records = stats.fetch_records(s, date(2024, 6, 15), date(2024, 6, 15), type_="Tanks")
        by_type = stats.count_by_field(s, "type", date(2024, 6, 15), date(2024, 6, 15))
    print(f"[查询] 2024-06-15 当日总记录 {total}，Tanks 明细 {len(records)} 条，类别数 {len(by_type)}")

    # 2. 数据采集页后端：小范围真实采集（约 2 秒/天）
    log = page_ingest.run_ingestion(date(2026, 10, 8), date(2026, 10, 9))
    print(f"[采集] {log.date_from} ~ {log.date_to}：status={log.status}，"
          f"拉取={log.records_fetched}，新增={log.records_new}，更新={log.records_updated}")

    # 3. 日报中心页后端：完整流水线 + 数字校验
    report_path = page_reports.run_report(date(2026, 10, 8))
    history = page_reports.list_history_reports(common.get_app_settings().report_path)
    print(f"[日报] 已生成：{report_path.name}；历史报告共 {len(history)} 份：{history}")

    # 4. 智能问答页后端：agent 降级路由
    result = page_chat.run_agent("2024-06-15 俄军损失了多少辆坦克？")
    print(f"[问答] used_tools={result['used_tools']}，fallback={result['fallback']}")
    print(f"[问答] {result['answer'][:120]}...")

    print("ALL BACKEND CALLS OK")


if __name__ == "__main__":
    main()
