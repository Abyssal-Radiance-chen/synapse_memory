"""
MemoryPackage 数据结构定义

Phase 4 核心数据模型
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class RetrievalConfig:
    """
    检索配置参数

    所有参数都有默认值，不设硬上限
    """
    # 基础层
    max_chunks: int = 10                    # Rerank 后返回的 chunk 数
    max_summaries: int = 5                  # 返回的摘要数
    token_budget: int = 8192                # Agent 检索的 token 预算
    min_similarity: float = 0.5             # 向量检索最低相似度阈值
    include_extra_ids: bool = True          # 是否返回候选 chunk_id 列表

    # Agent 增强层
    enable_agent_retrieval: bool = False    # 默认关
    agent_max_rounds: int = 5               # Agent 最多迭代轮数

    # 逆向召回
    enable_adjacent_chunks: bool = False    # 默认关
    adjacent_window: int = 2                # 前后各取几个 chunk

    # 图谱
    max_graph_entities: int = 20            # 返回的最大实体数
    max_graph_edges: int = 30               # 返回的最大边数


@dataclass
class ChunkInfo:
    """Chunk 信息"""
    chunk_id: str
    doc_id: str
    text_content: str
    section_name: Optional[str] = None
    section_index: Optional[int] = None
    paragraph_index: Optional[int] = None
    score: float = 0.0                      # 检索得分
    rank: int = 0                           # 排名

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "text_content": self.text_content,
            "section_name": self.section_name,
            "section_index": self.section_index,
            "paragraph_index": self.paragraph_index,
            "score": self.score,
            "rank": self.rank,
        }


@dataclass
class SummaryInfo:
    """摘要信息"""
    summary_id: str
    doc_id: str
    summary_text: str
    summary_type: str
    source_chunks: List[str] = field(default_factory=list)
    score: float = 0.0
    rank: int = 0

    def to_dict(self) -> dict:
        return {
            "summary_id": self.summary_id,
            "doc_id": self.doc_id,
            "summary_text": self.summary_text,
            "summary_type": self.summary_type,
            "source_chunks": self.source_chunks,
            "score": self.score,
            "rank": self.rank,
        }


@dataclass
class GraphContext:
    """图谱上下文（L1 关系图）"""
    entities: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entities": self.entities,
            "edges": self.edges,
        }


@dataclass
class SessionStateInfo:
    """Session 状态信息（用于返回）"""
    session_id: str
    status: str                             # active, topic_ended, archived
    turn_count: int
    topic_id: Optional[str] = None
    created_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "turn_count": self.turn_count,
            "topic_id": self.topic_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
        }


@dataclass
class UsageStats:
    """使用统计"""
    retrieval_time_ms: float = 0.0          # 检索耗时
    rerank_time_ms: float = 0.0             # Rerank 耗时
    total_time_ms: float = 0.0              # 总耗时
    tokens_used: int = 0                    # Token 使用量

    def to_dict(self) -> dict:
        return {
            "retrieval_time_ms": self.retrieval_time_ms,
            "rerank_time_ms": self.rerank_time_ms,
            "total_time_ms": self.total_time_ms,
            "tokens_used": self.tokens_used,
        }


@dataclass
class MemoryPackage:
    """
    记忆包 - submit_turn 的返回结构

    包含检索结果、状态信息、统计信息
    """
    # 核心检索结果
    ranked_chunks: List[ChunkInfo] = field(default_factory=list)       # Rerank 后的 chunk（含完整原文）
    ranked_summaries: List[SummaryInfo] = field(default_factory=list)  # 去重后的摘要
    graph_context: GraphContext = field(default_factory=GraphContext)  # L1 关系图
    extra_chunk_ids: List[str] = field(default_factory=list)           # 候选 chunk_id（不含原文）

    # 话题相关
    pending_archive_summary: Optional[str] = None   # 上一轮归档话题的摘要
    topic_changed: bool = False                     # 是否发生话题切换
    topic_id: Optional[str] = None                  # 话题结束时生成的 ID

    # 估算与统计
    token_estimate: int = 0                         # 核心层估算 token 数
    session_state: Optional[SessionStateInfo] = None  # 当前 session 状态
    usage: UsageStats = field(default_factory=UsageStats)  # token + 耗时统计

    def to_dict(self) -> dict:
        return {
            "ranked_chunks": [c.to_dict() for c in self.ranked_chunks],
            "ranked_summaries": [s.to_dict() for s in self.ranked_summaries],
            "graph_context": self.graph_context.to_dict(),
            "extra_chunk_ids": self.extra_chunk_ids,
            "pending_archive_summary": self.pending_archive_summary,
            "topic_changed": self.topic_changed,
            "topic_id": self.topic_id,
            "token_estimate": self.token_estimate,
            "session_state": self.session_state.to_dict() if self.session_state else None,
            "usage": self.usage.to_dict(),
        }


# --------------------------------------------------
# 对话数据结构
# --------------------------------------------------

@dataclass
class TurnInput:
    """submit_turn 的输入"""
    session_id: str
    user_message: str
    assistant_response: str                              # 必填
    metadata: Optional[Dict[str, Any]] = None

    # 可选配置覆盖
    config: Optional[RetrievalConfig] = None


@dataclass
class TopicArchiveInfo:
    """话题归档信息"""
    topic_id: str
    session_id: str
    conversation_id: str                         # 响应对话 ID
    timestamp: datetime
    summary: str
    turn_count: int
    entities_extracted: int = 0
    chunks_indexed: int = 0

    def to_dict(self) -> dict:
        return {
            "topic_id": self.topic_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "timestamp": self.timestamp.isoformat(),
            "summary": self.summary,
            "turn_count": self.turn_count,
            "entities_extracted": self.entities_extracted,
            "chunks_indexed": self.chunks_indexed,
        }
