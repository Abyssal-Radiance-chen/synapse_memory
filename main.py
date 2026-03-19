"""
伴侣记忆系统 - FastAPI 入口
"""
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from database.pg_client import PGClient
from database.milvus_client import MilvusVectorClient
from services.embedding_service import EmbeddingService
from services.chat_service import ChatService
from api.chat import router as chat_router
from api.character import router as character_router
from api.query import router as query_router

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # ====== 启动 ======
    logger.info("🚀 伴侣记忆系统启动中...")

    # 初始化 PostgreSQL
    pg_client = PGClient()
    pg_client.connect()
    pg_client.init_tables()
    app.state.pg_client = pg_client

    # 初始化 Milvus
    milvus_client = MilvusVectorClient()
    milvus_client.connect()
    milvus_client.init_collection()
    app.state.milvus_client = milvus_client

    # 初始化 Embedding 服务
    embedding_service = EmbeddingService()
    app.state.embedding_service = embedding_service

    # 初始化 Chat 服务
    chat_service = ChatService(pg_client, milvus_client, embedding_service)
    app.state.chat_service = chat_service

    logger.info("✅ 所有服务初始化完成")

    yield

    # ====== 关闭 ======
    logger.info("🛑 伴侣记忆系统关闭中...")
    pg_client.close()
    milvus_client.close()
    logger.info("所有连接已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="伴侣记忆系统",
    description="一个基于多 AI 协同的伴侣对话记忆系统",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(chat_router)
app.include_router(character_router)
app.include_router(query_router)


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "memory-system"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        reload=False, #True,
    )
