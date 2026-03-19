"""
PostgreSQL 数据库操作封装（异步兼容）
使用 asyncio.to_thread 包装同步 psycopg2 调用
RLock + _execute_with_retry 保证线程安全 & 断线自动重连
"""
import asyncio
import json
import uuid
import logging
import threading
from typing import List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

import config
from database.models import (
    CREATE_TABLES_SQL,
    EventSummary,
    ConversationRound,
    CurrentEventContext,
    RollingSummary,
    SystemState,
    CharacterCreate,
    CharacterUpdate,
)

logger = logging.getLogger(__name__)


class PGClient:
    """PostgreSQL 数据库操作客户端（异步封装）"""

    def __init__(self):
        self.conn = None
        self._lock = threading.RLock()

    # --------------------------------------------------
    # 连接管理
    # --------------------------------------------------

    def connect(self):
        self.conn = psycopg2.connect(
            user=config.PG_USER,
            password=config.PG_PASSWORD,
            host=config.PG_HOST,
            port=config.PG_PORT,
            dbname=config.PG_DBNAME,
        )
        self.conn.autocommit = False
        logger.info("✅ PostgreSQL 连接成功")

    def close(self):
        if self.conn:
            self.conn.close()
            logger.info("PostgreSQL 连接已关闭")

    def _ensure_connection(self):
        if self.conn is None or self.conn.closed:
            self.connect()

    def _execute_with_retry(self, func):
        """线程安全 + 断线自动重连一次"""
        with self._lock:
            try:
                self._ensure_connection()
                return func()
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                logger.warning(f"⚠️ PG 连接异常 ({e})，正在重连...")
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None
                self._ensure_connection()
                return func()

    def init_tables(self):
        def _do():
            with self.conn.cursor() as cur:
                cur.execute(CREATE_TABLES_SQL)
            self.conn.commit()
            logger.info("✅ 数据库表初始化完成")
            # 确保 system_state 有初始行
            with self.conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM system_state")
                count = cur.fetchone()[0]
                if count == 0:
                    new_event_id = self._generate_event_id()
                    cur.execute(
                        "INSERT INTO system_state (current_event_id, current_event_round, global_round) VALUES (%s, 0, 0)",
                        (new_event_id,),
                    )
            self.conn.commit()
        self._execute_with_retry(_do)

    # --------------------------------------------------
    # 同步内部方法（全部通过 _execute_with_retry 保护）
    # --------------------------------------------------

    def _get_system_state_sync(self) -> SystemState:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM system_state ORDER BY id LIMIT 1")
                row = cur.fetchone()
                return SystemState(**row) if row else SystemState(
                    current_event_id=self._generate_event_id(),
                    current_event_round=0, global_round=0,
                )
        return self._execute_with_retry(_do)

    def _update_system_state_sync(self, **kwargs):
        def _do():
            updates = []
            values = []
            for key in ["current_event_id", "current_event_round", "global_round",
                         "event_start_time", "event_start_weather"]:
                if key in kwargs:
                    updates.append(f"{key} = %s")
                    values.append(kwargs[key])
            updates.append("updated_at = NOW()")
            if updates:
                sql = f"UPDATE system_state SET {', '.join(updates)} WHERE id = (SELECT MIN(id) FROM system_state)"
                with self.conn.cursor() as cur:
                    cur.execute(sql, values)
                self.conn.commit()
        self._execute_with_retry(_do)

    def _add_context_round_sync(self, ctx: CurrentEventContext):
        def _do():
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO current_event_context (event_id, round_in_event, user_message, assistant_message) VALUES (%s, %s, %s, %s)",
                    (ctx.event_id, ctx.round_in_event, ctx.user_message, ctx.assistant_message),
                )
            self.conn.commit()
        self._execute_with_retry(_do)

    def _get_current_event_context_sync(self) -> List[CurrentEventContext]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM current_event_context ORDER BY round_in_event ASC")
                return [CurrentEventContext(**row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    def _clear_current_event_context_sync(self):
        def _do():
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM current_event_context")
            self.conn.commit()
        self._execute_with_retry(_do)

    def _truncate_context_from_round_sync(self, event_id: str, target_round: int):
        def _do():
            with self.conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM current_event_context WHERE event_id = %s AND round_in_event >= %s",
                    (event_id, target_round)
                )
                cur.execute(
                    "DELETE FROM conversation_history WHERE event_id = %s AND round_in_event >= %s",
                    (event_id, target_round)
                )
            self.conn.commit()
        self._execute_with_retry(_do)

    def _save_conversation_round_sync(self, round_data: ConversationRound):
        def _do():
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO conversation_history (message_id, event_id, round_in_event, global_round, user_message, assistant_message) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (message_id) DO NOTHING",
                    (round_data.message_id, round_data.event_id, round_data.round_in_event,
                     round_data.global_round, round_data.user_message, round_data.assistant_message),
                )
            self.conn.commit()
        self._execute_with_retry(_do)

    def _get_conversation_by_event_sync(self, event_id: str) -> List[ConversationRound]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM conversation_history WHERE event_id = %s ORDER BY round_in_event ASC", (event_id,))
                return [ConversationRound(**row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    def _save_event_summary_sync(self, summary: EventSummary):
        def _do():
            with self.conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO event_summaries (event_id, summary_text, event_date, weather, start_round, end_round, round_count)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (event_id) DO UPDATE SET summary_text=EXCLUDED.summary_text, event_date=EXCLUDED.event_date,
                       weather=EXCLUDED.weather, end_round=EXCLUDED.end_round, round_count=EXCLUDED.round_count""",
                    (summary.event_id, summary.summary_text, summary.event_date, summary.weather,
                     summary.start_round, summary.end_round, summary.round_count),
                )
            self.conn.commit()
        self._execute_with_retry(_do)

    def _get_event_summary_sync(self, event_id: str) -> Optional[EventSummary]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM event_summaries WHERE event_id = %s", (event_id,))
                row = cur.fetchone()
                return EventSummary(**row) if row else None
        return self._execute_with_retry(_do)

    def _get_rolling_summaries_sync(self) -> List[RollingSummary]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM rolling_summary_window ORDER BY position ASC")
                return [RollingSummary(**row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    def _push_rolling_summary_sync(self, event_id: str, summary_text: str, event_date: str):
        def _do():
            max_events = config.MAX_CONTEXT_EVENTS
            with self.conn.cursor() as cur:
                cur.execute("UPDATE rolling_summary_window SET position = position + 1")
                cur.execute(
                    "INSERT INTO rolling_summary_window (event_id, summary_text, event_date, position) VALUES (%s, %s, %s, 1)",
                    (event_id, summary_text, event_date),
                )
                cur.execute("DELETE FROM rolling_summary_window WHERE position > %s", (max_events,))
            self.conn.commit()
        self._execute_with_retry(_do)

    def _create_character_sync(self, data: CharacterCreate) -> dict:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO character_profiles (name, relationship, gender, hobbies, basic_info, evaluation, related_events) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                    (data.name, data.relationship, data.gender, data.hobbies,
                     json.dumps(data.basic_info or {}, ensure_ascii=False),
                     data.evaluation, json.dumps(data.related_events or [], ensure_ascii=False)),
                )
                row = cur.fetchone()
            self.conn.commit()
            return dict(row)
        return self._execute_with_retry(_do)

    def _get_character_sync(self, character_id: int) -> Optional[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM character_profiles WHERE id = %s", (character_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        return self._execute_with_retry(_do)

    def _list_characters_sync(self) -> List[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM character_profiles ORDER BY id ASC")
                return [dict(row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    def _update_character_sync(self, character_id: int, data: CharacterUpdate) -> Optional[dict]:
        def _do():
            updates, values = [], []
            for field_name in ["name", "relationship", "gender", "hobbies", "evaluation"]:
                val = getattr(data, field_name, None)
                if val is not None:
                    updates.append(f"{field_name} = %s")
                    values.append(val)
            if data.basic_info is not None:
                updates.append("basic_info = %s")
                values.append(json.dumps(data.basic_info, ensure_ascii=False))
            if data.related_events is not None:
                updates.append("related_events = %s")
                values.append(json.dumps(data.related_events, ensure_ascii=False))
            if not updates:
                # 内部递归调用也受 RLock 保护
                with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM character_profiles WHERE id = %s", (character_id,))
                    row = cur.fetchone()
                    return dict(row) if row else None
            updates.append("updated_at = NOW()")
            values.append(character_id)
            sql = f"UPDATE character_profiles SET {', '.join(updates)} WHERE id = %s RETURNING *"
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, values)
                row = cur.fetchone()
            self.conn.commit()
            return dict(row) if row else None
        return self._execute_with_retry(_do)

    def _delete_character_sync(self, character_id: int) -> bool:
        def _do():
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM character_profiles WHERE id = %s RETURNING id", (character_id,))
                deleted = cur.fetchone()
            self.conn.commit()
            return deleted is not None
        return self._execute_with_retry(_do)

    def _search_characters_by_name_sync(self, name: str) -> List[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM character_profiles WHERE name ILIKE %s", (f"%{name}%",))
                return [dict(row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    def _query_all_sync(self, sql: str, params=None) -> List[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params or ())
                return [dict(row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    def _query_one_sync(self, sql: str, params=None) -> Optional[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params or ())
                row = cur.fetchone()
                return dict(row) if row else None
        return self._execute_with_retry(_do)

    # --------------------------------------------------
    # 异步公开接口
    # --------------------------------------------------

    async def get_system_state(self) -> SystemState:
        return await asyncio.to_thread(self._get_system_state_sync)

    async def update_system_state(self, **kwargs):
        await asyncio.to_thread(self._update_system_state_sync, **kwargs)

    async def add_context_round(self, ctx: CurrentEventContext):
        await asyncio.to_thread(self._add_context_round_sync, ctx)

    async def get_current_event_context(self) -> List[CurrentEventContext]:
        return await asyncio.to_thread(self._get_current_event_context_sync)

    async def clear_current_event_context(self):
        return await asyncio.to_thread(self._clear_current_event_context_sync)

    async def truncate_context_from_round(self, event_id: str, target_round: int):
        return await asyncio.to_thread(self._truncate_context_from_round_sync, event_id, target_round)

    async def save_conversation_round(self, round_data: ConversationRound):
        return await asyncio.to_thread(self._save_conversation_round_sync, round_data)

    async def get_conversation_by_event(self, event_id: str) -> List[ConversationRound]:
        return await asyncio.to_thread(self._get_conversation_by_event_sync, event_id)

    async def save_event_summary(self, summary: EventSummary):
        await asyncio.to_thread(self._save_event_summary_sync, summary)

    async def get_event_summary(self, event_id: str) -> Optional[EventSummary]:
        return await asyncio.to_thread(self._get_event_summary_sync, event_id)

    async def get_rolling_summaries(self) -> List[RollingSummary]:
        return await asyncio.to_thread(self._get_rolling_summaries_sync)

    async def push_rolling_summary(self, event_id: str, summary_text: str, event_date: str):
        await asyncio.to_thread(self._push_rolling_summary_sync, event_id, summary_text, event_date)

    async def create_character(self, data: CharacterCreate) -> dict:
        return await asyncio.to_thread(self._create_character_sync, data)

    async def get_character(self, character_id: int) -> Optional[dict]:
        return await asyncio.to_thread(self._get_character_sync, character_id)

    async def list_characters(self) -> List[dict]:
        return await asyncio.to_thread(self._list_characters_sync)

    async def update_character(self, character_id: int, data: CharacterUpdate) -> Optional[dict]:
        return await asyncio.to_thread(self._update_character_sync, character_id, data)

    async def delete_character(self, character_id: int) -> bool:
        return await asyncio.to_thread(self._delete_character_sync, character_id)

    async def search_characters_by_name(self, name: str) -> List[dict]:
        return await asyncio.to_thread(self._search_characters_by_name_sync, name)

    async def query_all(self, sql: str, params=None) -> List[dict]:
        return await asyncio.to_thread(self._query_all_sync, sql, params)

    async def query_one(self, sql: str, params=None) -> Optional[dict]:
        return await asyncio.to_thread(self._query_one_sync, sql, params)

    # --------------------------------------------------
    # 工具方法
    # --------------------------------------------------

    @staticmethod
    def _generate_event_id() -> str:
        return f"evt_{uuid.uuid4().hex[:8]}"

    def generate_new_event_id(self) -> str:
        return self._generate_event_id()
