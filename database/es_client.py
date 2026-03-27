"""
Elasticsearch 全文检索客户端（异步兼容）
用于 Chunk 和 Summary 的全文检索
"""
import asyncio
import logging
import urllib3
from typing import List, Optional, Dict, Any

import requests

import config

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class ESClient:
    """Elasticsearch 全文检索客户端"""

    def __init__(self):
        self.base_url = config.ES_URL.rstrip("/")
        self.auth = (config.ES_USER, config.ES_PASSWORD)
        self.headers = {
            "Content-Type": "application/json",
            "X-Gateway-Key": config.ES_API_KEY,
        }
        self.chunks_index = config.ES_CHUNKS_INDEX
        self.summaries_index = config.ES_SUMMARIES_INDEX

    # --------------------------------------------------
    # 索引管理
    # --------------------------------------------------

    def create_chunks_index(self) -> bool:
        """创建 chunks 索引"""
        url = f"{self.base_url}/{self.chunks_index}"
        
        # 先检查索引是否存在
        try:
            resp = requests.head(url, auth=self.auth, headers=self.headers, verify=False, timeout=10)
            if resp.status_code == 200:
                logger.info(f"ES 索引 '{self.chunks_index}' 已存在")
                return True
        except Exception:
            pass

        # 创建索引
        mapping = {
            "mappings": {
                "properties": {
                    "chunk_id": {"type": "keyword"},
                    "doc_id": {"type": "keyword"},
                    "text_content": {
                        "type": "text",
                        "analyzer": "standard",
                        "search_analyzer": "standard"
                    },
                    "section_name": {"type": "text", "analyzer": "standard"},
                    "section_hierarchy": {"type": "keyword"},
                    "created_at": {"type": "date"}
                }
            }
        }

        try:
            resp = requests.put(url, json=mapping, auth=self.auth, headers=self.headers, verify=False, timeout=30)
            if resp.status_code in (200, 201):
                logger.info(f"✅ ES 索引 '{self.chunks_index}' 创建成功")
                return True
            else:
                logger.error(f"创建 ES 索引失败: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            logger.error(f"创建 ES 索引异常: {e}")
            return False

    def create_summaries_index(self) -> bool:
        """创建 summaries 索引"""
        url = f"{self.base_url}/{self.summaries_index}"
        
        # 先检查索引是否存在
        try:
            resp = requests.head(url, auth=self.auth, headers=self.headers, verify=False, timeout=10)
            if resp.status_code == 200:
                logger.info(f"ES 索引 '{self.summaries_index}' 已存在")
                return True
        except Exception:
            pass

        # 创建索引
        mapping = {
            "mappings": {
                "properties": {
                    "summary_id": {"type": "integer"},
                    "doc_id": {"type": "keyword"},
                    "summary_text": {
                        "type": "text",
                        "analyzer": "standard",
                        "search_analyzer": "standard"
                    },
                    "summary_type": {"type": "keyword"},
                    "created_at": {"type": "date"}
                }
            }
        }

        try:
            resp = requests.put(url, json=mapping, auth=self.auth, headers=self.headers, verify=False, timeout=30)
            if resp.status_code in (200, 201):
                logger.info(f"✅ ES 索引 '{self.summaries_index}' 创建成功")
                return True
            else:
                logger.error(f"创建 ES 索引失败: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            logger.error(f"创建 ES 索引异常: {e}")
            return False

    def init_indices(self):
        """初始化所有索引"""
        self.create_chunks_index()
        self.create_summaries_index()

    # --------------------------------------------------
    # 异步索引管理（用于测试）
    # --------------------------------------------------

    async def create_chunks_index_async(self) -> bool:
        """异步创建 chunks 索引"""
        return await asyncio.to_thread(self.create_chunks_index)

    async def create_summaries_index_async(self) -> bool:
        """异步创建 summaries 索引"""
        return await asyncio.to_thread(self.create_summaries_index)

    # --------------------------------------------------
    # 文档操作
    # --------------------------------------------------

    def _index_document_sync(self, index: str, doc_id: str, doc: Dict[str, Any]) -> bool:
        """索引单个文档"""
        url = f"{self.base_url}/{index}/_doc/{doc_id}"
        try:
            resp = requests.put(url, json=doc, auth=self.auth, headers=self.headers, verify=False, timeout=30)
            return resp.status_code in (200, 201)
        except Exception as e:
            logger.error(f"ES 索引文档失败: {e}")
            return False

    def _bulk_index_sync(self, index: str, docs: List[Dict[str, Any]]) -> bool:
        """批量索引文档"""
        import json
        url = f"{self.base_url}/{index}/_bulk"
        bulk_body = ""
        for doc in docs:
            doc_id = doc.get("chunk_id") or doc.get("summary_id") or doc.get("id")
            if doc_id:
                bulk_body += f'{{"index":{{"_id":"{doc_id}"}}}}\n'
                bulk_body += f'{json.dumps(doc, ensure_ascii=False)}\n'

        if not bulk_body:
            return False

        try:
            resp = requests.post(
                url,
                data=bulk_body.encode('utf-8'),
                auth=self.auth,
                headers={"Content-Type": "application/x-ndjson", "X-Gateway-Key": self.headers.get("X-Gateway-Key", "")},
                verify=False,
                timeout=60
            )
            if resp.status_code != 200:
                logger.error(f"ES 批量索引失败: {resp.status_code} - {resp.text[:500]}")
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"ES 批量索引失败: {e}")
            return False

    def _delete_document_sync(self, index: str, doc_id: str) -> bool:
        """删除单个文档"""
        url = f"{self.base_url}/{index}/_doc/{doc_id}"
        try:
            resp = requests.delete(url, auth=self.auth, headers=self.headers, verify=False, timeout=30)
            return resp.status_code in (200, 404)
        except Exception as e:
            logger.error(f"ES 删除文档失败: {e}")
            return False

    # --------------------------------------------------
    # 搜索操作
    # --------------------------------------------------

    def _search_sync(self, index: str, query: str, top_k: int = 10, filters: Optional[Dict] = None) -> List[Dict]:
        """全文搜索"""
        url = f"{self.base_url}/{index}/_search"
        
        es_query = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["text_content^2", "section_name", "summary_text^1.5"],
                                "type": "best_fields"
                            }
                        }
                    ]
                }
            }
        }
        
        if filters:
            filter_clauses = []
            for key, value in filters.items():
                filter_clauses.append({"term": {key: value}})
            if filter_clauses:
                es_query["query"]["bool"]["filter"] = filter_clauses

        try:
            resp = requests.post(url, json=es_query, auth=self.auth, headers=self.headers, verify=False, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                hits = result.get("hits", {}).get("hits", [])
                return [
                    {
                        "id": hit["_id"],
                        "score": hit["_score"],
                        **hit["_source"]
                    }
                    for hit in hits
                ]
            else:
                logger.error(f"ES 搜索失败: {resp.status_code}")
                return []
        except Exception as e:
            logger.error(f"ES 搜索异常: {e}")
            return []

    def _bm25_search_sync(self, index: str, query: str, top_k: int = 10) -> List[Dict]:
        """BM25 全文搜索（用于 RRF 融合）"""
        return self._search_sync(index, query, top_k)

    # --------------------------------------------------
    # 异步公开接口
    # --------------------------------------------------

    async def index_chunk(self, chunk_id: str, doc: Dict[str, Any]) -> bool:
        """索引 Chunk 文档"""
        return await asyncio.to_thread(self._index_document_sync, self.chunks_index, chunk_id, doc)

    async def index_summary(self, summary_id: str, doc: Dict[str, Any]) -> bool:
        """索引 Summary 文档"""
        return await asyncio.to_thread(self._index_document_sync, self.summaries_index, summary_id, doc)

    async def bulk_index_chunks(self, docs: List[Dict[str, Any]]) -> bool:
        """批量索引 Chunks"""
        return await asyncio.to_thread(self._bulk_index_sync, self.chunks_index, docs)

    async def bulk_index_summaries(self, docs: List[Dict[str, Any]]) -> bool:
        """批量索引 Summaries"""
        return await asyncio.to_thread(self._bulk_index_sync, self.summaries_index, docs)

    async def delete_chunk(self, chunk_id: str) -> bool:
        """删除 Chunk 文档"""
        return await asyncio.to_thread(self._delete_document_sync, self.chunks_index, chunk_id)

    async def delete_summary(self, summary_id: str) -> bool:
        """删除 Summary 文档"""
        return await asyncio.to_thread(self._delete_document_sync, self.summaries_index, summary_id)

    async def search_chunks(self, query: str, top_k: int = 10, filters: Optional[Dict] = None) -> List[Dict]:
        """搜索 Chunks"""
        return await asyncio.to_thread(self._search_sync, self.chunks_index, query, top_k, filters)

    async def search_summaries(self, query: str, top_k: int = 10, filters: Optional[Dict] = None) -> List[Dict]:
        """搜索 Summaries"""
        return await asyncio.to_thread(self._search_sync, self.summaries_index, query, top_k, filters)

    async def bm25_search_chunks(self, query: str, top_k: int = 10) -> List[Dict]:
        """BM25 搜索 Chunks（用于 RRF）"""
        return await asyncio.to_thread(self._bm25_search_sync, self.chunks_index, query, top_k)

    async def bm25_search_summaries(self, query: str, top_k: int = 10) -> List[Dict]:
        """BM25 搜索 Summaries（用于 RRF）"""
        return await asyncio.to_thread(self._bm25_search_sync, self.summaries_index, query, top_k)
