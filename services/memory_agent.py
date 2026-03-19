"""
记忆拉取 Agent（全异步）
使用 function calling 从向量数据库和 PostgreSQL 中异步检索相关记忆
返回结构化检索结果 + 累计 token 统计
"""
import asyncio
import json
import logging
import time
from typing import List, Tuple

import config
from services.llm_client import LLMClient
from services.embedding_service import EmbeddingService
from database.milvus_client import MilvusVectorClient
from database.pg_client import PGClient
from utils.token_counter import count_tokens

logger = logging.getLogger(__name__)

# Function Calling 工具定义
MEMORY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "在向量数据库中搜索与查询内容相关的历史事件摘要",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要搜索的查询内容"},
                    "top_k": {"type": "integer", "description": "返回最大结果数量，默认5", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_full_scene",
            "description": "根据事件ID获取完整原始对话。仅在需要对话细节时使用",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "事件ID"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_character_info",
            "description": "根据人物名字查询人物志。仅在对话明确涉及特定人物时使用",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "人物的名字"},
                },
                "required": ["name"],
            },
        },
    },
]


class MemoryAgent:
    """异步记忆拉取 Agent"""

    def __init__(self, pg_client: PGClient, milvus_client: MilvusVectorClient, embedding_service: EmbeddingService):
        self.pg = pg_client
        self.milvus = milvus_client
        self.embedding = embedding_service
        self.llm = LLMClient(config.MEMORY_AGENT_MODEL)
        self._prompt = config.get_prompt("memory_agent_prompt").replace(
            "{max_memory_tokens}", str(config.MAX_MEMORY_TOKENS)
        )
        self.max_tokens = config.MAX_MEMORY_TOKENS
        self.max_rounds = config.MAX_RETRIEVAL_ROUNDS

    async def retrieve_memory(self, user_message: str, rolling_summaries: List[str]) -> Tuple[str, list, dict]:
        """
        异步检索相关记忆

        Returns:
            (memory_text, retrieved_memories, usage_info)
            - memory_text: 供 prompt 注入的记忆文本
            - retrieved_memories: 结构化的检索结果列表 [{event_id, summary_preview, event_date, weather}]
            - usage_info: {input_tokens, output_tokens, duration_ms}
        """
        t0 = time.monotonic()
        total_input_tokens = 0
        total_output_tokens = 0
        retrieved_memories = []  # 结构化记忆引用

        recent_context = ""
        if rolling_summaries:
            recent_context = "近期事件摘要:\n" + "\n".join(f"- {s}" for s in rolling_summaries)

        messages = [
            {"role": "system", "content": self._prompt},
            {"role": "user", "content": f"当前用户消息: {user_message}\n\n{recent_context}\n\n请检索相关记忆。"},
        ]

        collected_memories = []
        total_content_tokens = 0

        for round_num in range(self.max_rounds):
            logger.info(f"记忆检索第 {round_num + 1} 轮")

            result = await self.llm.chat_with_tools(messages=messages, tools=MEMORY_TOOLS, tool_choice="auto")

            # 累计 usage
            usage = result.get("usage", {})
            total_input_tokens += usage.get("input_tokens", 0)
            total_output_tokens += usage.get("output_tokens", 0)

            if not result["tool_calls"]:
                if result["content"]:
                    collected_memories.append(result["content"])
                break

            # 追加 assistant 消息
            assistant_msg = {"role": "assistant", "content": result["content"]}
            if result["tool_calls"]:
                assistant_msg["tool_calls"] = [
                    {"id": tc["id"], "type": "function", "function": tc["function"]}
                    for tc in result["tool_calls"]
                ]
            messages.append(assistant_msg)

            # 并发执行所有工具调用
            tool_tasks = []
            for tc in result["tool_calls"]:
                func_name = tc["function"]["name"]
                func_args = json.loads(tc["function"]["arguments"])
                tool_tasks.append((tc["id"], func_name, func_args, self._execute_tool(func_name, func_args)))

            # asyncio.gather 并发执行
            tool_results = await asyncio.gather(*[task[3] for task in tool_tasks], return_exceptions=True)

            for i, (tc_id, func_name, func_args, _) in enumerate(tool_tasks):
                if isinstance(tool_results[i], Exception):
                    tool_result_text = f"工具执行失败: {tool_results[i]}"
                    tool_structured = None
                else:
                    tool_result_text, tool_structured = tool_results[i]

                messages.append({"role": "tool", "tool_call_id": tc_id, "content": tool_result_text})

                # 收集结构化记忆引用
                if tool_structured and func_name == "search_memory":
                    retrieved_memories.extend(tool_structured)

                total_content_tokens += count_tokens(tool_result_text)

            if total_content_tokens >= self.max_tokens:
                logger.info(f"记忆 token 已达 {total_content_tokens}，停止检索")
                break

        # 最后一轮让 LLM 整理结果
        if len(messages) > 2:
            messages.append({"role": "user", "content": "请根据检索到的信息，整理并返回与当前对话最相关的记忆内容。"})
            final_result = await self.llm.chat(messages)
            final_usage = final_result.get("usage", {})
            total_input_tokens += final_usage.get("input_tokens", 0)
            total_output_tokens += final_usage.get("output_tokens", 0)
            final_text = final_result.get("content", "")
            if final_text:
                collected_memories.append(final_text)

        memory_text = "\n\n".join(collected_memories)
        if count_tokens(memory_text) > self.max_tokens:
            memory_text = self._truncate_memory(memory_text)

        duration_ms = int((time.monotonic() - t0) * 1000)
        usage_info = {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "duration_ms": duration_ms,
        }

        logger.info(f"记忆检索完成: {len(retrieved_memories)} 条引用, "
                     f"input={total_input_tokens} output={total_output_tokens} ({duration_ms}ms)")

        return memory_text, retrieved_memories, usage_info

    async def _execute_tool(self, func_name: str, func_args: dict) -> Tuple[str, list]:
        """
        异步执行工具调用

        Returns:
            (result_text, structured_data)
        """
        try:
            if func_name == "search_memory":
                return await self._tool_search_memory(func_args["query"], func_args.get("top_k", 5))
            elif func_name == "get_full_scene":
                text = await self._tool_get_full_scene(func_args["event_id"])
                return text, None
            elif func_name == "get_character_info":
                text = await self._tool_get_character_info(func_args["name"])
                return text, None
            else:
                return f"未知工具: {func_name}", None
        except Exception as e:
            logger.error(f"工具 {func_name} 执行失败: {e}")
            return f"工具执行失败: {str(e)}", None

    async def _tool_search_memory(self, query: str, top_k: int = 5) -> Tuple[str, list]:
        """异步搜索记忆，返回 (文本结果, 结构化引用列表)"""
        query_embedding = await self.embedding.embed_text(query)
        if not query_embedding:
            return "向量化失败，无法搜索", []

        results = await self.milvus.search_similar_events(query_embedding=query_embedding, top_k=top_k)
        if not results:
            return "未检索到相关记忆", []

        # 并发获取每个命中事件的详细信息（含日期天气）
        event_ids = [r["event_id"] for r in results]
        summary_tasks = [self.pg.get_event_summary(eid) for eid in event_ids]
        summaries = await asyncio.gather(*summary_tasks, return_exceptions=True)

        output_lines = []
        structured = []
        for i, r in enumerate(results):
            summary_obj = summaries[i] if not isinstance(summaries[i], Exception) else None
            event_date = summary_obj.event_date if summary_obj else ""
            weather = summary_obj.weather if summary_obj else ""

            output_lines.append(
                f"{i+1}. 事件ID: {r['event_id']}\n   日期: {event_date}\n   天气: {weather}\n"
                f"   相似度: {r['distance']:.4f}\n   摘要: {r['summary_preview']}"
            )
            structured.append({
                "event_id": r["event_id"],
                "summary_preview": r["summary_preview"],
                "event_date": event_date,
                "weather": weather,
            })

        return "\n\n".join(output_lines), structured

    async def _tool_get_full_scene(self, event_id: str) -> str:
        """异步获取完整场景对话"""
        rounds = await self.pg.get_conversation_by_event(event_id)
        if not rounds:
            return f"未找到事件 {event_id} 的对话记录"

        summary = await self.pg.get_event_summary(event_id)
        header = f"[{summary.event_date}] [{summary.weather}]\n" if summary else ""

        lines = [header]
        for r in rounds:
            lines.append(f"第{r.round_in_event}轮:")
            lines.append(f"  用户: {r.user_message}")
            lines.append(f"  助手: {r.assistant_message}")
        return "\n".join(lines)

    async def _tool_get_character_info(self, name: str) -> str:
        """异步获取人物志"""
        characters = await self.pg.search_characters_by_name(name)
        if not characters:
            return f"未找到名为 {name} 的人物信息"

        output = []
        for c in characters:
            info_parts = [f"姓名: {c['name']}", f"关系: {c.get('relationship', '未知')}", f"性别: {c.get('gender', '未知')}"]
            if c.get("hobbies"):
                info_parts.append(f"爱好: {c['hobbies']}")
            if c.get("evaluation"):
                info_parts.append(f"评价: {c['evaluation']}")
            if c.get("basic_info"):
                for k, v in c["basic_info"].items():
                    info_parts.append(f"{k}: {v}")
            output.append("\n".join(info_parts))
        return "\n---\n".join(output)

    def _truncate_memory(self, text: str) -> str:
        """截断记忆（允许最后一段超出）"""
        paragraphs = text.split("\n\n")
        result = []
        current_tokens = 0
        for p in paragraphs:
            p_tokens = count_tokens(p)
            if current_tokens + p_tokens > self.max_tokens and result:
                result.append(p)
                break
            result.append(p)
            current_tokens += p_tokens
        return "\n\n".join(result)
