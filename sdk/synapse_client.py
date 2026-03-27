"""
Synapse Memory Python SDK

提供简洁的 Python 接口封装，方便外部 Agent/LLM 接入
"""
import asyncio
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)


@dataclass
class ChunkInfo:
    """Chunk 信息"""
    chunk_id: str
    doc_id: str
    text_content: str
    section_name: Optional[str] = None
    section_index: Optional[int] = None
    paragraph_index: Optional[int] = None
    score: float = 0.0
    rank: int = 0


@dataclass
class SummaryInfo:
    """摘要信息"""
    summary_id: str
    doc_id: str
    summary_text: str
    summary_type: str
    score: float = 0.0


@dataclass
class MemoryPackage:
    """记忆包"""
    ranked_chunks: List[ChunkInfo]
    ranked_summaries: List[SummaryInfo]
    graph_context: Dict[str, Any]
    extra_chunk_ids: List[str]
    pending_archive_summary: Optional[str]
    topic_changed: bool
    topic_id: Optional[str]
    token_estimate: int
    usage: Dict[str, Any]


class SynapseClient:
    """
    Synapse Memory 客户端

    使用示例:
    ```python
    client = SynapseClient("http://localhost:8000")

    # 提交对话
    result = await client.submit_turn(
        session_id="my_session",
        user_message="红楼梦里贾宝玉是谁？",
        assistant_response="贾宝玉是《红楼梦》的主人公..."
    )

    # 使用检索结果
    for chunk in result.ranked_chunks:
        print(f"Chunk: {chunk.text_content[:100]}...")

    # 按需获取更多
    if result.extra_chunk_ids:
        more_chunks = await client.get_chunks_by_ids(result.extra_chunk_ids[:5])
    ```
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """
        初始化客户端

        Args:
            base_url: API 基础 URL
            api_key: 可选的 API Key
            timeout: 请求超时时间
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def _ensure_client(self) -> httpx.AsyncClient:
        """确保 HTTP 客户端存在"""
        if self._client is None:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    async def close(self):
        """关闭客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ========================================================
    # 核心接口
    # ========================================================

    async def submit_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_response: str,
        metadata: Optional[Dict[str, Any]] = None,
        max_chunks: int = 10,
        max_summaries: int = 5,
        min_similarity: float = 0.5,
        enable_adjacent_chunks: bool = False,
        adjacent_window: int = 2,
    ) -> MemoryPackage:
        """
        提交一轮对话

        这是最核心的接口，返回结构化的记忆包

        Args:
            session_id: Session ID
            user_message: 用户消息
            assistant_response: 助手回复（必填）
            metadata: 可选的元数据
            max_chunks: 返回的 chunk 数量
            max_summaries: 返回的摘要数量
            min_similarity: 最低相似度阈值
            enable_adjacent_chunks: 是否启用逆向召回
            adjacent_window: 逆向召回窗口大小

        Returns:
            MemoryPackage: 结构化的记忆包
        """
        client = await self._ensure_client()

        response = await client.post(
            "/submit_turn",
            json={
                "session_id": session_id,
                "user_message": user_message,
                "assistant_response": assistant_response,
                "metadata": metadata,
                "max_chunks": max_chunks,
                "max_summaries": max_summaries,
                "min_similarity": min_similarity,
                "enable_adjacent_chunks": enable_adjacent_chunks,
                "adjacent_window": adjacent_window,
            },
        )

        if response.status_code != 200:
            raise Exception(f"submit_turn 失败: {response.status_code} - {response.text}")

        data = response.json()

        # 解析响应
        return MemoryPackage(
            ranked_chunks=[
                ChunkInfo(
                    chunk_id=c["chunk_id"],
                    doc_id=c["doc_id"],
                    text_content=c["text_content"],
                    section_name=c.get("section_name"),
                    section_index=c.get("section_index"),
                    paragraph_index=c.get("paragraph_index"),
                    score=c.get("score", 0),
                    rank=c.get("rank", 0),
                )
                for c in data.get("ranked_chunks", [])
            ],
            ranked_summaries=[
                SummaryInfo(
                    summary_id=s["summary_id"],
                    doc_id=s["doc_id"],
                    summary_text=s["summary_text"],
                    summary_type=s["summary_type"],
                    score=s.get("score", 0),
                )
                for s in data.get("ranked_summaries", [])
            ],
            graph_context=data.get("graph_context", {}),
            extra_chunk_ids=data.get("extra_chunk_ids", []),
            pending_archive_summary=data.get("pending_archive_summary"),
            topic_changed=data.get("topic_changed", False),
            topic_id=data.get("topic_id"),
            token_estimate=data.get("token_estimate", 0),
            usage=data.get("usage", {}),
        )

    async def ingest_document(
        self,
        doc_id: str,
        doc_title: str,
        text_content: str,
        source_type: str = "article",
        source_path: Optional[str] = None,
        use_es: bool = False,
    ) -> Dict[str, Any]:
        """
        摄入文档

        Args:
            doc_id: 文档 ID
            doc_title: 文档标题
            text_content: 文档内容
            source_type: 来源类型
            source_path: 来源路径
            use_es: 是否使用 ES

        Returns:
            摄入结果
        """
        client = await self._ensure_client()

        response = await client.post(
            "/ingest_document",
            json={
                "doc_id": doc_id,
                "doc_title": doc_title,
                "text_content": text_content,
                "source_type": source_type,
                "source_path": source_path,
                "use_es": use_es,
            },
        )

        if response.status_code != 200:
            raise Exception(f"ingest_document 失败: {response.status_code} - {response.text}")

        return response.json()

    async def get_session_state(self, session_id: str) -> Dict[str, Any]:
        """
        获取 Session 状态

        Args:
            session_id: Session ID

        Returns:
            Session 状态信息
        """
        client = await self._ensure_client()

        response = await client.get(f"/session/{session_id}")

        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise Exception(f"get_session_state 失败: {response.status_code} - {response.text}")

        return response.json()

    async def get_chunks_by_ids(self, chunk_ids: List[str]) -> List[ChunkInfo]:
        """
        按 ID 批量获取 Chunk

        Args:
            chunk_ids: Chunk ID 列表

        Returns:
            Chunk 信息列表
        """
        client = await self._ensure_client()

        response = await client.post(
            "/chunks/by_ids",
            json={"chunk_ids": chunk_ids},
        )

        if response.status_code != 200:
            raise Exception(f"get_chunks_by_ids 失败: {response.status_code} - {response.text}")

        data = response.json()
        return [
            ChunkInfo(
                chunk_id=c["chunk_id"],
                doc_id=c["doc_id"],
                text_content=c["text_content"],
                section_name=c.get("section_name"),
                section_index=c.get("section_index"),
                paragraph_index=c.get("paragraph_index"),
            )
            for c in data.get("chunks", [])
        ]

    async def get_adjacent_chunks(
        self,
        chunk_id: str,
        window: int = 2
    ) -> List[ChunkInfo]:
        """
        逆向召回：获取相邻 Chunk

        Args:
            chunk_id: 中心 Chunk ID
            window: 前后各取几个 Chunk

        Returns:
            相邻 Chunk 列表
        """
        client = await self._ensure_client()

        response = await client.get(f"/chunks/{chunk_id}/adjacent", params={"window": window})

        if response.status_code != 200:
            raise Exception(f"get_adjacent_chunks 失败: {response.status_code} - {response.text}")

        data = response.json()
        return [
            ChunkInfo(
                chunk_id=c["chunk_id"],
                doc_id=c["doc_id"],
                text_content=c["text_content"],
                section_name=c.get("section_name"),
                section_index=c.get("section_index"),
            )
            for c in data.get("chunks", [])
        ]

    async def delete_topic(self, topic_id: str) -> bool:
        """
        删除话题

        Args:
            topic_id: 话题 ID

        Returns:
            是否成功
        """
        client = await self._ensure_client()

        response = await client.delete(f"/topic/{topic_id}")

        if response.status_code != 200:
            raise Exception(f"delete_topic 失败: {response.status_code} - {response.text}")

        return response.json().get("deleted", False)

    async def delete_session(self, session_id: str) -> bool:
        """
        删除 Session

        Args:
            session_id: Session ID

        Returns:
            是否成功
        """
        client = await self._ensure_client()

        response = await client.delete(f"/session/{session_id}")

        if response.status_code == 404:
            return False
        if response.status_code != 200:
            raise Exception(f"delete_session 失败: {response.status_code} - {response.text}")

        return response.json().get("deleted", False)

    async def start_new_topic(self, session_id: str) -> bool:
        """
        开始新话题

        Args:
            session_id: Session ID

        Returns:
            是否成功
        """
        client = await self._ensure_client()

        response = await client.post(f"/session/{session_id}/new_topic")

        if response.status_code != 200:
            raise Exception(f"start_new_topic 失败: {response.status_code} - {response.text}")

        return response.json().get("success", False)

    async def health_check(self) -> Dict[str, Any]:
        """
        健康检查

        Returns:
            健康状态
        """
        client = await self._ensure_client()
        response = await client.get("/")
        return response.json()

    async def get_stats(self) -> Dict[str, Any]:
        """
        获取系统统计

        Returns:
            统计信息
        """
        client = await self._ensure_client()
        response = await client.get("/stats")
        return response.json()


# ========================================================
# 便捷函数
# ========================================================

async def submit_turn(
    session_id: str,
    user_message: str,
    assistant_response: str,
    base_url: str = "http://localhost:8000",
    **kwargs
) -> MemoryPackage:
    """
    便捷函数：提交一轮对话

    Args:
        session_id: Session ID
        user_message: 用户消息
        assistant_response: 助手回复
        base_url: API 基础 URL
        **kwargs: 其他参数传递给 submit_turn

    Returns:
        MemoryPackage
    """
    async with SynapseClient(base_url) as client:
        return await client.submit_turn(
            session_id=session_id,
            user_message=user_message,
            assistant_response=assistant_response,
            **kwargs
        )


async def ingest_document(
    doc_id: str,
    doc_title: str,
    text_content: str,
    base_url: str = "http://localhost:8000",
    **kwargs
) -> Dict[str, Any]:
    """
    便捷函数：摄入文档
    """
    async with SynapseClient(base_url) as client:
        return await client.ingest_document(
            doc_id=doc_id,
            doc_title=doc_title,
            text_content=text_content,
            **kwargs
        )
