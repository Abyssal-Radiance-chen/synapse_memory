"""
Session 管理服务（无 Redis 版本）

使用内存缓存 + PostgreSQL 持久化
"""
import asyncio
import logging
import uuid
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import threading

logger = logging.getLogger(__name__)


@dataclass
class ConversationTurn:
    """一轮对话"""
    turn_index: int
    user_message: str
    assistant_response: str
    timestamp: datetime = field(default_factory=datetime.now)
    turn_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict:
        return {
            "turn_index": self.turn_index,
            "turn_id": self.turn_id,
            "user_message": self.user_message,
            "assistant_response": self.assistant_response,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class SessionState:
    """Session 状态"""
    session_id: str
    turns: List[ConversationTurn] = field(default_factory=list)
    topic_id: Optional[str] = None  # 话题结束时生成
    topic_start_time: Optional[datetime] = None
    status: str = "active"  # active, topic_ended, archived
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)

    # 归档相关
    pending_archive_summary: Optional[str] = None
    archive_completed: bool = False

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "turns": [t.to_dict() for t in self.turns],
            "topic_id": self.topic_id,
            "topic_start_time": self.topic_start_time.isoformat() if self.topic_start_time else None,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "pending_archive_summary": self.pending_archive_summary,
            "archive_completed": self.archive_completed,
        }


class SessionManager:
    """
    Session 管理器

    内存缓存 + 可选 PostgreSQL 持久化
    """

    def __init__(self, max_sessions: int = 1000, session_timeout: int = 3600):
        """
        Args:
            max_sessions: 最大 session 数量
            session_timeout: session 超时时间（秒）
        """
        self._sessions: Dict[str, SessionState] = {}
        self._lock = threading.Lock()
        self.max_sessions = max_sessions
        self.session_timeout = session_timeout

        # 启动定期清理
        self._cleanup_task = None

    def start_cleanup_task(self, interval: int = 300):
        """启动定期清理任务"""
        async def _cleanup_loop():
            while True:
                await asyncio.sleep(interval)
                self.cleanup_expired_sessions()

        self._cleanup_task = asyncio.create_task(_cleanup_loop())
        logger.info(f"Session 清理任务已启动，间隔 {interval}s")

    def create_session(self, session_id: str = None) -> SessionState:
        """创建新 Session"""
        if session_id is None:
            session_id = f"sess_{uuid.uuid4().hex[:12]}"

        with self._lock:
            # 检查是否超过上限
            if len(self._sessions) >= self.max_sessions:
                self._cleanup_expired()

            session = SessionState(session_id=session_id)
            self._sessions[session_id] = session
            logger.info(f"创建 Session: {session_id}")
            return session

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """获取 Session"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.last_activity = datetime.now()
            return session

    def add_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_response: str
    ) -> Optional[ConversationTurn]:
        """添加一轮对话"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                logger.warning(f"Session 不存在: {session_id}")
                return None

            turn = ConversationTurn(
                turn_index=len(session.turns),
                user_message=user_message,
                assistant_response=assistant_response,
            )
            session.turns.append(turn)
            session.last_activity = datetime.now()

            logger.debug(f"Session {session_id} 添加第 {turn.turn_index} 轮对话")
            return turn

    def end_topic(self, session_id: str) -> Optional[str]:
        """结束当前话题，生成 topic_id"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None

            # 生成 topic_id: topic_{session_id}_{timestamp}
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            topic_id = f"topic_{session.session_id}_{timestamp}"

            session.topic_id = topic_id
            session.topic_start_time = datetime.now()
            session.status = "topic_ended"

            logger.info(f"Session {session_id} 话题结束，topic_id: {topic_id}")
            return topic_id

    def start_new_topic(self, session_id: str) -> bool:
        """开始新话题（保留 session，重置话题相关状态）"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            # 保留 pending_archive_summary 供下一轮使用
            old_summary = session.pending_archive_summary

            session.topic_id = None
            session.topic_start_time = None
            session.status = "active"
            session.turns = []  # 清空对话轮次
            session.archive_completed = False

            logger.info(f"Session {session_id} 开始新话题")
            return True

    def set_pending_archive_summary(self, session_id: str, summary: str) -> bool:
        """设置待归档摘要"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            session.pending_archive_summary = summary
            return True

    def mark_archive_completed(self, session_id: str) -> bool:
        """标记归档完成"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            session.archive_completed = True
            session.status = "archived"
            logger.info(f"Session {session_id} 归档完成")
            return True

    def get_turns_for_archive(self, session_id: str) -> List[Dict]:
        """获取用于归档的对话数据"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return []

            return [t.to_dict() for t in session.turns]

    def delete_session(self, session_id: str) -> bool:
        """删除 Session"""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info(f"删除 Session: {session_id}")
                return True
            return False

    def delete_topic(self, topic_id: str) -> bool:
        """按 topic_id 删除（查找对应的 session）"""
        with self._lock:
            for session_id, session in list(self._sessions.items()):
                if session.topic_id == topic_id:
                    del self._sessions[session_id]
                    logger.info(f"按 topic_id 删除 Session: {session_id}")
                    return True
            return False

    def cleanup_expired_sessions(self) -> int:
        """清理过期的 Session"""
        with self._lock:
            return self._cleanup_expired()

    def _cleanup_expired(self) -> int:
        """内部清理方法（需要已持有锁）"""
        now = datetime.now()
        expired = []

        for session_id, session in self._sessions.items():
            elapsed = (now - session.last_activity).total_seconds()
            if elapsed > self.session_timeout:
                expired.append(session_id)

        for session_id in expired:
            del self._sessions[session_id]

        if expired:
            logger.info(f"清理 {len(expired)} 个过期 Session")

        return len(expired)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            active_count = sum(1 for s in self._sessions.values() if s.status == "active")
            topic_ended_count = sum(1 for s in self._sessions.values() if s.status == "topic_ended")
            archived_count = sum(1 for s in self._sessions.values() if s.status == "archived")

            return {
                "total_sessions": len(self._sessions),
                "active": active_count,
                "topic_ended": topic_ended_count,
                "archived": archived_count,
                "max_sessions": self.max_sessions,
                "session_timeout": self.session_timeout,
            }


# 全局单例
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """获取全局 SessionManager 单例"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
