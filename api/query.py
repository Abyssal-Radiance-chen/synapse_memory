"""
查询 API 路由（全异步）
为前端提供历史对话、事件摘要、系统状态等查询接口 (原 web_pg_cline 迁移)
"""
import logging
from typing import Optional

from fastapi import APIRouter, Request, Query, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pg", tags=["查询"])

# ========== 对话历史 ==========

@router.get("/conversations")
async def get_conversations(
    req: Request,
    event_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """分页查询对话历史，可按 event_id 筛选"""
    pg = req.app.state.pg_client
    if event_id:
        rows = await pg.query_all(
            """SELECT id, message_id, event_id, round_in_event, global_round,
                      user_message, assistant_message, created_at
               FROM conversation_history
               WHERE event_id = %s
               ORDER BY global_round DESC
               LIMIT %s OFFSET %s""",
            (event_id, limit, offset),
        )
    else:
        rows = await pg.query_all(
            """SELECT id, message_id, event_id, round_in_event, global_round,
                      user_message, assistant_message, created_at
               FROM conversation_history
               ORDER BY global_round DESC
               LIMIT %s OFFSET %s""",
            (limit, offset),
        )
    return {"data": rows, "total": len(rows)}


@router.get("/conversations/recent")
async def get_recent_conversations(req: Request, limit: int = Query(20, ge=1, le=100)):
    """获取最近 N 轮对话（按时间正序返回）"""
    pg = req.app.state.pg_client
    rows = await pg.query_all(
        """SELECT id, message_id, event_id, round_in_event, global_round,
                  user_message, assistant_message, created_at
           FROM conversation_history
           ORDER BY global_round DESC
           LIMIT %s""",
        (limit,),
    )
    rows.reverse()
    return {"data": rows}


@router.get("/conversations/events")
async def get_conversation_events(req: Request):
    """按事件分组，返回每个事件的轮次数和时间范围"""
    pg = req.app.state.pg_client
    rows = await pg.query_all(
        """SELECT event_id,
                  COUNT(*) as round_count,
                  MIN(created_at) as first_message_at,
                  MAX(created_at) as last_message_at,
                  MIN(user_message) as first_user_message
           FROM conversation_history
           GROUP BY event_id
           ORDER BY MAX(global_round) DESC"""
    )
    return {"data": rows}


# ========== 事件摘要 ==========

@router.get("/summaries")
async def get_summaries(req: Request):
    """获取所有事件摘要"""
    pg = req.app.state.pg_client
    rows = await pg.query_all(
        """SELECT event_id, summary_text, event_date, weather,
                  start_round, end_round, round_count, created_at
           FROM event_summaries
           ORDER BY created_at DESC"""
    )
    return {"data": rows}


@router.get("/summaries/{event_id}")
async def get_summary_by_event(event_id: str, req: Request):
    """获取指定事件的摘要"""
    pg = req.app.state.pg_client
    row = await pg.query_one(
        """SELECT event_id, summary_text, event_date, weather,
                  start_round, end_round, round_count, created_at
           FROM event_summaries
           WHERE event_id = %s""",
        (event_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Summary not found")
    return {"data": row}


# ========== 系统状态 ==========

@router.get("/system-state")
async def get_system_state(req: Request):
    """获取当前系统状态"""
    pg = req.app.state.pg_client
    row = await pg.query_one(
        """SELECT current_event_id, current_event_round, global_round,
                  event_start_time, event_start_weather, updated_at
           FROM system_state
           ORDER BY id LIMIT 1"""
    )
    return {"data": row}


@router.get("/rolling-summaries")
async def get_rolling_summaries(req: Request):
    """获取滚动摘要窗口"""
    pg = req.app.state.pg_client
    rows = await pg.query_all(
        """SELECT event_id, summary_text, event_date, position, created_at
           FROM rolling_summary_window
           ORDER BY position ASC"""
    )
    return {"data": rows}


@router.get("/current-context")
async def get_current_context(req: Request):
    """获取当前事件的对话上下文"""
    pg = req.app.state.pg_client
    rows = await pg.query_all(
        """SELECT event_id, round_in_event, user_message, assistant_message, created_at
           FROM current_event_context
           ORDER BY round_in_event ASC"""
    )
    return {"data": rows}
