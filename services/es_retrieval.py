"""
Elasticsearch 全文检索服务

功能：
1. BM25 全文检索 Chunk
2. BM25 全文检索摘要
3. 支持中文 IK 分词
"""
import asyncio
import logging
from typing import List, Dict, Any, Optional

import config

logger = logging.getLogger(__name__)


class ESRetrievalService:
    """
    Elasticsearch 全文检索服务

    使用 BM25 算法进行全文检索
    """

    def __init__(self):
        from database.es_client import ESClient
        self.es_client = ESClient()

    async def search_chunks(
        self,
        query: str,
        top_k: int = 20,
        doc_id_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        全文检索 Chunk

        Args:
            query: 查询文本
            top_k: 返回数量
            doc_id_filter: 文档 ID 过滤

        Returns:
            检索结果列表，每个元素包含:
            - chunk_id
            - doc_id
            - text_content
            - section_name
            - score (BM25 分数)
        """
        filters = {"doc_id": doc_id_filter} if doc_id_filter else None
        results = await self.es_client.search_chunks(query, top_k, filters)

        return [
            {
                "chunk_id": r.get("chunk_id"),
                "doc_id": r.get("doc_id"),
                "text_content": r.get("text_content"),
                "section_name": r.get("section_name"),
                "score": r.get("score", 0),
            }
            for r in results
        ]

    async def search_summaries(
        self,
        query: str,
        top_k: int = 10,
        summary_type_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        全文检索摘要

        Args:
            query: 查询文本
            top_k: 返回数量
            summary_type_filter: 摘要类型过滤 (section/event/conversation)

        Returns:
            检索结果列表
        """
        filters = {"summary_type": summary_type_filter} if summary_type_filter else None
        results = await self.es_client.search_summaries(query, top_k, filters)

        return [
            {
                "summary_id": r.get("summary_id"),
                "doc_id": r.get("doc_id"),
                "summary_text": r.get("summary_text"),
                "summary_type": r.get("summary_type"),
                "score": r.get("score", 0),
            }
            for r in results
        ]

    async def hybrid_search(
        self,
        query: str,
        chunk_top_k: int = 20,
        summary_top_k: int = 10,
    ) -> Dict[str, List[Dict]]:
        """
        同时检索 Chunk 和摘要

        Args:
            query: 查询文本
            chunk_top_k: Chunk 返回数量
            summary_top_k: 摘要返回数量

        Returns:
            {"chunks": [...], "summaries": [...]}
        """
        # 并行检索
        chunks_task = self.search_chunks(query, chunk_top_k)
        summaries_task = self.search_summaries(query, summary_top_k)

        chunks, summaries = await asyncio.gather(chunks_task, summaries_task)

        return {
            "chunks": chunks,
            "summaries": summaries,
        }


# 便捷函数
async def es_search_chunks(query: str, top_k: int = 20) -> List[Dict]:
    """便捷函数：全文检索 Chunk"""
    service = ESRetrievalService()
    return await service.search_chunks(query, top_k)


async def es_search_summaries(query: str, top_k: int = 10) -> List[Dict]:
    """便捷函数：全文检索摘要"""
    service = ESRetrievalService()
    return await service.search_summaries(query, top_k)
