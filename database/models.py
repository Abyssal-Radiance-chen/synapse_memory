"""
数据模型定义
PostgreSQL 表结构 & Pydantic 数据模型
"""
from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field


# =============================================
# Pydantic 请求/响应模型
# =============================================

class ChatRequest(BaseModel):
    """对话请求 - OpenAI 标准格式"""
    model: str = "default"
    messages: List[dict] = Field(..., description="对话消息列表")
    stream: bool = True


class ChatMessage(BaseModel):
    """单条消息"""
    role: str
    content: str


# =============================================
# 人物志 CRUD 模型
# =============================================

class CharacterCreate(BaseModel):
    """创建人物志"""
    name: str
    relationship: Optional[str] = None
    gender: Optional[str] = None
    hobbies: Optional[str] = None
    basic_info: Optional[dict] = None
    evaluation: Optional[str] = None
    related_events: Optional[List[str]] = []


class CharacterUpdate(BaseModel):
    """更新人物志"""
    name: Optional[str] = None
    relationship: Optional[str] = None
    gender: Optional[str] = None
    hobbies: Optional[str] = None
    basic_info: Optional[dict] = None
    evaluation: Optional[str] = None
    related_events: Optional[List[str]] = None


class CharacterResponse(BaseModel):
    """人物志响应"""
    id: int
    name: str
    relationship: Optional[str] = None
    gender: Optional[str] = None
    hobbies: Optional[str] = None
    basic_info: Optional[dict] = None
    evaluation: Optional[str] = None
    related_events: Optional[List[str]] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# =============================================
# 内部数据模型
# =============================================

class EventSummary(BaseModel):
    """事件摘要"""
    event_id: str
    summary_text: str
    event_date: str
    weather: str
    start_round: int
    end_round: int
    round_count: int
    created_at: Optional[datetime] = None


class ConversationRound(BaseModel):
    """单轮对话"""
    message_id: str
    event_id: str
    round_in_event: int
    global_round: int
    user_message: str
    assistant_message: str
    created_at: Optional[datetime] = None


class CurrentEventContext(BaseModel):
    """当前事件上下文中的一轮"""
    event_id: str
    round_in_event: int
    user_message: str
    assistant_message: str


class RollingSummary(BaseModel):
    """滚动摘要窗口中的一条"""
    event_id: str
    summary_text: str
    event_date: str
    position: int


class SystemState(BaseModel):
    """系统状态"""
    current_event_id: str
    current_event_round: int
    global_round: int
    event_start_time: Optional[str] = None
    event_start_weather: Optional[str] = None


class MemoryRetrievalResult(BaseModel):
    """记忆拉取结果"""
    relevant_summaries: List[str] = []
    full_scene: Optional[str] = None
    character_info: Optional[str] = None
    total_tokens: int = 0


# =============================================
# Phase 0: 文档和分块模型
# =============================================

class DocumentCreate(BaseModel):
    """创建文档"""
    doc_id: str
    doc_title: str
    source_type: Optional[str] = None  # file, url, text
    source_path: Optional[str] = None
    metadata: Optional[dict] = None


class SummaryCreate(BaseModel):
    """创建摘要"""
    summary_id: str
    doc_id: str
    summary_type: str  # scene_summary, rolling_summary, event_summary
    summary_text: str
    source_chunks: Optional[List[str]] = None
    time_info: Optional[str] = None  # 例如: "2026-03-24"
    metadata: Optional[dict] = None


class SummaryResponse(BaseModel):
    """摘要响应"""
    id: int
    summary_id: str
    doc_id: str
    summary_type: str
    summary_text: str
    source_chunks: Optional[List[str]] = None
    time_info: Optional[str] = None
    es_indexed: bool = False
    created_at: Optional[datetime] = None


