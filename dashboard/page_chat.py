"""智能问答页：聊天式界面，调用 agent 模块，展示回答 + 结构化数据 + 记录 ID。"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

import common
from agent.agent import OsintAgent

EXAMPLE_QUESTIONS = [
    "2024-06-15 俄军损失了多少辆坦克？",
    "近7天损失趋势？",
    '单位"第114旅"的损失历史？',
]


def run_agent(question: str) -> dict[str, Any]:
    """页面问答的后端调用（与 CLI 共用 agent.agent.OsintAgent）。"""
    with common.new_session() as s:
        agent = OsintAgent(s, common.get_app_settings())
        return agent.ask(question)


def _render_meta(meta: dict[str, Any]) -> None:
    st.caption(f"调用工具：{meta.get('used_tools') or '无'}｜降级模式：{meta.get('fallback')}")
    tool_result = meta.get("tool_result")
    if not isinstance(tool_result, dict):
        return
    records = tool_result.get("records")
    if records:
        st.dataframe(pd.DataFrame(records), use_container_width=True)
    with st.expander("命中的结构化数据（含来源署名）"):
        st.json(tool_result)


def render() -> None:
    st.header("智能问答")
    if not common.get_app_settings().llm_available:
        st.info("未配置 OPENAI_API_KEY，当前为关键词路由降级模式：可识别日期（YYYY-MM-DD）、"
                "近 N 天/近两周/上周/上个月、类别关键词（坦克/无人机/火炮等）、"
                "型号（如 T-90M）、带引号的单位名。配置 key 后自动切换为 LLM 工具调用模式。")
    st.caption("示例：" + "；".join(EXAMPLE_QUESTIONS))

    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant" and msg.get("meta"):
                _render_meta(msg["meta"])

    question = st.chat_input("输入问题，如：2024-06-15 俄军损失了多少辆坦克？")
    if not question:
        return
    st.session_state.chat_messages.append({"role": "user", "content": question})
    with st.spinner("正在查询……"):
        try:
            result = run_agent(question)
            answer = result["answer"]
            meta = {k: result.get(k) for k in ("used_tools", "fallback", "tool_result")}
        except Exception as exc:  # 含数字校验拦截
            answer = f"回答生成失败（已拦截）：{exc}"
            meta = None
    st.session_state.chat_messages.append({"role": "assistant", "content": answer, "meta": meta})
    st.rerun()
