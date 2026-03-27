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


# LLM 配置
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "qwen")
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "")
LLM_VERIFY_SSL: bool = os.getenv("LLM_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
LLM_MODEL: str = os.getenv("LLM_MODEL", "")
LLM_MODEL_SUMMARY: str = os.getenv("LLM_MODEL_SUMMARY", LLM_MODEL)
LLM_MODEL_ENTITY: str = os.getenv("LLM_MODEL_ENTITY", LLM_MODEL)
LLM_MODEL_TOPIC: str = os.getenv("LLM_MODEL_TOPIC", LLM_MODEL)
LLM_MODEL_AGENT: str = os.getenv("LLM_MODEL_AGENT", LLM_MODEL)
LLM_MODEL_QUERY: str = os.getenv("LLM_MODEL_QUERY", LLM_MODEL)

# 兼容旧配置（带 verify_ssl 支持）
CHAT_MODEL = ModelConfig(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, model=LLM_MODEL, verify_ssl=LLM_VERIFY_SSL)
SUMMARY_MODEL = ModelConfig(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, model=LLM_MODEL_SUMMARY, verify_ssl=LLM_VERIFY_SSL)
MEMORY_AGENT_MODEL = ModelConfig(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, model=LLM_MODEL_AGENT, verify_ssl=LLM_VERIFY_SSL)
CHARACTER_MODEL = ModelConfig(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, model=LLM_MODEL, verify_ssl=LLM_VERIFY_SSL)

# ========== Embedding 配置 ==========

EMBEDDING_BASE_URL: str = os.getenv("EMBEDDING_BASE_URL", "")
EMBEDDING_API_KEY: str = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_NAME: str = os.getenv("EMBEDDING_NAME", "Qwen3-Embedding-0.6B")
EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "1024"))

EMBEDDING_MODEL = ModelConfig(
    base_url=EMBEDDING_BASE_URL,
    api_key=EMBEDDING_API_KEY,
    model=EMBEDDING_NAME,
)

# ========== Rerank 配置 ==========

RERANK_URL: str = os.getenv("RERANK_URL", "")
RERANK_MODEL: str = os.getenv("RERANK_MODEL", "")
RERANK_API_KEY: str = os.getenv("RERANK_API_KEY", "")

# ========== PostgreSQL 配置 ==========

PG_USER: str = os.getenv("PG_USER", "")
PG_PASSWORD: str = os.getenv("PG_PASSWORD", "")
PG_HOST: str = os.getenv("PG_HOST", "")
PG_PORT: str = os.getenv("PG_PORT", "5432")
PG_DBNAME: str = os.getenv("PG_DBNAME", "")

# ========== Milvus 配置 ==========

MILVUS_URI: str = os.getenv("MILVUS_URI", "")
MILVUS_TOKEN: str = os.getenv("MILVUS_TOKEN", "")
MILVUS_COLLECTION_NAME: str = os.getenv("MILVUS_COLLECTION_NAME", "event_vectors")
MILVUS_CHUNK_COLLECTION: str = os.getenv("MILVUS_CHUNK_COLLECTION", "chunk_vectors")
MILVUS_SUMMARY_COLLECTION: str = os.getenv("MILVUS_SUMMARY_COLLECTION", "summary_vectors")

# ========== Neo4j 配置 ==========

NEO4J_URI: str = os.getenv("NEO4J_URI", "")
NEO4J_USER: str = os.getenv("NEO4J_USER", "")
NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE: str = os.getenv("NEO4J_DATABASE", "neo4j")

# ========== Elasticsearch 配置 ==========

ES_URL: str = os.getenv("ES_URL", "")
ES_USER: str = os.getenv("ES_USER", "")
ES_PASSWORD: str = os.getenv("ES_PASSWORD", "")
ES_API_KEY: str = os.getenv("ES_API_KEY", "")
ES_CHUNKS_INDEX: str = os.getenv("ES_CHUNKS_INDEX", "chunks_index")
ES_SUMMARIES_INDEX: str = os.getenv("ES_SUMMARIES_INDEX", "summaries_index")

# ========== 天气配置 ==========

WEATHER_API_KEY: str = os.getenv("WEATHER_API_KEY", "")
WEATHER_CITY: str = os.getenv("WEATHER_CITY", "苏州")

# ========== 超参数 ==========

MAX_CONTEXT_EVENTS: int = int(os.getenv("MAX_CONTEXT_EVENTS", "5"))
MAX_ASYNC_QUERIES: int = int(os.getenv("MAX_ASYNC_QUERIES", "5"))
MAX_RETRIEVAL_ROUNDS: int = int(os.getenv("MAX_RETRIEVAL_ROUNDS", "2"))
MAX_FULL_SCENES: int = int(os.getenv("MAX_FULL_SCENES", "1"))
MAX_MEMORY_TOKENS: int = int(os.getenv("MAX_MEMORY_TOKENS", "8192"))

# ========== RRF 融合配置 ==========

RRF_K: int = int(os.getenv("RRF_K", "60"))
RRF_ALPHA: float = float(os.getenv("RRF_ALPHA", "0.33"))  # ES 全文权重
RRF_BETA: float = float(os.getenv("RRF_BETA", "0.33"))    # 摘要向量权重
RRF_GAMMA: float = float(os.getenv("RRF_GAMMA", "0.34"))  # Chunk 向量权重

# ========== 分块配置 ==========

CHUNK_HARD_SPLIT: int = int(os.getenv("CHUNK_HARD_SPLIT", "1536"))
CHUNK_INDEPENDENT_MIN: int = int(os.getenv("CHUNK_INDEPENDENT_MIN", "512"))
CHUNK_INDEPENDENT_MAX: int = int(os.getenv("CHUNK_INDEPENDENT_MAX", "1024"))
CHUNK_BUFFER_MAX: int = int(os.getenv("CHUNK_BUFFER_MAX", "1536"))
CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "128"))

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
