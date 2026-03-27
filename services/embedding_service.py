"""
Embedding 服务封装（全异步）
支持自定义 Embedding API（Qwen3-Embedding 等）
"""
import logging
from typing import List

import httpx

import config

logger = logging.getLogger(__name__)


class EmbeddingService:
    """异步 Embedding 向量化服务"""

    def __init__(self):
        self.base_url = config.EMBEDDING_BASE_URL
        self.api_key = config.EMBEDDING_API_KEY
        self.model_name = config.EMBEDDING_NAME
        self.dim = config.EMBEDDING_DIM

        # HTTP 客户端
        self.client = httpx.AsyncClient(verify=config.LLM_VERIFY_SSL, timeout=60.0)

    async def embed_text(self, text: str) -> List[float]:
        """对单段文本生成 embedding 向量（异步）"""
        cleaned = text.replace("\n", " ").strip()
        if not cleaned:
            return []

        try:
            response = await self.client.post(
                self.base_url,
                json={
                    "model": self.model_name,
                    "input": cleaned,
                },
                headers={
                    "X-Gateway-Key": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )

            if response.status_code != 200:
                logger.error(f"Embedding 生成失败: {response.status_code} - {response.text}")
                return []

            data = response.json()
            return data["data"][0]["embedding"]

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
            response = await self.client.post(
                self.base_url,
                json={
                    "model": self.model_name,
                    "input": cleaned,
                },
                headers={
                    "X-Gateway-Key": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )

            if response.status_code != 200:
                logger.error(f"批量 Embedding 生成失败: {response.status_code} - {response.text}")
                return [[] for _ in texts]

            data = response.json()
            return [d["embedding"] for d in data["data"]]

        except Exception as e:
            logger.error(f"批量 Embedding 生成失败: {e}")
            return [[] for _ in texts]

    async def close(self):
        """关闭客户端"""
        await self.client.aclose()