class DocumentResponse(BaseModel):
    """文档响应"""
    id: int
    doc_id: str
    doc_title: str
    source_type: Optional[str] = None
    source_path: Optional[str] = None
    metadata: Optional[dict] = None
    chunk_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ChunkCreate(BaseModel):
    """创建分块"""
    chunk_id: str
    doc_id: str
    text_content: str
    section_name: Optional[str] = None
    section_hierarchy: Optional[List[str]] = None
    section_index: Optional[int] = None
    paragraph_index: Optional[int] = None
    sub_chunk_index: Optional[int] = None
    char_count: Optional[int] = None


class ChunkResponse(BaseModel):
    """分块响应"""
    id: int
    chunk_id: str
    doc_id: str
    text_content: str
    section_name: Optional[str] = None
    section_hierarchy: Optional[List[str]] = None
    section_index: Optional[int] = None
    paragraph_index: Optional[int] = None
    sub_chunk_index: Optional[int] = None
    char_count: Optional[int] = None
    vector_stored: bool = False
    es_indexed: bool = False
    created_at: Optional[datetime] = None


class EntityCreate(BaseModel):
    """创建实体"""
    name: str
    entity_type: str
    aliases: Optional[List[str]] = None
    description: Optional[str] = None
    metadata: Optional[dict] = None


class EntityResponse(BaseModel):
    """实体响应"""
    id: int
    name: str
    entity_type: str
    aliases: Optional[List[str]] = None
    description: Optional[str] = None
    metadata: Optional[dict] = None
    mention_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RelationshipCreate(BaseModel):
    """创建关系"""
    subject_entity: str
    object_entity: str
    relation_type: str
    predicate: Optional[str] = None
    properties: Optional[dict] = None
    chunk_id: Optional[str] = None  # 来源 chunk，便于溯源
    doc_id: Optional[str] = None    # 来源文档，便于按文档查找关系网


class RelationshipResponse(BaseModel):
    """关系响应"""
    id: int
    subject_entity: str
    object_entity: str
    relation_type: str
    predicate: Optional[str] = None
    properties: Optional[dict] = None
    weight: float = 1.0
    chunk_id: Optional[str] = None
    doc_id: Optional[str] = None
    created_at: Optional[datetime] = None


# =============================================
# PostgreSQL 建表 SQL
# =============================================

