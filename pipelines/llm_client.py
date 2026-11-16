"""LLM client 抽象层：OpenAI 兼容接口，key/base_url/model 走配置。

未配置 OPENAI_API_KEY 时 available=False，调用方自动降级为确定性模板写作，
保证日报 workflow 离线也能完整跑通。
"""
from __future__ import annotations

import logging

from config import Settings, get_settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = None
        if self.settings.openai_api_key:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url,
                timeout=60.0,
            )
        else:
            logger.info("未配置 OPENAI_API_KEY，LLM 功能降级为确定性 fallback")

    @property
    def available(self) -> bool:
        return self._client is not None

    def chat(self, system: str, user: str) -> str:
        """单轮对话补全。未配置 key 时抛错（调用方应先检查 available）。"""
        if self._client is None:
            raise RuntimeError("LLM 未配置（缺少 OPENAI_API_KEY），请使用 fallback 路径")
        resp = self._client.chat.completions.create(
            model=self.settings.openai_model,
            temperature=self.settings.llm_temperature,
            max_tokens=self.settings.llm_max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""
