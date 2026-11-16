#!/usr/bin/env python
"""军事开源情报分析系统 CLI 入口。

用法示例：
  python run.py ingest --from 2026-09-22 --to 2026-10-05   # 区间采集
  python run.py ingest --backfill                          # 全量回溯（2022-02-24 起，耗时长）
  python run.py report --date 2026-10-05                   # 手动触发日报
  python run.py ask "2024-06-15 俄军损失了多少辆坦克？"     # 数据问答
  python run.py dashboard                                  # 启动 Streamlit 看板
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from config import get_settings  # noqa: E402
from storage.db import get_engine, init_db, session_factory  # noqa: E402


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def cmd_ingest(args: argparse.Namespace) -> int:
    from ingestion.client import WarSpottingClient
    from ingestion.pipeline import BACKFILL_START, ingest_range

    settings = get_settings()
    engine = get_engine(settings.database_url)
    init_db(engine)
    factory = session_factory(engine)
    client = WarSpottingClient(settings)

    if args.backfill:
        date_from = BACKFILL_START
        date_to = date.today() - timedelta(days=1)
    elif args.backfill_recent:
        date_to = date.today() - timedelta(days=1)
        date_from = date_to - timedelta(days=args.backfill_recent - 1)
    else:
        if not args.date_from or not args.date_to:
            print("错误：ingest 需要 --from/--to，或 --backfill，或 --backfill-recent N", file=sys.stderr)
            return 2
        date_from, date_to = _parse_date(args.date_from), _parse_date(args.date_to)

    log = ingest_range(factory, client, date_from, date_to, settings)
    print(f"采集完成：{date_from} ~ {date_to}，状态={log.status}，"
          f"拉取={log.records_fetched}，新增={log.records_new}，"
          f"更新={log.records_updated}，失败天数={log.days_failed}")
    return 0 if log.status in ("success", "partial") else 1


def cmd_report(args: argparse.Namespace) -> int:
    from pipelines.report import generate_daily_report

    settings = get_settings()
    engine = get_engine(settings.database_url)
    init_db(engine)
    factory = session_factory(engine)
    day = _parse_date(args.date) if args.date else date.today() - timedelta(days=1)
    with factory() as session:
        path = generate_daily_report(session, day, settings)
    print(f"日报已生成：{path}")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from agent.agent import OsintAgent

    settings = get_settings()
    engine = get_engine(settings.database_url)
    init_db(engine)
    factory = session_factory(engine)
    with factory() as session:
        agent = OsintAgent(session, settings)
        result = agent.ask(args.question)
    print(result["answer"])
    print(f"\n[调用工具: {result['used_tools'] or '无'} | 降级模式: {result['fallback']}]")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    app = BASE_DIR / "dashboard" / "app.py"
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)])


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(prog="military-osint", description="军事开源情报分析系统（一期）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="采集 WarSpotting 战损数据")
    p_ingest.add_argument("--from", dest="date_from", help="开始日期 YYYY-MM-DD")
    p_ingest.add_argument("--to", dest="date_to", help="结束日期 YYYY-MM-DD")
    p_ingest.add_argument("--backfill", action="store_true", help="全量回溯（2022-02-24 起）")
    p_ingest.add_argument("--backfill-recent", type=int, metavar="N", help="补采最近 N 天")
    p_ingest.set_defaults(func=cmd_ingest)

    p_report = sub.add_parser("report", help="生成日报（默认昨日）")
    p_report.add_argument("--date", help="日期 YYYY-MM-DD")
    p_report.set_defaults(func=cmd_report)

    p_ask = sub.add_parser("ask", help="自然语言数据问答")
    p_ask.add_argument("question", help="问题，如：上个月俄军损失了多少辆 T-90M？")
    p_ask.set_defaults(func=cmd_ask)

    p_dash = sub.add_parser("dashboard", help="启动 Streamlit 看板")
    p_dash.set_defaults(func=cmd_dashboard)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
