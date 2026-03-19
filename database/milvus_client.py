"""
Milvus 向量数据库操作封装（异步兼容）
使用 asyncio.to_thread 包装同步 pymilvus 调用
"""
import asyncio
import logging
from typing import List, Optional

from pymilvus import MilvusClient, DataType

import config

logger = logging.getLogger(__name__)


class MilvusVectorClient:
    """异步 Milvus 向量检索客户端"""

    def __init__(self):
        self.client: Optional[MilvusClient] = None
        self.collection_name = config.MILVUS_COLLECTION_NAME

    def connect(self):
        self.client = MilvusClient(uri=config.MILVUS_URI, token=config.MILVUS_TOKEN)
        logger.info("✅ Milvus 连接成功")

    def close(self):
        if self.client:
            self.client.close()
            logger.info("Milvus 连接已关闭")

    def init_collection(self):
        if self.client.has_collection(self.collection_name):
            logger.info(f"Milvus collection '{self.collection_name}' 已存在")
            return

        logger.info(f"🔨 创建 Milvus collection: {self.collection_name}")
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("event_id", DataType.VARCHAR, is_primary=True, max_length=50)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=config.EMBEDDING_DIM)
        schema.add_field("summary_preview", DataType.VARCHAR, max_length=2000)

        index_params = self.client.prepare_index_params()
        index_params.add_index(field_name="embedding", index_type="AUTOINDEX", metric_type="COSINE")

        self.client.create_collection(
            collection_name=self.collection_name, schema=schema, index_params=index_params,
        )
        logger.info("✅ Milvus collection 创建成功")

    # --------------------------------------------------
    # 同步内部方法
    # --------------------------------------------------

    def _insert_event_vector_sync(self, event_id: str, embedding: List[float], summary_preview: str):
        self.client.insert(
            collection_name=self.collection_name,
            data=[{"event_id": event_id, "embedding": embedding, "summary_preview": summary_preview[:2000]}],
        )
        logger.info(f"✅ Milvus 插入事件向量: {event_id}")

    def _search_similar_events_sync(self, query_embedding: List[float], top_k: int = 10) -> List[dict]:
        results = self.client.search(
            collection_name=self.collection_name,
            data=[query_embedding],
            limit=top_k,
            output_fields=["event_id", "summary_preview"],
        )
        matches = []
        if results and len(results) > 0:
            for hit in results[0]:
                matches.append({
                    "event_id": hit["entity"]["event_id"],
                    "summary_preview": hit["entity"]["summary_preview"],
                    "distance": hit["distance"],
                })
        return matches

    def _delete_event_vector_sync(self, event_id: str):
        self.client.delete(collection_name=self.collection_name, filter=f'event_id == "{event_id}"')
        logger.info(f"Milvus 删除事件向量: {event_id}")

    # --------------------------------------------------
    # 异步公开接口
    # --------------------------------------------------

    async def insert_event_vector(self, event_id: str, embedding: List[float], summary_preview: str):
        await asyncio.to_thread(self._insert_event_vector_sync, event_id, embedding, summary_preview)

    async def search_similar_events(self, query_embedding: List[float], top_k: int = 10) -> List[dict]:
        return await asyncio.to_thread(self._search_similar_events_sync, query_embedding, top_k)

    async def delete_event_vector(self, event_id: str):
        await asyncio.to_thread(self._delete_event_vector_sync, event_id)
