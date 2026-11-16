"""WarSpotting API 客户端：限速 + 指数退避重试。"""
from __future__ import annotations

import logging
import random
import time
from datetime import date

import requests

from config import Settings, get_settings

logger = logging.getLogger(__name__)

USER_AGENT = "military-osint-research/0.1 (+research use; polite crawl)"


class WarSpottingAPIError(RuntimeError):
    """多次重试后仍失败的 API 错误。"""


class WarSpottingClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        interval = self.settings.request_interval_seconds
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < interval:
            time.sleep(interval - elapsed)

    def fetch_day(self, day: date) -> list[dict]:
        """按日拉取俄军战损记录，返回原始记录列表。失败重试 max_retries 次后抛错。"""
        url = f"{self.settings.warspotting_base_url}/{day.isoformat()}/"
        last_err: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.get(url, timeout=self.settings.request_timeout_seconds)
                self._last_request_at = time.monotonic()
                if resp.status_code >= 500 or resp.status_code == 429:
                    raise WarSpottingAPIError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                payload = resp.json()
                losses = payload.get("losses", [])
                logger.info("采集 %s：%d 条记录", day.isoformat(), len(losses))
                return losses
            except (requests.RequestException, ValueError, WarSpottingAPIError) as exc:
                last_err = exc
                wait = self.settings.backoff_base_seconds * (2 ** (attempt - 1)) + random.uniform(0, 1)
                logger.warning(
                    "采集 %s 第 %d/%d 次失败：%s，%.1fs 后重试",
                    day.isoformat(), attempt, self.settings.max_retries, exc, wait,
                )
                time.sleep(wait)
        raise WarSpottingAPIError(f"采集 {day.isoformat()} 失败（重试 {self.settings.max_retries} 次）: {last_err}")
