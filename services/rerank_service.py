"""
Rerank 精排服务

功能：
1. 调用 Rerank API 对候选集精排
2. 返回 Top-K 结果
"""
import asyncio
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

import httpx

import config

logger = logging.getLogger(__name__)


@dataclass
class RerankResult:
    """Rerank 结果"""
    index: int  # 在原始候选集中的索引
    score: float  # Rerank 分数
    content: str  # 文本内容
    metadata: Dict[str, Any]  # 其他元数据


class RerankService:
    """
    Rerank 精排服务

    使用 Cross-Encoder 模型对候选集进行精排
    """

    def __init__(self):
        self.rerank_url = config.RERANK_URL
        self.model_name = config.RERANK_MODEL
        self.api_key = config.RERANK_API_KEY or config.EMBEDDING_API_KEY

        # HTTP 客户端
        self.client = httpx.AsyncClient(verify=config.LLM_VERIFY_SSL, timeout=60.0)

    async def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int = 10,
        text_key: str = "text_content",
    ) -> List[RerankResult]:
        """
        对候选集进行 Rerank

        Args:
            query: 查询文本
            candidates: 候选集列表，每个元素包含 text_content 和其他元数据
            top_k: 返回数量
            text_key: 文本内容的 key

        Returns:
            Rerank 后的结果列表
        """
        if not candidates:
            return []

        # 提取文本
        documents = [c.get(text_key, "") for c in candidates]

        try:
            response = await self.client.post(
                self.rerank_url,
                json={
                    "model": self.model_name,
                    "query": query,
                    "documents": documents,
                },
                headers={
                    "X-Gateway-Key": f"{self.api_key}",
                    "Content-Type": "application/json",
                },
            )

            if response.status_code != 200:
                error_msg = f"Rerank API 失败: HTTP {response.status_code} - {response.text}"
                logger.error(error_msg)
                raise ConnectionError(error_msg)

            data = response.json()
            results = data.get("results", [])

            if not results:
                raise ValueError(f"Rerank API 返回空结果: {data}")

            # 解析 Rerank 结果
            rerank_results = []
            for r in results[:top_k]:
                index = r.get("index", 0)
                score = r.get("relevance_score", 0)

                if 0 <= index < len(candidates):
                    candidate = candidates[index]
                    rerank_results.append(RerankResult(
                        index=index,
                        score=score,
                        content=candidate.get(text_key, ""),
                        metadata=candidate,
                    ))

            logger.info(f"Rerank 完成: {len(rerank_results)} 个结果")
            return rerank_results

        except (ConnectionError, ValueError):
            raise
        except Exception as e:
            error_msg = f"Rerank 服务异常: {type(e).__name__}: {e}"
            logger.error(error_msg)
            raise ConnectionError(error_msg)

    def _fallback_rerank(
        self,
        candidates: List[Dict],
        top_k: int,
        text_key: str,
    ) -> List[RerankResult]:
        """降级方案：返回原始顺序的前 top_k 个"""
        return [
            RerankResult(
                index=i,
                score=candidates[i].get("final_score", candidates[i].get("score", 0)),
                content=candidates[i].get(text_key, ""),
                metadata=candidates[i],
            )
            for i in range(min(top_k, len(candidates)))
        ]

    async def close(self):
        """关闭客户端"""
        await self.client.aclose()


# 便捷函数
async def rerank(
    query: str,
    candidates: List[Dict],
    top_k: int = 10,
) -> List[RerankResult]:
    """便捷函数：Rerank"""
    service = RerankService()
    try:
        return await service.rerank(query, candidates, top_k)
    finally:
        await service.close()
