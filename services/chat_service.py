"""
交互 AI 服务（全异步 + 并行优化 + 全链路统计）
SSE 流式输出 + 后台异步任务
话题判断 & 记忆拉取 并行执行
输出 metadata chunk（token + 耗时 + 上下文引用）
"""
import asyncio
import json
import logging
import time
import uuid
from typing import AsyncGenerator, List

import config
from services.llm_client import LLMClient
from services.memory_agent import MemoryAgent
from services.summary_service import SummaryService
from services.realtime_info import RealtimeInfoService
from services.embedding_service import EmbeddingService
from database.pg_client import PGClient
from database.milvus_client import MilvusVectorClient
from database.models import (
    ConversationRound,
    CurrentEventContext,
    EventSummary,
)

logger = logging.getLogger(__name__)


class ChatService:
    """异步交互 AI 服务 — 核心业务协调器"""

    def __init__(self, pg_client: PGClient, milvus_client: MilvusVectorClient, embedding_service: EmbeddingService):
        self.pg = pg_client
        self.milvus = milvus_client
        self.embedding = embedding_service

        self.chat_llm = LLMClient(config.CHAT_MODEL)
        self.memory_agent = MemoryAgent(pg_client, milvus_client, embedding_service)
        self.summary_service = SummaryService()
        self.realtime_info = RealtimeInfoService()

        self._chat_prompt_template = config.get_prompt("chat_prompt")

    async def regenerate_message(self, user_message: str, target_round: int = -1) -> AsyncGenerator[str, None]:
        """
        重新生成/编辑特定轮次的消息
        1. 校验 target_round 的有效性
        2. 回退 system_state 的 rounds
        3. 删除目标轮次之后的当前事件上下文
        4. 走正常的 handle_message 流程
        """
        state = await self.pg.get_system_state()
        
        if target_round == -1:
            target_round = state.current_event_round
            
        # 校验：不能编辑已经归档的历史话题，只能编辑当前活跃事件的轮次
        if target_round <= 0 or target_round > state.current_event_round:
            # 如果目标轮次不合法，返回错误流
            async def error_stream():
                yield f'data: {{"error": "无法编辑该轮次：目标轮次 {target_round} 超出当前话题范围"}}\n\n'
                yield "data: [DONE]\n\n"
            async for chunk in error_stream():
                yield chunk
            return

        # 数据库回滚：
        # 1. 删除 >= target_round 的上下文
        await self.pg.truncate_context_from_round(state.current_event_id, target_round)
        
        # 2. 回退系统状态的轮次 (回退到 target_round - 1)
        # 例如要编辑第 3 轮，系统状态就回退到刚完成第 2 轮的状态
        round_diff = state.current_event_round - (target_round - 1)
        new_event_round = target_round - 1
        new_global_round = state.global_round - round_diff
        
        await self.pg.update_system_state(
            current_event_round=new_event_round,
            global_round=new_global_round,
        )
        
        logger.info(f"重新生成：已将话题 {state.current_event_id} 回退至第 {new_event_round} 轮状态，开始处理新消息...")
        
        # 调用标准的 handle_message，自然会把 user_message 当成新的第 target_round 轮来处理
        async_gen = self.handle_message(user_message, is_regeneration=True)
        async for chunk in async_gen:
            yield chunk

    async def handle_message(self, user_message: str, is_regeneration: bool = False) -> AsyncGenerator[str, None]:
        """
        处理用户消息 — 并行优化 + 全链路统计

        话题判断逻辑:
        ┌────────────────────────────────────────────────────┐
        │ 第1轮: 不判断，直接作为当前话题第1轮                  │
        │ 第N轮(N≥2): [当前上下文] + [新消息] → 判断AI         │
        │   false → 话题继续，新消息加入当前话题                │
        │   true  → 已有上下文全部摘要+索引                    │
        │          → 新消息成为新话题第1轮                     │
        └────────────────────────────────────────────────────┘
        """
        total_start = time.monotonic()
        usage_stats = {}  # 收集各阶段 usage

        # ① 并发获取系统状态 + 当前上下文 + 滚动摘要
        state, context_rounds, rolling = await asyncio.gather(
            self.pg.get_system_state(),
            self.pg.get_current_event_context(),
            self.pg.get_rolling_summaries(),
        )

        rolling_texts = [r.summary_text for r in rolling]
        has_existing_context = state.current_event_round >= 1 and len(context_rounds) > 0

        # ② 构建并行任务
        parallel_tasks = {}

        # 记忆拉取 — 始终执行
        parallel_tasks["memory"] = self.memory_agent.retrieve_memory(user_message, rolling_texts)

        # 话题结束判断 — 第2轮消息起，且不是重新生成时
        if has_existing_context and not is_regeneration:
            parallel_tasks["judge"] = self.summary_service.judge_event_ended(context_rounds, user_message)

        # 首轮（无上下文时）获取时间天气
        if not has_existing_context:
            parallel_tasks["weather"] = self.realtime_info.get_event_time_weather()

        # 并行执行
        task_keys = list(parallel_tasks.keys())
        task_coros = list(parallel_tasks.values())
        results = await asyncio.gather(*task_coros, return_exceptions=True)

        # 解析结果
        result_map = {}
        for i, key in enumerate(task_keys):
            if isinstance(results[i], Exception):
                logger.error(f"并行任务 {key} 失败: {results[i]}")
                result_map[key] = None
            else:
                result_map[key] = results[i]

        # 解包记忆结果 (memory_text, retrieved_memories, memory_usage)
        memory_result = result_map.get("memory")
        if memory_result:
            memory_text, retrieved_memories, memory_usage = memory_result
            usage_stats["memory"] = memory_usage
        else:
            memory_text, retrieved_memories = "", []

        # 解包话题判断结果 (is_ended, judge_usage)
        judge_result = result_map.get("judge")
        event_ended = False
        if judge_result:
            event_ended, judge_usage = judge_result
            usage_stats["judge"] = judge_usage

        # 处理首轮时间天气
        if not has_existing_context and result_map.get("weather"):
            time_weather = result_map["weather"]
            await self.pg.update_system_state(
                event_start_time=time_weather["date"],
                event_start_weather=time_weather["weather"],
            )
            state.event_start_time = time_weather["date"]
            state.event_start_weather = time_weather["weather"]

        # ③ 如果话题已结束 → 归档旧话题，当前消息成为新话题第1轮
        if event_ended:
            logger.info(f"话题 {state.current_event_id} 已结束，新消息开启新话题，开始归档")
            await self._finalize_event(state.current_event_id, state, context_rounds)
            # 归档后重新获取状态
            state = await self.pg.get_system_state()
            context_rounds = []  # 上下文已清空
            # 新话题首轮，获取时间天气
            time_weather = await self.realtime_info.get_event_time_weather()
            await self.pg.update_system_state(
                event_start_time=time_weather["date"],
                event_start_weather=time_weather["weather"],
            )
            state.event_start_time = time_weather["date"]
            state.event_start_weather = time_weather["weather"]

        # ④ 构建 prompt
        system_prompt = self._build_system_prompt(
            time_info=state.event_start_time or "",
            weather_info=state.event_start_weather or "",
            memory_context=memory_text,
        )

        # ⑤ 构建消息列表
        messages = [{"role": "system", "content": system_prompt}]
        for r in context_rounds:
            messages.append({"role": "user", "content": r.user_message})
            messages.append({"role": "assistant", "content": r.assistant_message})
        messages.append({"role": "user", "content": user_message})

        # ⑥ 构建上下文元数据
        context_metadata = {
            "current_topic": {
                "event_id": state.current_event_id,
                "rounds": [r.round_in_event for r in context_rounds],
                "event_date": state.event_start_time or "",
                "weather": state.event_start_weather or "",
            },
            "rolling_summaries": [
                {
                    "event_id": r.event_id,
                    "summary": r.summary_text[:200],
                    "event_date": r.event_date,
                    "position": r.position,
                }
                for r in rolling
            ],
            "retrieved_memories": retrieved_memories,
        }

        # ⑦ 流式输出 + metadata
        async for chunk in self._stream_with_metadata(
            messages, user_message, state, usage_stats, context_metadata, total_start
        ):
            yield chunk

    async def _stream_with_metadata(
        self, messages: list, user_message: str, state,
        usage_stats: dict, context_metadata: dict, total_start: float,
    ) -> AsyncGenerator[str, None]:
        """异步流式输出，完成后输出 metadata chunk"""
        full_response = []
        chat_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"

        chat_start = time.monotonic()
        stream = await self.chat_llm.chat_stream(messages)

        chat_input_tokens = 0
        chat_output_tokens = 0

        async for chunk in stream:
            # 提取 usage（stream_options: include_usage）
            if hasattr(chunk, "usage") and chunk.usage:
                chat_input_tokens = chunk.usage.prompt_tokens or 0
                chat_output_tokens = chunk.usage.completion_tokens or 0

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            content = delta.content if delta.content else ""

            if content:
                full_response.append(content)

            sse_data = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "choices": [{
                    "index": 0,
                    "delta": {"content": content} if content else {},
                    "finish_reason": chunk.choices[0].finish_reason,
                }],
            }

            yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"

            if chunk.choices[0].finish_reason == "stop":
                break

        chat_duration_ms = int((time.monotonic() - chat_start) * 1000)
        total_duration_ms = int((time.monotonic() - total_start) * 1000)

        # 回退：如果模型提供商不支持在流式输出中返回 usage
        if chat_input_tokens == 0:
            try:
                import tiktoken
                enc = tiktoken.get_encoding("cl100k_base")
                chat_input_tokens = sum(len(enc.encode(m.get("content", ""))) for m in messages)
                chat_output_tokens = len(enc.encode("".join(full_response)))
            except ImportError:
                # 非常粗略的 fallback
                chat_input_tokens = sum(len(str(m.get("content", ""))) for m in messages) // 2
                chat_output_tokens = len("".join(full_response)) // 2

        # 记录主对话 usage
        usage_stats["chat"] = {
            "input_tokens": chat_input_tokens,
            "output_tokens": chat_output_tokens,
            "duration_ms": chat_duration_ms,
        }

        # 发送 metadata chunk（在 [DONE] 之前）
        metadata = {
            "type": "metadata",
            "usage": usage_stats,
            "total_duration_ms": total_duration_ms,
            "context": context_metadata,
        }
        yield f"data: {json.dumps(metadata, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

        # 后台保存
        assistant_message = "".join(full_response)
        asyncio.create_task(self._post_save(user_message, assistant_message, state))

    async def _post_save(self, user_message: str, assistant_message: str, state):
        """后台异步保存（仅保存，不做判断）"""
        try:
            new_event_round = state.current_event_round + 1
            new_global_round = state.global_round + 1
            event_id = state.current_event_id
            message_id = f"{event_id}_{new_event_round}"

            await asyncio.gather(
                self.pg.save_conversation_round(
                    ConversationRound(
                        message_id=message_id, event_id=event_id,
                        round_in_event=new_event_round, global_round=new_global_round,
                        user_message=user_message, assistant_message=assistant_message,
                    )
                ),
                self.pg.add_context_round(
                    CurrentEventContext(
                        event_id=event_id, round_in_event=new_event_round,
                        user_message=user_message, assistant_message=assistant_message,
                    )
                ),
                self.pg.update_system_state(
                    current_event_round=new_event_round,
                    global_round=new_global_round,
                ),
            )
        except Exception as e:
            logger.error(f"后台保存失败: {e}", exc_info=True)

    async def _finalize_event(self, event_id: str, state, context_rounds):
        """话题结束：生成摘要 → 存储 → 向量化 → 滚动窗口 → 新话题"""
        event_date = state.event_start_time or ""
        weather = state.event_start_weather or ""

        # 生成摘要
        summary_text, summary_usage = await self.summary_service.summarize_event(
            event_id=event_id, event_date=event_date, weather=weather,
            context_rounds=context_rounds,
        )
        logger.info(f"摘要生成 usage: {summary_usage}")

        # 并发：存PG + 向量化
        summary_embedding, _ = await asyncio.gather(
            self.embedding.embed_text(summary_text),
            self.pg.save_event_summary(
                EventSummary(
                    event_id=event_id, summary_text=summary_text,
                    event_date=event_date, weather=weather,
                    start_round=context_rounds[0].round_in_event if context_rounds else 0,
                    end_round=context_rounds[-1].round_in_event if context_rounds else 0,
                    round_count=len(context_rounds),
                )
            ),
        )

        # 向量存入 Milvus
        if summary_embedding:
            await self.milvus.insert_event_vector(event_id, summary_embedding, summary_text[:2000])

        # 并发：推送滚动窗口 + 清空上下文 + 创建新事件
        new_event_id = self.pg.generate_new_event_id()
        await asyncio.gather(
            self.pg.push_rolling_summary(event_id, summary_text, event_date),
            self.pg.clear_current_event_context(),
            self.pg.update_system_state(
                current_event_id=new_event_id,
                current_event_round=0,
                event_start_time=None,
                event_start_weather=None,
            ),
        )

        logger.info(f"话题 {event_id} 已归档，新话题 {new_event_id} 已创建")

    def _build_system_prompt(self, time_info: str, weather_info: str, memory_context: str) -> str:
        prompt = self._chat_prompt_template
        time_parts = []
        if time_info:
            time_parts.append(f"当前时间: {time_info}")
        if weather_info:
            time_parts.append(f"当前天气: {weather_info}")
        time_block = "\n".join(time_parts)
        memory_block = f"相关记忆:\n{memory_context}" if memory_context else "暂无相关记忆"
        prompt = prompt.replace("{time_info}", time_block)
        prompt = prompt.replace("{memory_context}", memory_block)
        prompt = prompt.replace("{character_context}", "")
        return prompt
