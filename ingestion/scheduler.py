"""定时采集：APScheduler 每日增量更新（默认采集前一日，并补采最近 3 天以防迟到数据）。

用法：python -m ingestion.scheduler
也可改用系统 cron，例如（每天 06:40）：
  40 6 * * * cd /path/to/military-osint && conda run -n nli python run.py ingest --backfill-recent 3
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config import get_settings
from ingestion.client import WarSpottingClient
from ingestion.pipeline import ingest_range
from storage.db import get_engine, init_db, session_factory

logger = logging.getLogger(__name__)


def daily_job() -> None:
    """每日任务：采集最近 3 天（含迟到数据的状态流转更新）。"""
    settings = get_settings()
    engine = get_engine(settings.database_url)
    init_db(engine)
    factory = session_factory(engine)
    client = WarSpottingClient(settings)
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=2)
    ingest_range(factory, client, start, end, settings)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    scheduler = BlockingScheduler()
    trigger = CronTrigger(hour=settings.scheduler_hour, minute=settings.scheduler_minute)
    scheduler.add_job(daily_job, trigger, id="daily_ingest", name="WarSpotting 每日增量采集")
    logger.info("调度器启动：每天 %02d:%02d 执行增量采集", settings.scheduler_hour, settings.scheduler_minute)
    scheduler.start()


if __name__ == "__main__":
    main()
