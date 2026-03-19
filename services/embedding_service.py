"""
Embedding 服务封装（全异步）
使用本地 vLLM 部署的 Qwen3-Embedding 模型
"""
import logging
from typing import List

import httpx
from openai import AsyncOpenAI

import config

logger = logging.getLogger(__name__)


class EmbeddingService:
    """异步 Embedding 向量化服务"""

    def __init__(self):
        cfg = config.EMBEDDING_MODEL

        if not cfg.verify_ssl:
            http_client = httpx.AsyncClient(verify=False)
        else:
            http_client = httpx.AsyncClient()

        self.client = AsyncOpenAI(
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            http_client=http_client,
        )
        self.model_name = cfg.model

    async def embed_text(self, text: str) -> List[float]:
        """对单段文本生成 embedding 向量（异步）"""
        cleaned = text.replace("\n", " ").strip()
        if not cleaned:
            return []

        try:
            response = await self.client.embeddings.create(
                model=self.model_name,
                input=cleaned,
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Embedding 生成失败: {e}")
            return []

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """批量生成 embedding（异步）"""
        if not texts:
            return []

        cleaned = [t.replace("\n", " ").strip() for t in texts]
        cleaned = [t if t else " " for t in cleaned]

        try:
            response = await self.client.embeddings.create(
                model=self.model_name,
                input=cleaned,
            )
            return [d.embedding for d in response.data]
        except Exception as e:
            logger.error(f"批量 Embedding 生成失败: {e}")
            return [[] for _ in texts]
