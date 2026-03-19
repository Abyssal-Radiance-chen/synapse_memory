"""
对话 API 路由（全异步）
SSE 流式输出，兼容 OpenAI /v1/chat/completions 格式
"""
import logging
from typing import List

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "default"
    messages: List[ChatMessage] = Field(..., description="对话消息列表")
    stream: bool = True
    temperature: float = 0.7
    max_tokens: int = None


class ChatRegenerateRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., description="修改后的对话消息列表")
    target_round: int = Field(default=-1, description="要重新生成的轮次 (>= 1, 或 -1 表示最后一轮)")


@router.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, req: Request):
    """对话接口 - OpenAI 标准兼容，异步 SSE 流式输出"""
    chat_service = req.app.state.chat_service

    user_message = ""
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_message = msg.content
            break

    if not user_message:
        return {"error": "未找到用户消息"}

    # handle_message 返回异步生成器
    async_generator = chat_service.handle_message(user_message)

    return StreamingResponse(
        async_generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@router.post("/v1/chat/regenerate")
async def chat_regenerate(request: ChatRegenerateRequest, req: Request):
    """对话重生成接口 - 回滚至指定轮次并基于修改后的消息生成新回复"""
    chat_service = req.app.state.chat_service

    user_message = ""
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_message = msg.content
            break

    if not user_message:
        return {"error": "未找到用户消息"}

    # regenerate_message 返回异步生成器，内部会处理数据库回滚
    async_generator = chat_service.regenerate_message(user_message, request.target_round)

    return StreamingResponse(
        async_generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
