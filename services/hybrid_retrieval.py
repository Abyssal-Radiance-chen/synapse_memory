"""
混合检索服务 (Hybrid Retrieval)

三路并行检索 + RRF 融合：
1. ES BM25 全文检索
2. Milvus 摘要向量检索
3. Milvus Chunk 向量检索

RRF 公式:
score(doc) = α/(k + rank_es) + β/(k + rank_summary_vec) + γ/(k + rank_chunk_vec)
其中 α + β + γ = 1，k = 60
"""
import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

import config

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """检索结果"""
    chunk_id: str
    doc_id: str
    text_content: str
    section_name: str
    final_score: float  # RRF 融合分数
    es_score: float = 0
    summary_vec_score: float = 0
    chunk_vec_score: float = 0
    source_chunks: Optional[List[str]] = None  # 关联的摘要源 chunks


class HybridRetrievalService:
    """
    混合检索服务

    三路检索 + RRF 融合
    """

    def __init__(self):
        from services.es_retrieval import ESRetrievalService
        from services.embedding_service import EmbeddingService
        from database.milvus_client import MilvusVectorClient
        from database.pg_client import PGClient

        self.es_service = ESRetrievalService()
        self.embedding_service = EmbeddingService()
        self.milvus_client = MilvusVectorClient()
        self.milvus_client.connect()
        self.pg_client = PGClient()
        self.pg_client.connect()

        # RRF 参数
        self.k = config.RRF_K  # 60
        self.alpha = config.RRF_ALPHA  # ES 权重
        self.beta = config.RRF_BETA  # 摘要向量权重
        self.gamma = config.RRF_GAMMA  # Chunk 向量权重

    async def retrieve(
        self,
        query: str,
        top_k: int = 20,
        es_top_k: int = 30,
        vec_top_k: int = 30,
    ) -> List[RetrievalResult]:
        """
        混合检索

        Args:
            query: 查询文本
            top_k: 最终返回数量
            es_top_k: ES 检索数量
            vec_top_k: 向量检索数量

        Returns:
            融合后的检索结果列表
        """
        # 1. 获取查询向量
        query_vector = await self.embedding_service.embed_text(query)
        if not query_vector:
            logger.warning("查询向量生成失败，降级为纯 ES 检索")
            return await self._es_only_retrieve(query, top_k)

        # 2. 三路并行检索
        es_task = self.es_service.search_chunks(query, es_top_k)
        summary_vec_task = self.milvus_client.search_summaries(query_vector, vec_top_k)
        chunk_vec_task = self.milvus_client.search_chunks(query_vector, vec_top_k)

        es_results, summary_vec_results, chunk_vec_results = await asyncio.gather(
            es_task, summary_vec_task, chunk_vec_task
        )

        logger.info(f"三路检索完成: ES={len(es_results)}, 摘要向量={len(summary_vec_results)}, Chunk向量={len(chunk_vec_results)}")

        # 3. RRF 融合
        merged_results = self._rrf_merge(
            es_results,
            summary_vec_results,
            chunk_vec_results,
        )

        # 4. 补充 Chunk 详细信息
        enriched_results = await self._enrich_results(merged_results[:top_k])

        return enriched_results

    def _rrf_merge(
        self,
        es_results: List[Dict],
        summary_vec_results: List[Dict],
        chunk_vec_results: List[Dict],
    ) -> List[RetrievalResult]:
        """
        RRF 融合三路检索结果

        RRF 公式:
        score(doc) = α/(k + rank_es) + β/(k + rank_summary_vec) + γ/(k + rank_chunk_vec)
        """
        # 使用 chunk_id 作为 key 汇总分数
        score_map: Dict[str, Dict] = {}

        # 处理 ES 结果
        for rank, result in enumerate(es_results, 1):
            chunk_id = result.get("chunk_id")
            if not chunk_id:
                continue

            if chunk_id not in score_map:
                score_map[chunk_id] = {
                    "chunk_id": chunk_id,
                    "doc_id": result.get("doc_id", ""),
                    "text_content": result.get("text_content", ""),
                    "section_name": result.get("section_name", ""),
                    "es_score": self.alpha / (self.k + rank),
                    "summary_vec_score": 0,
                    "chunk_vec_score": 0,
                    "source_chunks": None,
                }
            else:
                score_map[chunk_id]["es_score"] = self.alpha / (self.k + rank)

        # 处理摘要向量结果
        for rank, result in enumerate(summary_vec_results, 1):
            # 摘要向量结果可能关联多个 chunk
            source_chunks = result.get("source_chunks", [])
            if not source_chunks:
                continue

            summary_score = self.beta / (self.k + rank)

            for chunk_id in source_chunks:
                if chunk_id not in score_map:
                    # 需要从数据库获取 chunk 信息
                    score_map[chunk_id] = {
                        "chunk_id": chunk_id,
                        "doc_id": result.get("doc_id", ""),
                        "text_content": "",
                        "section_name": "",
                        "es_score": 0,
                        "summary_vec_score": summary_score,
                        "chunk_vec_score": 0,
                        "source_chunks": source_chunks,
                    }
                else:
                    score_map[chunk_id]["summary_vec_score"] = max(
                        score_map[chunk_id]["summary_vec_score"],
                        summary_score
                    )

        # 处理 Chunk 向量结果
        for rank, result in enumerate(chunk_vec_results, 1):
            chunk_id = result.get("chunk_id")
            if not chunk_id:
                continue

            chunk_score = self.gamma / (self.k + rank)

            if chunk_id not in score_map:
                score_map[chunk_id] = {
                    "chunk_id": chunk_id,
                    "doc_id": result.get("doc_id", ""),
                    "text_content": result.get("text_content", ""),
                    "section_name": result.get("section_name", ""),
                    "es_score": 0,
                    "summary_vec_score": 0,
                    "chunk_vec_score": chunk_score,
                    "source_chunks": None,
                }
            else:
                score_map[chunk_id]["chunk_vec_score"] = max(
                    score_map[chunk_id]["chunk_vec_score"],
                    chunk_score
                )

        # 计算最终分数并排序
        results = []
        for chunk_id, data in score_map.items():
            final_score = data["es_score"] + data["summary_vec_score"] + data["chunk_vec_score"]
            results.append(RetrievalResult(
                chunk_id=chunk_id,
                doc_id=data["doc_id"],
                text_content=data["text_content"],
                section_name=data["section_name"],
                final_score=final_score,
                es_score=data["es_score"],
                summary_vec_score=data["summary_vec_score"],
                chunk_vec_score=data["chunk_vec_score"],
                source_chunks=data["source_chunks"],
            ))

        # 按最终分数降序排序
        results.sort(key=lambda x: x.final_score, reverse=True)

        logger.info(f"RRF 融合完成: {len(results)} 个候选")
        return results

    async def _enrich_results(self, results: List[RetrievalResult]) -> List[RetrievalResult]:
        """补充 Chunk 详细信息"""
        for result in results:
            if not result.text_content:
                # 从数据库获取 chunk 信息
                chunk_data = await self.pg_client.get_chunk(result.chunk_id)
                if chunk_data:
                    result.text_content = chunk_data.get("text_content", "")
                    result.section_name = chunk_data.get("section_name", "")
                    result.doc_id = chunk_data.get("doc_id", result.doc_id)

        return results

    async def _es_only_retrieve(self, query: str, top_k: int) -> List[RetrievalResult]:
        """降级方案：纯 ES 检索"""
        es_results = await self.es_service.search_chunks(query, top_k)

        return [
            RetrievalResult(
                chunk_id=r.get("chunk_id", ""),
                doc_id=r.get("doc_id", ""),
                text_content=r.get("text_content", ""),
                section_name=r.get("section_name", ""),
                final_score=r.get("score", 0),
                es_score=r.get("score", 0),
            )
            for r in es_results
        ]

    def close(self):
        """关闭连接"""
        self.milvus_client.close()
        self.pg_client.close()


# 便捷函数
async def hybrid_retrieve(query: str, top_k: int = 20) -> List[RetrievalResult]:
    """便捷函数：混合检索"""
    service = HybridRetrievalService()
    try:
        return await service.retrieve(query, top_k)
    finally:
        service.close()
