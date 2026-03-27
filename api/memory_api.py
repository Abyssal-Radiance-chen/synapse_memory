"""
REST API 层

Phase 5: 对外暴露 REST 接口
- submit_turn（核心交互）
- ingest_document（文档摄入）
- get_session_state
- get_chunks_by_ids
- delete_topic
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from services.memory_service import MemoryService
from services.memory_package import (
    RetrievalConfig, MemoryPackage, ChunkInfo, SummaryInfo,
    GraphContext, SessionStateInfo, UsageStats
)
from services.session_manager import SessionManager
from services.ingestion_pipeline import IngestionPipeline
from database.pg_client import PGClient

logger = logging.getLogger(__name__)


# ============================================================
# Request/Response Models
# ============================================================

class SubmitTurnRequest(BaseModel):
    """submit_turn 请求"""
    session_id: str = Field(..., description="Session ID")
    user_message: str = Field(..., description="用户消息")
    assistant_response: str = Field(..., description="助手回复（必填）")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="额外元数据")

    # 检索配置覆盖
    max_chunks: Optional[int] = Field(default=10, ge=10, description="返回的 chunk 数")
    max_summaries: Optional[int] = Field(default=5, ge=5, description="返回的摘要数")
    min_similarity: Optional[float] = Field(default=0.5, ge=0.5, description="最低相似度阈值")
    enable_adjacent_chunks: Optional[bool] = Field(default=False, description="是否启用逆向召回")
    adjacent_window: Optional[int] = Field(default=2, ge=2, description="逆向召回窗口大小")


class SubmitTurnResponse(BaseModel):
    """submit_turn 响应"""
    ranked_chunks: List[Dict[str, Any]]
    ranked_summaries: List[Dict[str, Any]]
    graph_context: Dict[str, Any]
    extra_chunk_ids: List[str]
    pending_archive_summary: Optional[str]
    topic_changed: bool
    topic_id: Optional[str]
    token_estimate: int
    session_state: Optional[Dict[str, Any]]
    usage: Dict[str, Any]


class IngestDocumentRequest(BaseModel):
    """文档摄入请求"""
    doc_id: str = Field(..., description="文档 ID")
    doc_title: str = Field(..., description="文档标题")
    text_content: str = Field(..., description="文档内容")
    source_type: Optional[str] = Field(default="article", description="来源类型")
    source_path: Optional[str] = Field(default=None, description="来源路径")
    use_es: Optional[bool] = Field(default=False, description="是否使用 ES")

    # 可选：分块配置
    enable_triple_extraction: Optional[bool] = Field(default=True, description="是否抽取三元组")


class IngestDocumentResponse(BaseModel):
    """文档摄入响应"""
    doc_id: str
    chunk_count: int
    triple_count: int
    summary_count: int
    message: str


class GetChunksByIdsRequest(BaseModel):
    """按 ID 获取 Chunk 请求"""
    chunk_ids: List[str] = Field(..., description="Chunk ID 列表")


class GetChunksByIdsResponse(BaseModel):
    """按 ID 获取 Chunk 响应"""
    chunks: List[Dict[str, Any]]
    total: int


class SessionStateResponse(BaseModel):
    """Session 状态响应"""
    session_id: str
    status: str
    turn_count: int
    topic_id: Optional[str]
    created_at: Optional[str]
    last_activity: Optional[str]
    pending_archive_summary: Optional[str]


class DeleteTopicResponse(BaseModel):
    """删除话题响应"""
    topic_id: str
    deleted: bool
    message: str


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    version: str
    timestamp: str
    components: Dict[str, str]


# ============================================================
# FastAPI Application
# ============================================================

app = FastAPI(
    title="Synapse Memory API",
    description="AI Memory System - 话题级对话记忆检索服务",
    version="1.0.0",
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 全局服务实例
_memory_service: Optional[MemoryService] = None
_session_manager: Optional[SessionManager] = None
_pg_client: Optional[PGClient] = None


def get_memory_service() -> MemoryService:
    """获取 MemoryService 单例"""
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service


def get_session_manager() -> SessionManager:
    """获取 SessionManager 单例"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


