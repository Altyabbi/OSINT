"""全局配置：所有敏感/可变项走环境变量或 .env 文件。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """系统配置。环境变量名与字段名一致（大小写不敏感），如 DATABASE_URL、OPENAI_API_KEY。"""

    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    # 数据库：默认 SQLite 便于本地/演示，生产切 PostgreSQL+PostGIS
    # 例：postgresql+psycopg2://osint:osint@localhost:5432/osint
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'osint.db').as_posix()}"

    # WarSpotting API
    warspotting_base_url: str = "https://warspotting.net/api/losses/russia"
    warspotting_lost_by: str = "Russia"
    request_interval_seconds: float = 1.5  # 礼貌抓取限速
    request_timeout_seconds: float = 30.0
    max_retries: int = 5
    backoff_base_seconds: float = 2.0

    # 输出目录
    raw_dir: str = str(BASE_DIR / "data" / "raw")
    report_dir: str = str(BASE_DIR / "outputs" / "reports")

    # LLM（OpenAI 兼容）。未配置 key 时报告/问答自动走确定性 fallback。
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2000

    # 定时采集（APScheduler）
    scheduler_hour: int = 6
    scheduler_minute: int = 40

    @property
    def raw_path(self) -> Path:
        return Path(self.raw_dir)

    @property
    def report_path(self) -> Path:
        return Path(self.report_dir)

    @property
    def llm_available(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
