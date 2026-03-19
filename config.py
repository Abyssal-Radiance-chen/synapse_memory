"""
配置管理模块
所有可配置参数统一从 .env 读取，零硬编码
"""
import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


# ========== 模型配置 ==========

@dataclass
class ModelConfig:
    """单个LLM模型的配置"""
    base_url: str
    api_key: str
    model: str
    verify_ssl: bool = True


def _model_from_env(prefix: str) -> ModelConfig:
    """从环境变量中按前缀读取模型配置"""
    verify = os.getenv(f"{prefix}_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
    return ModelConfig(
        base_url=os.getenv(f"{prefix}_BASE_URL", ""),
        api_key=os.getenv(f"{prefix}_API_KEY", ""),
        model=os.getenv(f"{prefix}_NAME", os.getenv(f"{prefix}_MODEL", "")),
        verify_ssl=verify,
    )


# 各模块模型配置
CHAT_MODEL = _model_from_env("CHAT_MODEL")
SUMMARY_MODEL = _model_from_env("SUMMARY_MODEL")
MEMORY_AGENT_MODEL = _model_from_env("MEMORY_AGENT_MODEL")
CHARACTER_MODEL = _model_from_env("CHARACTER_MODEL")
EMBEDDING_MODEL = _model_from_env("EMBEDDING")


# ========== PostgreSQL 配置 ==========

PG_USER: str = os.getenv("PG_USER", "")
PG_PASSWORD: str = os.getenv("PG_PASSWORD", "")
PG_HOST: str = os.getenv("PG_HOST", "")
PG_PORT: str = os.getenv("PG_PORT", "5432")
PG_DBNAME: str = os.getenv("PG_DBNAME", "")

MILVUS_URI: str = os.getenv("MILVUS_URI", "")
MILVUS_TOKEN: str = os.getenv("MILVUS_TOKEN", "")
MILVUS_COLLECTION_NAME: str = os.getenv("MILVUS_COLLECTION_NAME", "event_vectors")


# ========== Embedding ==========

EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "1024"))


# ========== 天气配置 ==========

WEATHER_API_KEY: str = os.getenv("WEATHER_API_KEY", "")
WEATHER_CITY: str = os.getenv("WEATHER_CITY", "苏州")


# ========== 超参数 ==========

MAX_CONTEXT_EVENTS: int = int(os.getenv("MAX_CONTEXT_EVENTS", "5"))
MAX_ASYNC_QUERIES: int = int(os.getenv("MAX_ASYNC_QUERIES", "5"))
MAX_RETRIEVAL_ROUNDS: int = int(os.getenv("MAX_RETRIEVAL_ROUNDS", "2"))
MAX_FULL_SCENES: int = int(os.getenv("MAX_FULL_SCENES", "1"))
MAX_MEMORY_TOKENS: int = int(os.getenv("MAX_MEMORY_TOKENS", "8192"))


# ========== 服务配置 ==========

SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8000"))


# ========== 提示词文件路径 ==========

PROMPTS_DIR: str = os.path.join(os.path.dirname(__file__), "prompts")


def get_prompt(name: str) -> str:
    """读取提示词文件内容"""
    path = os.path.join(PROMPTS_DIR, f"{name}.md")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
