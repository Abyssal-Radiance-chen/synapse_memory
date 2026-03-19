"""
人物志 CRUD API 路由（全异步）
"""
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Request

from database.models import CharacterCreate, CharacterUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/characters", tags=["人物志"])


@router.get("", response_model=List[dict])
async def list_characters(req: Request):
    pg = req.app.state.pg_client
    return await pg.list_characters()


@router.get("/{character_id}")
async def get_character(character_id: int, req: Request):
    pg = req.app.state.pg_client
    character = await pg.get_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="人物不存在")
    return character


@router.post("", response_model=dict)
async def create_character(data: CharacterCreate, req: Request):
    pg = req.app.state.pg_client
    return await pg.create_character(data)


@router.put("/{character_id}")
async def update_character(character_id: int, data: CharacterUpdate, req: Request):
    pg = req.app.state.pg_client
    result = await pg.update_character(character_id, data)
    if not result:
        raise HTTPException(status_code=404, detail="人物不存在")
    return result


@router.delete("/{character_id}")
async def delete_character(character_id: int, req: Request):
    pg = req.app.state.pg_client
    success = await pg.delete_character(character_id)
    if not success:
        raise HTTPException(status_code=404, detail="人物不存在")
    return {"success": True, "message": "删除成功"}
