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
    DocumentCreate,
    ChunkCreate,
    SummaryCreate,
    EntityCreate,
    RelationshipCreate,
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
        """线程安全 + 断线自动重连一次 + 事务错误回滚"""
        with self._lock:
            try:
                self._ensure_connection()
                return func()
            except psycopg2.errors.InFailedSqlTransaction as e:
                # 事务中止错误，需要回滚后重试
                logger.warning(f"事务中止，正在回滚重试...")
                try:
                    self.conn.rollback()
                except Exception:
                    pass
                self._ensure_connection()
                return func()
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                logger.warning(f"PG 连接异常 ({e})，正在重连...")
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

            # 表结构迁移：为旧表添加缺失的列
            self._migrate_tables_sync()

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

    def _migrate_tables_sync(self):
        """表结构迁移：为旧表添加缺失的列"""
        migrations = [
            # summaries 表添加 updated_at 和 metadata 列
            "ALTER TABLE summaries ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE summaries ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'",
            # entities 表添加 updated_at 列
            "ALTER TABLE entities ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
        ]
        try:
            with self.conn.cursor() as cur:
                for sql in migrations:
                    cur.execute(sql)
            self.conn.commit()
            logger.info("✅ 数据库表结构迁移完成")
        except Exception as e:
            logger.warning(f"表结构迁移警告（可能列已存在）: {e}")
            self.conn.rollback()

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
    # Phase 0: 文档操作
    # --------------------------------------------------

    def _create_document_sync(self, data: DocumentCreate) -> dict:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """INSERT INTO documents (doc_id, doc_title, source_type, source_path, metadata)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (doc_id) DO UPDATE SET
                       doc_title = EXCLUDED.doc_title,
                       source_type = EXCLUDED.source_type,
                       source_path = EXCLUDED.source_path,
                       metadata = EXCLUDED.metadata,
                       updated_at = NOW()
                       RETURNING *""",
                    (data.doc_id, data.doc_title, data.source_type, data.source_path,
                     json.dumps(data.metadata or {}, ensure_ascii=False)),
                )
                row = cur.fetchone()
            self.conn.commit()
            return dict(row)
        return self._execute_with_retry(_do)

    def _get_document_sync(self, doc_id: str) -> Optional[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM documents WHERE doc_id = %s", (doc_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        return self._execute_with_retry(_do)

    def _list_documents_sync(self, limit: int = 100, offset: int = 0) -> List[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM documents ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (limit, offset)
                )
                return [dict(row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    def _delete_document_sync(self, doc_id: str) -> bool:
        def _do():
            with self.conn.cursor() as cur:
                # 先删除关联的 chunks
                cur.execute("DELETE FROM chunks WHERE doc_id = %s", (doc_id,))
                # 删除文档
                cur.execute("DELETE FROM documents WHERE doc_id = %s RETURNING id", (doc_id,))
                deleted = cur.fetchone()
            self.conn.commit()
            return deleted is not None
        return self._execute_with_retry(_do)

    def _update_document_chunk_count_sync(self, doc_id: str, delta: int = 1):
        def _do():
            with self.conn.cursor() as cur:
                cur.execute(
                    "UPDATE documents SET chunk_count = chunk_count + %s, updated_at = NOW() WHERE doc_id = %s",
                    (delta, doc_id)
                )
            self.conn.commit()
        self._execute_with_retry(_do)

    # --------------------------------------------------
    # Phase 0: 分块操作
    # --------------------------------------------------

    def _create_chunk_sync(self, data: ChunkCreate) -> dict:
        def _do():
            char_count = data.char_count or len(data.text_content)
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """INSERT INTO chunks (chunk_id, doc_id, text_content, section_name, section_hierarchy,
                       section_index, paragraph_index, sub_chunk_index, char_count)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (chunk_id) DO UPDATE SET
                       text_content = EXCLUDED.text_content,
                       section_name = EXCLUDED.section_name,
                       section_hierarchy = EXCLUDED.section_hierarchy,
                       section_index = EXCLUDED.section_index,
                       paragraph_index = EXCLUDED.paragraph_index,
                       sub_chunk_index = EXCLUDED.sub_chunk_index,
                       char_count = EXCLUDED.char_count
                       RETURNING *""",
                    (data.chunk_id, data.doc_id, data.text_content, data.section_name,
                     json.dumps(data.section_hierarchy or [], ensure_ascii=False),
                     data.section_index, data.paragraph_index, data.sub_chunk_index, char_count),
                )
                row = cur.fetchone()
            self.conn.commit()
            return dict(row)
        return self._execute_with_retry(_do)

    def _bulk_create_chunks_sync(self, chunks: List[ChunkCreate]) -> int:
        def _do():
            count = 0
            with self.conn.cursor() as cur:
                for chunk in chunks:
                    char_count = chunk.char_count or len(chunk.text_content)
                    cur.execute(
                        """INSERT INTO chunks (chunk_id, doc_id, text_content, section_name, section_hierarchy,
                           section_index, paragraph_index, sub_chunk_index, char_count)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (chunk_id) DO NOTHING""",
                        (chunk.chunk_id, chunk.doc_id, chunk.text_content, chunk.section_name,
                         json.dumps(chunk.section_hierarchy or [], ensure_ascii=False),
                         chunk.section_index, chunk.paragraph_index, chunk.sub_chunk_index, char_count),
                    )
                    if cur.rowcount > 0:
                        count += 1
            self.conn.commit()
            return count
        return self._execute_with_retry(_do)

    def _get_chunk_sync(self, chunk_id: str) -> Optional[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM chunks WHERE chunk_id = %s", (chunk_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        return self._execute_with_retry(_do)

    def _get_chunks_by_document_sync(self, doc_id: str, limit: int = 1000) -> List[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT * FROM chunks WHERE doc_id = %s
                       ORDER BY section_index NULLS LAST, paragraph_index NULLS LAST, sub_chunk_index NULLS LAST
                       LIMIT %s""",
                    (doc_id, limit)
                )
                return [dict(row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    def _delete_chunk_sync(self, chunk_id: str) -> bool:
        def _do():
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM chunks WHERE chunk_id = %s RETURNING id", (chunk_id,))
                deleted = cur.fetchone()
            self.conn.commit()
            return deleted is not None
        return self._execute_with_retry(_do)

    def _delete_chunks_by_document_sync(self, doc_id: str) -> int:
        def _do():
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM chunks WHERE doc_id = %s RETURNING count(*)", (doc_id,))
                count = cur.fetchone()[0]
            self.conn.commit()
            return count
        return self._execute_with_retry(_do)

    def _update_chunk_vector_status_sync(self, chunk_id: str, stored: bool = True):
        def _do():
            with self.conn.cursor() as cur:
                cur.execute(
                    "UPDATE chunks SET vector_stored = %s WHERE chunk_id = %s",
                    (stored, chunk_id)
                )
            self.conn.commit()
        self._execute_with_retry(_do)

    def _update_chunk_es_status_sync(self, chunk_id: str, indexed: bool = True):
        def _do():
            with self.conn.cursor() as cur:
                cur.execute(
                    "UPDATE chunks SET es_indexed = %s WHERE chunk_id = %s",
                    (indexed, chunk_id)
                )
            self.conn.commit()
        self._execute_with_retry(_do)

    def _get_unindexed_chunks_sync(self, limit: int = 100) -> List[dict]:
        """获取未索引到 ES 的 chunks"""
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM chunks WHERE es_indexed = FALSE LIMIT %s",
                    (limit,)
                )
                return [dict(row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    def _get_unvectored_chunks_sync(self, limit: int = 100) -> List[dict]:
        """获取未存储向量的 chunks"""
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM chunks WHERE vector_stored = FALSE LIMIT %s",
                    (limit,)
                )
                return [dict(row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    # --------------------------------------------------
    # Phase 0: 摘要操作
    # --------------------------------------------------

    def _create_summary_sync(self, data: SummaryCreate) -> dict:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """INSERT INTO summaries (summary_id, doc_id, summary_type, summary_text, source_chunks, time_info)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (summary_id) DO UPDATE SET
                       summary_text = EXCLUDED.summary_text,
                       source_chunks = EXCLUDED.source_chunks,
                       time_info = EXCLUDED.time_info,
                       updated_at = NOW()
                       RETURNING *""",
                    (data.summary_id, data.doc_id, data.summary_type,
                     data.summary_text, json.dumps(data.source_chunks or [], ensure_ascii=False),
                     data.time_info),
                )
                row = cur.fetchone()
            self.conn.commit()
            return dict(row)
        return self._execute_with_retry(_do)

    def _get_summary_sync(self, summary_id: str) -> Optional[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM summaries WHERE summary_id = %s", (summary_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        return self._execute_with_retry(_do)

    def _get_summaries_by_doc_sync(self, doc_id: str, limit: int = 100) -> List[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT * FROM summaries WHERE doc_id = %s
                       ORDER BY created_at DESC LIMIT %s""",
                    (doc_id, limit)
                )
                return [dict(row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    def _update_summary_es_status_sync(self, summary_id: str, indexed: bool = True):
        def _do():
            with self.conn.cursor() as cur:
                cur.execute(
                    "UPDATE summaries SET es_indexed = %s WHERE summary_id = %s",
                    (indexed, summary_id)
                )
            self.conn.commit()
        self._execute_with_retry(_do)

    def _delete_summary_sync(self, summary_id: str) -> bool:
        def _do():
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM summaries WHERE summary_id = %s RETURNING id", (summary_id,))
                deleted = cur.fetchone()
            self.conn.commit()
            return deleted is not None
        return self._execute_with_retry(_do)

    # --------------------------------------------------
    # Phase 0: 实体操作
    # --------------------------------------------------

    def _create_entity_sync(self, data: EntityCreate) -> dict:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """INSERT INTO entities (name, entity_type, aliases, description, metadata)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (name) DO UPDATE SET
                       entity_type = EXCLUDED.entity_type,
                       aliases = EXCLUDED.aliases,
                       description = COALESCE(EXCLUDED.description, entities.description),
                       metadata = EXCLUDED.metadata,
                       updated_at = NOW()
                       RETURNING *""",
                    (data.name, data.entity_type,
                     json.dumps(data.aliases or [], ensure_ascii=False),
                     data.description,
                     json.dumps(data.metadata or {}, ensure_ascii=False)),
                )
                row = cur.fetchone()
            self.conn.commit()
            return dict(row)
        return self._execute_with_retry(_do)

    def _get_entity_sync(self, entity_id: int) -> Optional[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM entities WHERE id = %s", (entity_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        return self._execute_with_retry(_do)

    def _get_entity_by_name_sync(self, name: str) -> Optional[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM entities WHERE name = %s", (name,))
                row = cur.fetchone()
                return dict(row) if row else None
        return self._execute_with_retry(_do)

    def _search_entities_sync(self, name_pattern: str, entity_type: str = None, limit: int = 20) -> List[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                if entity_type:
                    cur.execute(
                        """SELECT * FROM entities
                           WHERE name ILIKE %s AND entity_type = %s
                           ORDER BY mention_count DESC
                           LIMIT %s""",
                        (f"%{name_pattern}%", entity_type, limit)
                    )
                else:
                    cur.execute(
                        """SELECT * FROM entities
                           WHERE name ILIKE %s
                           ORDER BY mention_count DESC
                           LIMIT %s""",
                        (f"%{name_pattern}%", limit)
                    )
                return [dict(row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    def _increment_entity_mention_sync(self, entity_name: str):
        def _do():
            with self.conn.cursor() as cur:
                cur.execute(
                    "UPDATE entities SET mention_count = mention_count + 1 WHERE name = %s",
                    (entity_name,)
                )
            self.conn.commit()
        self._execute_with_retry(_do)

    def _delete_entity_sync(self, entity_id: int) -> bool:
        def _do():
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM entities WHERE id = %s RETURNING id", (entity_id,))
                deleted = cur.fetchone()
            self.conn.commit()
            return deleted is not None
        return self._execute_with_retry(_do)

    # --------------------------------------------------
    # Phase 0: 关系操作
    # --------------------------------------------------

    def _create_relationship_sync(self, data: RelationshipCreate) -> dict:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """INSERT INTO entity_relationships (subject_entity, object_entity, relation_type, predicate, properties, chunk_id, doc_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (subject_entity, object_entity, relation_type, chunk_id) DO UPDATE SET
                       predicate = COALESCE(EXCLUDED.predicate, entity_relationships.predicate),
                       properties = EXCLUDED.properties,
                       weight = entity_relationships.weight + 1
                       RETURNING *""",
                    (data.subject_entity, data.object_entity, data.relation_type,
                     data.predicate, json.dumps(data.properties or {}, ensure_ascii=False),
                     data.chunk_id, data.doc_id),
                )
                row = cur.fetchone()
            self.conn.commit()
            return dict(row)
        return self._execute_with_retry(_do)

    def _get_relationships_by_entity_sync(self, entity_name: str, limit: int = 50) -> List[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT * FROM entity_relationships
                       WHERE subject_entity = %s OR object_entity = %s
                       ORDER BY weight DESC
                       LIMIT %s""",
                    (entity_name, entity_name, limit)
                )
                return [dict(row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    def _delete_relationship_sync(self, relationship_id: int) -> bool:
        def _do():
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM entity_relationships WHERE id = %s RETURNING id", (relationship_id,))
                deleted = cur.fetchone()
            self.conn.commit()
            return deleted is not None
        return self._execute_with_retry(_do)

    def _get_relationships_by_chunk_sync(self, chunk_id: str) -> List[dict]:
        """通过 chunk_id 查询关系（溯源）"""
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT * FROM entity_relationships
                       WHERE chunk_id = %s
                       ORDER BY weight DESC""",
                    (chunk_id,)
                )
                return [dict(row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    def _get_relationships_by_doc_sync(self, doc_id: str, limit: int = 100) -> List[dict]:
        """通过 doc_id 查询关系网络"""
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT * FROM entity_relationships
                       WHERE doc_id = %s
                       ORDER BY weight DESC
                       LIMIT %s""",
                    (doc_id, limit)
                )
                return [dict(row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    # --------------------------------------------------
    # Phase 0: Chunk-Entity 关联操作
    # --------------------------------------------------

    def _link_chunk_to_entity_sync(self, chunk_id: str, entity_id: int) -> bool:
        def _do():
            with self.conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO chunk_entities (chunk_id, entity_id)
                       VALUES (%s, %s) ON CONFLICT DO NOTHING""",
                    (chunk_id, entity_id)
                )
            self.conn.commit()
            return True
        return self._execute_with_retry(_do)

    def _get_entities_by_chunk_sync(self, chunk_id: str) -> List[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT e.* FROM entities e
                       JOIN chunk_entities ce ON e.id = ce.entity_id
                       WHERE ce.chunk_id = %s""",
                    (chunk_id,)
                )
                return [dict(row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    def _get_chunks_by_entity_sync(self, entity_id: int, limit: int = 50) -> List[dict]:
        def _do():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT c.* FROM chunks c
                       JOIN chunk_entities ce ON c.chunk_id = ce.chunk_id
                       WHERE ce.entity_id = %s
                       LIMIT %s""",
                    (entity_id, limit)
                )
                return [dict(row) for row in cur.fetchall()]
        return self._execute_with_retry(_do)

    # --------------------------------------------------
    # Phase 0: 异步公开接口
    # --------------------------------------------------

    async def create_document(self, data: DocumentCreate) -> dict:
        return await asyncio.to_thread(self._create_document_sync, data)

    async def get_document(self, doc_id: str) -> Optional[dict]:
        return await asyncio.to_thread(self._get_document_sync, doc_id)

    async def list_documents(self, limit: int = 100, offset: int = 0) -> List[dict]:
        return await asyncio.to_thread(self._list_documents_sync, limit, offset)

    async def delete_document(self, doc_id: str) -> bool:
        return await asyncio.to_thread(self._delete_document_sync, doc_id)

    async def update_document_chunk_count(self, doc_id: str, delta: int = 1):
        await asyncio.to_thread(self._update_document_chunk_count_sync, doc_id, delta)

    async def create_chunk(self, data: ChunkCreate) -> dict:
        return await asyncio.to_thread(self._create_chunk_sync, data)

    async def bulk_create_chunks(self, chunks: List[ChunkCreate]) -> int:
        return await asyncio.to_thread(self._bulk_create_chunks_sync, chunks)

    async def get_chunk(self, chunk_id: str) -> Optional[dict]:
        return await asyncio.to_thread(self._get_chunk_sync, chunk_id)

    async def get_chunks_by_document(self, doc_id: str, limit: int = 1000) -> List[dict]:
        return await asyncio.to_thread(self._get_chunks_by_document_sync, doc_id, limit)

    async def delete_chunk(self, chunk_id: str) -> bool:
        return await asyncio.to_thread(self._delete_chunk_sync, chunk_id)

    async def delete_chunks_by_document(self, doc_id: str) -> int:
        return await asyncio.to_thread(self._delete_chunks_by_document_sync, doc_id)

    async def update_chunk_vector_status(self, chunk_id: str, stored: bool = True):
        await asyncio.to_thread(self._update_chunk_vector_status_sync, chunk_id, stored)

    async def update_chunk_es_status(self, chunk_id: str, indexed: bool = True):
        await asyncio.to_thread(self._update_chunk_es_status_sync, chunk_id, indexed)

    async def get_unindexed_chunks(self, limit: int = 100) -> List[dict]:
        return await asyncio.to_thread(self._get_unindexed_chunks_sync, limit)

    async def get_unvectored_chunks(self, limit: int = 100) -> List[dict]:
        return await asyncio.to_thread(self._get_unvectored_chunks_sync, limit)

    async def create_entity(self, data: EntityCreate) -> dict:
        return await asyncio.to_thread(self._create_entity_sync, data)

    async def get_entity(self, entity_id: int) -> Optional[dict]:
        return await asyncio.to_thread(self._get_entity_sync, entity_id)

    async def get_entity_by_name(self, name: str) -> Optional[dict]:
        return await asyncio.to_thread(self._get_entity_by_name_sync, name)

    async def search_entities(self, name_pattern: str, entity_type: str = None, limit: int = 20) -> List[dict]:
        return await asyncio.to_thread(self._search_entities_sync, name_pattern, entity_type, limit)

    async def increment_entity_mention(self, entity_name: str):
        await asyncio.to_thread(self._increment_entity_mention_sync, entity_name)

    async def delete_entity(self, entity_id: int) -> bool:
        return await asyncio.to_thread(self._delete_entity_sync, entity_id)

    async def create_relationship(self, data: RelationshipCreate) -> dict:
        return await asyncio.to_thread(self._create_relationship_sync, data)

    async def get_relationships_by_entity(self, entity_name: str, limit: int = 50) -> List[dict]:
        return await asyncio.to_thread(self._get_relationships_by_entity_sync, entity_name, limit)

    async def delete_relationship(self, relationship_id: int) -> bool:
        return await asyncio.to_thread(self._delete_relationship_sync, relationship_id)

    async def get_relationships_by_chunk(self, chunk_id: str) -> List[dict]:
        """通过 chunk_id 查询关系（溯源）"""
        return await asyncio.to_thread(self._get_relationships_by_chunk_sync, chunk_id)

    async def get_relationships_by_doc(self, doc_id: str, limit: int = 100) -> List[dict]:
        """通过 doc_id 查询关系网络"""
        return await asyncio.to_thread(self._get_relationships_by_doc_sync, doc_id, limit)

    async def link_chunk_to_entity(self, chunk_id: str, entity_id: int) -> bool:
        return await asyncio.to_thread(self._link_chunk_to_entity_sync, chunk_id, entity_id)

    async def get_entities_by_chunk(self, chunk_id: str) -> List[dict]:
        return await asyncio.to_thread(self._get_entities_by_chunk_sync, chunk_id)

    async def get_chunks_by_entity(self, entity_id: int, limit: int = 50) -> List[dict]:
        return await asyncio.to_thread(self._get_chunks_by_entity_sync, entity_id, limit)

    # --------------------------------------------------
    # Phase 0: 摘要操作（异步接口）
    # --------------------------------------------------

    async def create_summary(self, data: SummaryCreate) -> dict:
        return await asyncio.to_thread(self._create_summary_sync, data)

    async def get_summary(self, summary_id: str) -> Optional[dict]:
        return await asyncio.to_thread(self._get_summary_sync, summary_id)

    async def get_summaries_by_doc(self, doc_id: str, limit: int = 100) -> List[dict]:
        return await asyncio.to_thread(self._get_summaries_by_doc_sync, doc_id, limit)

    async def update_summary_es_status(self, summary_id: str, indexed: bool = True):
        await asyncio.to_thread(self._update_summary_es_status_sync, summary_id, indexed)

    async def delete_summary(self, summary_id: str) -> bool:
        return await asyncio.to_thread(self._delete_summary_sync, summary_id)

    # --------------------------------------------------
    # 工具方法
    # --------------------------------------------------

    @staticmethod
    def _generate_event_id() -> str:
        return f"evt_{uuid.uuid4().hex[:8]}"

    def generate_new_event_id(self) -> str:
        return self._generate_event_id()