def get_pg_client() -> PGClient:
    """获取 PGClient 单例"""
    global _pg_client
    if _pg_client is None:
        _pg_client = PGClient()
        _pg_client.connect()
    return _pg_client


@app.on_event("startup")
async def startup_event():
    """应用启动时初始化"""
    logger.info("Synapse Memory API 启动中...")
    # 预初始化服务
    get_session_manager()
    logger.info("Synapse Memory API 启动完成")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时清理"""
    logger.info("Synapse Memory API 关闭中...")
    global _memory_service, _pg_client
    if _memory_service:
        _memory_service.close()
    if _pg_client:
        _pg_client.close()
    logger.info("Synapse Memory API 关闭完成")


# ============================================================
# API Endpoints
# ============================================================

@app.get("/", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        timestamp=datetime.now().isoformat(),
        components={
            "session_manager": "ok",
            "memory_service": "ok",
            "pg_client": "ok",
        }
    )


@app.get("/stats")
async def get_stats():
    """获取系统统计信息"""
    sm = get_session_manager()
    return sm.get_stats()


# ------------------------------------------------------------
# 核心接口: submit_turn
# ------------------------------------------------------------

@app.post("/submit_turn", response_model=SubmitTurnResponse)
async def submit_turn(request: SubmitTurnRequest):
    """
    核心交互接口

    提交一轮对话，返回记忆包：
    - 检索相关 Chunks 和 Summaries
    - 判断话题是否结束
    - 话题结束时触发异步归档
    """
    try:
        # 构建检索配置
        config = RetrievalConfig(
            max_chunks=request.max_chunks or 10,
            max_summaries=request.max_summaries or 5,
            min_similarity=request.min_similarity or 0.5,
            enable_adjacent_chunks=request.enable_adjacent_chunks or False,
            adjacent_window=request.adjacent_window or 2,
        )

        # 调用 MemoryService
        service = get_memory_service()
        result = await service.submit_turn(
            session_id=request.session_id,
            user_message=request.user_message,
            assistant_response=request.assistant_response,
            metadata=request.metadata,
            config=config,
        )

        # 构建响应
        return SubmitTurnResponse(
            ranked_chunks=[{
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "text_content": c.text_content,
                "section_name": c.section_name,
                "score": c.score,
                "rank": c.rank,
            } for c in result.ranked_chunks],
            ranked_summaries=[{
                "summary_id": s.summary_id,
                "doc_id": s.doc_id,
                "summary_text": s.summary_text,
                "summary_type": s.summary_type,
                "score": s.score,
            } for s in result.ranked_summaries],
            graph_context=result.graph_context.to_dict() if result.graph_context else {},
            extra_chunk_ids=result.extra_chunk_ids,
            pending_archive_summary=result.pending_archive_summary,
            topic_changed=result.topic_changed,
            topic_id=result.topic_id,
            token_estimate=result.token_estimate,
            session_state=result.session_state.to_dict() if result.session_state else None,
            usage=result.usage.to_dict() if result.usage else {},
        )

    except ConnectionError as e:
        logger.error(f"连接错误: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"submit_turn 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------
# 文档摄入
# ------------------------------------------------------------

@app.post("/ingest_document", response_model=IngestDocumentResponse)
async def ingest_document(request: IngestDocumentRequest):
    """
    文档摄入接口

    将文档切分为 Chunk，建立向量索引和知识图谱
    """
    try:
        pipeline = IngestionPipeline()

        result = await pipeline.ingest_document(
            text=request.text_content,
            doc_id=request.doc_id,
            doc_title=request.doc_title,
            source_type=request.source_type or "article",
            source_path=request.source_path,
            use_es=request.use_es or False,
        )

        pipeline.close()

        return IngestDocumentResponse(
            doc_id=result["doc_id"],
            chunk_count=result["chunk_count"],
            triple_count=result.get("triple_count", 0),
            summary_count=result.get("summary_count", 0),
            message="文档摄入成功",
        )

    except Exception as e:
        logger.error(f"文档摄入失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------
# Session 状态查询
# ------------------------------------------------------------

@app.get("/session/{session_id}", response_model=SessionStateResponse)
async def get_session_state(session_id: str):
    """获取 Session 状态"""
    sm = get_session_manager()
    session = sm.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail=f"Session 不存在: {session_id}")

    return SessionStateResponse(
        session_id=session.session_id,
        status=session.status,
        turn_count=len(session.turns),
        topic_id=session.topic_id,
        created_at=session.created_at.isoformat() if session.created_at else None,
        last_activity=session.last_activity.isoformat() if session.last_activity else None,
        pending_archive_summary=session.pending_archive_summary,
    )


# ------------------------------------------------------------
# 按 ID 获取 Chunk
# ------------------------------------------------------------

@app.post("/chunks/by_ids", response_model=GetChunksByIdsResponse)
async def get_chunks_by_ids(request: GetChunksByIdsRequest):
    """
    按 ID 批量获取 Chunk

    用于按需拉取额外的 Chunk 内容
    """
    try:
        service = get_memory_service()
        chunks = await service.get_chunks_by_ids(request.chunk_ids)

        return GetChunksByIdsResponse(
            chunks=[{
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "text_content": c.text_content,
                "section_name": c.section_name,
                "section_index": c.section_index,
                "paragraph_index": c.paragraph_index,
            } for c in chunks],
            total=len(chunks),
        )

    except Exception as e:
        logger.error(f"获取 Chunk 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------
# 逆向召回
# ------------------------------------------------------------

@app.get("/chunks/{chunk_id}/adjacent")
async def get_adjacent_chunks(chunk_id: str, window: int = 2):
    """
    逆向召回：获取相邻 Chunk

    Args:
        chunk_id: 中心 Chunk ID
        window: 前后各取几个 Chunk
    """
    try:
        service = get_memory_service()
        chunks = await service.get_adjacent_chunks(chunk_id, window=window)

        return {
            "chunks": [{
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "text_content": c.text_content,
                "section_name": c.section_name,
                "section_index": c.section_index,
            } for c in chunks],
            "total": len(chunks),
        }

    except Exception as e:
        logger.error(f"获取相邻 Chunk 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------
# 删除话题
# ------------------------------------------------------------

@app.delete("/topic/{topic_id}", response_model=DeleteTopicResponse)
async def delete_topic(topic_id: str):
    """
    删除话题

    删除指定话题的所有数据：
    - Session 缓存
    - 对话 Chunks
    - 摘要
    - 图谱节点
    """
    try:
        # 1. 从 Session 缓存删除
        sm = get_session_manager()
        deleted_session = sm.delete_topic(topic_id)

        # 2. 从 PostgreSQL 删除对话 Chunks
        pg = get_pg_client()
        # TODO: 实现 delete_chunks_by_topic

        return DeleteTopicResponse(
            topic_id=topic_id,
            deleted=True,
            message=f"话题 {topic_id} 已删除",
        )

    except Exception as e:
        logger.error(f"删除话题失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------
# Session 管理
# ------------------------------------------------------------

@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """删除 Session"""
    sm = get_session_manager()
    if sm.delete_session(session_id):
        return {"deleted": True, "message": f"Session {session_id} 已删除"}
    raise HTTPException(status_code=404, detail=f"Session 不存在: {session_id}")


@app.post("/session/{session_id}/new_topic")
async def start_new_topic(session_id: str):
    """开始新话题（保留 Session）"""
    sm = get_session_manager()
    if sm.start_new_topic(session_id):
        return {"success": True, "message": f"Session {session_id} 开始新话题"}
    raise HTTPException(status_code=404, detail=f"Session 不存在: {session_id}")


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
