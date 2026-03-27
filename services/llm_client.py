"""
统一 LLM 调用封装（全异步）
支持多供应商、function calling、流式输出
所有方法返回 usage 信息用于 token 统计
"""
import json
import logging
from typing import List, Optional, AsyncGenerator, Tuple

import httpx
from openai import AsyncOpenAI

from config import ModelConfig

logger = logging.getLogger(__name__)


def _extract_usage(response) -> dict:
    """从 OpenAI 响应对象提取 usage 信息"""
    if response.usage:
        return {
            "input_tokens": response.usage.prompt_tokens or 0,
            "output_tokens": response.usage.completion_tokens or 0,
        }
    return {"input_tokens": 0, "output_tokens": 0}


class LLMClient:
    """
    统一的异步 LLM 客户端
    使用 AsyncOpenAI 进行全异步调用
    """

    def __init__(self, model_config: ModelConfig):
        self.config = model_config

        if not model_config.verify_ssl:
            http_client = httpx.AsyncClient(verify=False, timeout=60.0)
        else:
            http_client = httpx.AsyncClient(timeout=60.0)


        self.client = AsyncOpenAI(
            base_url=model_config.base_url,
            api_key=model_config.api_key,
            http_client=http_client,
            default_headers={
                "X-Gateway-Key": f"Bearer {model_config.api_key}",
            },
        )

    async def chat(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        tool_choice: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> dict:
        """非流式对话（异步），返回含 usage 的 dict"""
        kwargs = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }

        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        response = await self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        return {
            "content": choice.message.content,
            "finish_reason": choice.finish_reason,
            "usage": _extract_usage(response),
        }

    async def chat_stream(
        self,
        messages: List[dict],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator:
        """流式对话（异步 SSE），返回异步迭代器"""
        kwargs = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        stream = await self.client.chat.completions.create(**kwargs)
        return stream

    async def chat_with_tools(
        self,
        messages: List[dict],
        tools: List[dict],
        tool_choice: str = "auto",
        temperature: float = 0.3,
    ) -> dict:
        """Function Calling 对话（异步），返回含 usage 的 dict"""
        response = await self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            stream=False,
        )

        choice = response.choices[0]
        result = {
            "content": choice.message.content,
            "tool_calls": [],
            "finish_reason": choice.finish_reason,
            "usage": _extract_usage(response),
        }

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                result["tool_calls"].append(
                    {
                        "id": tc.id,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                )

        return result

    async def simple_complete(self, system_prompt: str, user_message: str) -> Tuple[str, dict]:
        """
        简单的一问一答（异步）

        Returns:
            (content, usage_dict)  usage_dict = {"input_tokens": N, "output_tokens": N}
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        result = await self.chat(messages, temperature=0.3)
        return result.get("content", ""), result.get("usage", {})
