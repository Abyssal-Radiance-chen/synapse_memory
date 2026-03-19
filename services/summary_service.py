"""
摘要服务（全异步）
负责话题结束判断和事件归纳
返回 (结果, usage_dict) 用于 token 统计
"""
import logging
import time
from typing import List, Tuple, Optional

import config
from services.llm_client import LLMClient
from database.models import CurrentEventContext

logger = logging.getLogger(__name__)


class SummaryService:
    """异步摘要服务"""

    def __init__(self):
        self.llm = LLMClient(config.SUMMARY_MODEL)
        self._judge_prompt = config.get_prompt("summary_judge_prompt")
        self._summary_prompt = config.get_prompt("summary_prompt")

    async def judge_event_ended(
        self,
        context_rounds: List[CurrentEventContext],
        new_user_message: str,
    ) -> Tuple[bool, dict]:
        """
        判断当前话题是否已结束（异步）

        将【已有上下文】+【用户新消息】一起发给 LLM 判定：
        - True: 新消息开启了新话题，已有上下文应被摘要
        - False: 话题仍在继续

        Returns:
            (is_ended, usage_dict)
        """
        context_text = self._format_context(context_rounds)
        user_input = (
            f"== 当前话题上下文 ==\n{context_text}\n\n"
            f"== 用户新消息 ==\n{new_user_message}\n\n"
            f"请判断用户新消息是否开启了新话题。"
        )

        t0 = time.monotonic()
        content, usage = await self.llm.simple_complete(self._judge_prompt, user_input)
        duration_ms = int((time.monotonic() - t0) * 1000)

        cleaned = content.strip().lower()
        is_ended = cleaned in ("true", "是", "结束", "yes")

        logger.info(f"话题结束判断: '{cleaned}' → {is_ended} ({duration_ms}ms)")

        usage_info = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "duration_ms": duration_ms,
        }
        return is_ended, usage_info

    async def summarize_event(
        self, event_id: str, event_date: str, weather: str,
        context_rounds: List[CurrentEventContext],
    ) -> Tuple[str, dict]:
        """
        归纳事件摘要（异步）

        Returns:
            (summary_text, usage_dict)
        """
        context_lines = []
        for r in context_rounds:
            ref = f"{event_id}_{r.round_in_event}"
            context_lines.append(f"[{ref}] 用户: {r.user_message}")
            context_lines.append(f"[{ref}] 助手: {r.assistant_message}")

        context_text = "\n".join(context_lines)
        user_input = (
            f"事件ID: {event_id}\n日期: {event_date}\n天气: {weather}\n"
            f"对话轮次数: {len(context_rounds)}\n\n对话内容:\n{context_text}\n\n请归纳这个事件的摘要。"
        )

        t0 = time.monotonic()
        summary, usage = await self.llm.simple_complete(self._summary_prompt, user_input)
        duration_ms = int((time.monotonic() - t0) * 1000)

        logger.info(f"事件 {event_id} 摘要生成完成，长度: {len(summary)} ({duration_ms}ms)")

        usage_info = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "duration_ms": duration_ms,
        }
        return summary, usage_info

    @staticmethod
    def _format_context(context_rounds: List[CurrentEventContext]) -> str:
        lines = []
        for r in context_rounds:
            lines.append(f"第{r.round_in_event}轮:")
            lines.append(f"  用户: {r.user_message}")
            lines.append(f"  助手: {r.assistant_message}")
        return "\n".join(lines)
