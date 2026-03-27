"""
Milvus 向量数据库操作封装（异步兼容）
支持双集合：chunk_vectors + summary_vectors
使用 asyncio.to_thread 包装同步 pymilvus 调用
"""
import asyncio
import logging
from typing import List, Optional, Dict, Any

from pymilvus import MilvusClient, DataType

import config

logger = logging.getLogger(__name__)


class MilvusVectorClient:
    """
    异步 Milvus 向量检索客户端

    支持双集合：
    - chunk_vectors: Chunk 级别向量
    - summary_vectors: 摘要级别向量
    """

    def __init__(self):
        self.client: Optional[MilvusClient] = None
        self.chunk_collection = config.MILVUS_CHUNK_COLLECTION
        self.summary_collection = config.MILVUS_SUMMARY_COLLECTION
        self.dim = config.EMBEDDING_DIM

    def connect(self):
        self.client = MilvusClient(uri=config.MILVUS_URI, token=config.MILVUS_TOKEN)
        logger.info("✅ Milvus 连接成功")

    def close(self):
        if self.client:
            self.client.close()
            logger.info("Milvus 连接已关闭")

    def init_collections(self):
        """初始化双集合"""
        self._init_chunk_collection()
        self._init_summary_collection()

    def _init_chunk_collection(self):
        """初始化 Chunk 向量集合"""
        if self.client.has_collection(self.chunk_collection):
            logger.info(f"Milvus collection '{self.chunk_collection}' 已存在")
            return

        logger.info(f"🔨 创建 Milvus collection: {self.chunk_collection}")
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field("chunk_id", DataType.VARCHAR, max_length=256)
        schema.add_field("doc_id", DataType.VARCHAR, max_length=256)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.dim)
        schema.add_field("text_content", DataType.VARCHAR, max_length=4096)
        schema.add_field("section_name", DataType.VARCHAR, max_length=1024)

        index_params = self.client.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        index_params.add_index(field_name="chunk_id", index_type="Trie")
        index_params.add_index(field_name="doc_id", index_type="Trie")

        self.client.create_collection(
            collection_name=self.chunk_collection,
            schema=schema,
            index_params=index_params,
        )
        logger.info(f"✅ Milvus collection '{self.chunk_collection}' 创建成功")

    def _init_summary_collection(self):
        """初始化摘要向量集合"""
        if self.client.has_collection(self.summary_collection):
            logger.info(f"Milvus collection '{self.summary_collection}' 已存在")
            return

        logger.info(f"🔨 创建 Milvus collection: {self.summary_collection}")
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field("summary_id", DataType.VARCHAR, max_length=256)
        schema.add_field("doc_id", DataType.VARCHAR, max_length=256)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.dim)
        schema.add_field("summary_text", DataType.VARCHAR, max_length=4096)
        schema.add_field("summary_type", DataType.VARCHAR, max_length=64)

        index_params = self.client.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        index_params.add_index(field_name="summary_id", index_type="Trie")
        index_params.add_index(field_name="doc_id", index_type="Trie")

        self.client.create_collection(
            collection_name=self.summary_collection,
            schema=schema,
            index_params=index_params,
        )
        logger.info(f"✅ Milvus collection '{self.summary_collection}' 创建成功")

    # --------------------------------------------------
    # Chunk 向量操作（同步内部方法）
    # --------------------------------------------------

    def _insert_chunk_vectors_sync(self, chunks: List[Dict[str, Any]]):
        """
        批量插入 Chunk 向量

        Args:
            chunks: List of {
                "chunk_id": str,
                "doc_id": str,
                "vector": List[float],
                "text_content": str,
                "section_name": str,
            }
        """
        data = []
        for chunk in chunks:
            data.append({
                "chunk_id": chunk["chunk_id"],
                "doc_id": chunk["doc_id"],
                "vector": chunk["vector"],
                "text_content": chunk["text_content"][:4096],
                "section_name": chunk.get("section_name", "")[:512],
            })

        self.client.insert(collection_name=self.chunk_collection, data=data)
        logger.info(f"✅ Milvus 插入 {len(chunks)} 个 Chunk 向量")

    def _search_chunks_sync(
        self,
        query_vector: List[float],
        top_k: int = 10,
        doc_id_filter: Optional[str] = None,
    ) -> List[Dict]:
        """搜索相似 Chunk"""
        filter_str = f'doc_id == "{doc_id_filter}"' if doc_id_filter else None

        results = self.client.search(
            collection_name=self.chunk_collection,
            data=[query_vector],
            limit=top_k,
            filter=filter_str,
            output_fields=["chunk_id", "doc_id", "text_content", "section_name"],
        )

        matches = []
        if results and len(results) > 0:
            for hit in results[0]:
                matches.append({
                    "chunk_id": hit["entity"]["chunk_id"],
                    "doc_id": hit["entity"]["doc_id"],
                    "text_content": hit["entity"]["text_content"],
                    "section_name": hit["entity"]["section_name"],
                    "distance": hit["distance"],
                })
        return matches

    def _delete_chunks_by_doc_sync(self, doc_id: str):
        """删除指定文档的所有 Chunk 向量"""
        self.client.delete(
            collection_name=self.chunk_collection,
            filter=f'doc_id == "{doc_id}"'
        )
        logger.info(f"Milvus 删除文档 Chunk 向量: {doc_id}")

    # --------------------------------------------------
    # Summary 向量操作（同步内部方法）
    # --------------------------------------------------

    def _insert_summary_vector_sync(self, summary: Dict[str, Any]):
        """
        插入摘要向量

        Args:
            summary: {
                "summary_id": str,
                "doc_id": str,
                "vector": List[float],
                "summary_text": str,
                "summary_type": str,
            }
        """
        data = [{
            "summary_id": summary["summary_id"],
            "doc_id": summary["doc_id"],
            "vector": summary["vector"],
            "summary_text": summary["summary_text"][:4096],
            "summary_type": summary.get("summary_type", "event"),
        }]

        self.client.insert(collection_name=self.summary_collection, data=data)
        logger.info(f"✅ Milvus 插入摘要向量: {summary['summary_id']}")

    def _search_summaries_sync(
        self,
        query_vector: List[float],
        top_k: int = 10,
        summary_type_filter: Optional[str] = None,
    ) -> List[Dict]:
        """搜索相似摘要"""
        filter_str = f'summary_type == "{summary_type_filter}"' if summary_type_filter else None

        results = self.client.search(
            collection_name=self.summary_collection,
            data=[query_vector],
            limit=top_k,
            filter=filter_str,
            output_fields=["summary_id", "doc_id", "summary_text", "summary_type"],
        )

        matches = []
        if results and len(results) > 0:
            for hit in results[0]:
                matches.append({
                    "summary_id": hit["entity"]["summary_id"],
                    "doc_id": hit["entity"]["doc_id"],
                    "summary_text": hit["entity"]["summary_text"],
                    "summary_type": hit["entity"]["summary_type"],
                    "distance": hit["distance"],
                })
        return matches

    # --------------------------------------------------
    # 异步公开接口 - Chunk
    # --------------------------------------------------

    async def insert_chunk_vectors(self, chunks: List[Dict[str, Any]]):
        """批量插入 Chunk 向量（异步）"""
        await asyncio.to_thread(self._insert_chunk_vectors_sync, chunks)

    async def search_chunks(
        self,
        query_vector: List[float],
        top_k: int = 10,
        doc_id_filter: Optional[str] = None,
    ) -> List[Dict]:
        """搜索相似 Chunk（异步）"""
        return await asyncio.to_thread(self._search_chunks_sync, query_vector, top_k, doc_id_filter)

    async def delete_chunks_by_doc(self, doc_id: str):
        """删除指定文档的所有 Chunk 向量（异步）"""
        await asyncio.to_thread(self._delete_chunks_by_doc_sync, doc_id)

    # --------------------------------------------------
    # 异步公开接口 - Summary
    # --------------------------------------------------

    async def insert_summary_vector(self, summary: Dict[str, Any]):
        """插入摘要向量（异步）"""
        await asyncio.to_thread(self._insert_summary_vector_sync, summary)

    async def search_summaries(
        self,
        query_vector: List[float],
        top_k: int = 10,
        summary_type_filter: Optional[str] = None,
    ) -> List[Dict]:
        """搜索相似摘要（异步）"""
        return await asyncio.to_thread(self._search_summaries_sync, query_vector, top_k, summary_type_filter)

    # --------------------------------------------------
    # 兼容旧接口 (event_vectors)
    # --------------------------------------------------

    async def insert_event_vector(self, event_id: str, embedding: List[float], summary_preview: str):
        """兼容旧接口：插入事件向量"""
        summary = {
            "summary_id": event_id,
            "doc_id": "legacy",
            "vector": embedding,
            "summary_text": summary_preview,
            "summary_type": "event",
        }
        await self.insert_summary_vector(summary)

    async def search_similar_events(self, query_embedding: List[float], top_k: int = 10) -> List[dict]:
        """兼容旧接口：搜索相似事件"""
        return await self.search_summaries(query_embedding, top_k)

    async def delete_event_vector(self, event_id: str):
        """兼容旧接口：删除事件向量"""
        self.client.delete(
            collection_name=self.summary_collection,
            filter=f'summary_id == "{event_id}"'
        )
