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

-- 索引
CREATE INDEX IF NOT EXISTS idx_conversation_event_id ON conversation_history(event_id);
CREATE INDEX IF NOT EXISTS idx_conversation_global_round ON conversation_history(global_round);
CREATE INDEX IF NOT EXISTS idx_current_context_event_id ON current_event_context(event_id);
CREATE INDEX IF NOT EXISTS idx_rolling_position ON rolling_summary_window(position);
"""