CREATE_TABLES_SQL = """
-- 事件摘要表
CREATE TABLE IF NOT EXISTS event_summaries (
    event_id VARCHAR(50) PRIMARY KEY,
    summary_text TEXT NOT NULL,
    event_date VARCHAR(50),
    weather VARCHAR(100),
    start_round INT,
    end_round INT,
    round_count INT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 对话历史表
CREATE TABLE IF NOT EXISTS conversation_history (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(100) UNIQUE NOT NULL,
    event_id VARCHAR(50) NOT NULL,
    round_in_event INT NOT NULL,
    global_round INT NOT NULL,
    user_message TEXT NOT NULL,
    assistant_message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 人物志表
CREATE TABLE IF NOT EXISTS character_profiles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    relationship VARCHAR(100),
    gender VARCHAR(10),
    hobbies TEXT,
    basic_info JSONB DEFAULT '{}',
    evaluation TEXT,
    related_events JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 当前事件上下文表
CREATE TABLE IF NOT EXISTS current_event_context (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(50) NOT NULL,
    round_in_event INT NOT NULL,
    user_message TEXT NOT NULL,
    assistant_message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 滚动摘要窗口表
CREATE TABLE IF NOT EXISTS rolling_summary_window (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(50) NOT NULL,
    summary_text TEXT NOT NULL,
    event_date VARCHAR(50),
    position INT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 系统状态表
CREATE TABLE IF NOT EXISTS system_state (
    id SERIAL PRIMARY KEY,
    current_event_id VARCHAR(50),
    current_event_round INT DEFAULT 0,
    global_round INT DEFAULT 0,
    event_start_time VARCHAR(100),
    event_start_weather VARCHAR(100),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- =============================================
-- Phase 0: 文档和分块表
-- =============================================

-- 文档表
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    doc_id VARCHAR(255) UNIQUE NOT NULL,
    doc_title VARCHAR(500) NOT NULL,
    source_type VARCHAR(50),
    source_path TEXT,
    metadata JSONB DEFAULT '{}',
    chunk_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 分块表
CREATE TABLE IF NOT EXISTS chunks (
    id SERIAL PRIMARY KEY,
    chunk_id VARCHAR(255) UNIQUE NOT NULL,
    doc_id VARCHAR(255) NOT NULL,
    text_content TEXT NOT NULL,
    section_name VARCHAR(500),
    section_hierarchy JSONB DEFAULT '[]',
    section_index INT,
    paragraph_index INT,
    sub_chunk_index INT DEFAULT 0,
    char_count INT,
    vector_stored BOOLEAN DEFAULT FALSE,
    es_indexed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 摘要表
CREATE TABLE IF NOT EXISTS summaries (
    id SERIAL PRIMARY KEY,
    summary_id VARCHAR(255) UNIQUE NOT NULL,
    doc_id VARCHAR(255) NOT NULL,
    summary_type VARCHAR(50) NOT NULL,  -- scene_summary, rolling_summary, event_summary
    summary_text TEXT NOT NULL,
    source_chunks JSONB DEFAULT '[]',
    time_info VARCHAR(100),
    metadata JSONB DEFAULT '{}',
    es_indexed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 实体表（与 Neo4j 同步）
CREATE TABLE IF NOT EXISTS entities (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    aliases JSONB DEFAULT '[]',
    description TEXT,
    metadata JSONB DEFAULT '{}',
    mention_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 实体关系表（与 Neo4j 同步）
-- 添加 chunk_id 和 doc_id 索引，便于溯源文档和通过文档查找关系网
CREATE TABLE IF NOT EXISTS entity_relationships (
    id SERIAL PRIMARY KEY,
    subject_entity VARCHAR(255) NOT NULL,
    object_entity VARCHAR(255) NOT NULL,
    relation_type VARCHAR(100) NOT NULL,
    predicate VARCHAR(255),
    properties JSONB DEFAULT '{}',
    weight FLOAT DEFAULT 1.0,
    chunk_id VARCHAR(255),  -- 来源 chunk，便于溯源
    doc_id VARCHAR(255),    -- 来源文档，便于按文档查找关系网
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(subject_entity, object_entity, relation_type, chunk_id)
);

-- Chunk-Entity 关联表
CREATE TABLE IF NOT EXISTS chunk_entities (
    id SERIAL PRIMARY KEY,
    chunk_id VARCHAR(255) NOT NULL,
    entity_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(chunk_id, entity_id)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_conversation_event_id ON conversation_history(event_id);
CREATE INDEX IF NOT EXISTS idx_conversation_global_round ON conversation_history(global_round);
CREATE INDEX IF NOT EXISTS idx_current_context_event_id ON current_event_context(event_id);
CREATE INDEX IF NOT EXISTS idx_rolling_position ON rolling_summary_window(position);

-- Phase 0 索引
CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_section_index ON chunks(doc_id, section_index);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entity_rels_subject ON entity_relationships(subject_entity);
CREATE INDEX IF NOT EXISTS idx_entity_rels_object ON entity_relationships(object_entity);
CREATE INDEX IF NOT EXISTS idx_entity_rels_chunk ON entity_relationships(chunk_id);  -- 溯源 chunk
CREATE INDEX IF NOT EXISTS idx_entity_rels_doc ON entity_relationships(doc_id);      -- 按文档查找关系网
CREATE INDEX IF NOT EXISTS idx_chunk_entities_chunk ON chunk_entities(chunk_id);
CREATE INDEX IF NOT EXISTS idx_chunk_entities_entity ON chunk_entities(entity_id);
"""
