# Synapse Memory

> 独立的 AI 记忆检索系统 —— 为任意 LLM / Agent 提供结构化长期记忆能力

![系统架构](images/synapse_memory.png)

## 概述

Synapse Memory 是一个**独立部署的记忆服务**，通过 REST API 对外提供结构化的记忆检索能力。系统将非结构化文本（文章、对话）切分为 Chunk，构建摘要索引 + 向量索引 + 知识图谱的多路存储，并通过混合召回 + Rerank 实现高质量的对话记忆检索。

**核心特性：**
- 🔌 **即插即用** — 通过 `submit_turn` 接口接入，不侵入外部 LLM 逻辑
- 🧠 **结构化记忆包** — 返回原文 Chunk、摘要、知识图谱关系，使用者自行决定如何使用
- 🔍 **两层检索** — 基础重写检索（默认）+ Agent 增强检索（可选，≤5 轮迭代）
- 📊 **话题感知** — 自动检测话题切换，异步归档生成摘要和图谱
- ⚙️ **全可配置** — 所有检索参数均可由使用者按需调整，不设硬上限

## 技术栈

| 组件 | 技术 |
|------|------|
| **后端框架** | Python, FastAPI |
| **关系存储** | PostgreSQL — Chunk 原文、文档结构、摘要 |
| **向量存储** | Milvus (Zilliz Cloud) — 摘要向量 + Chunk 向量双集合 |
| **知识图谱** | Neo4j — 实体关系、L1 子图查询 |
| **全文检索** | Elasticsearch (可选备用) |
| **LLM** | OpenAI 兼容接口（Qwen3 等） |
| **Embedding** | 1024 维 Embedding 模型 |
| **Rerank** | Cross-Encoder 精排模型 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入实际的数据库连接和 API 密钥
```

### 3. 启动服务

```bash
# 启动独立记忆 API 服务
python -m api.memory_api

# 或使用 uvicorn
uvicorn api.memory_api:app --host 0.0.0.0 --port 8000
```

### 4. 接入使用

```python
from sdk.synapse_client import SynapseClient

async with SynapseClient("http://localhost:8000") as client:
    # 提交一轮对话，获取记忆包
    result = await client.submit_turn(
        session_id="my_session",
        user_message="红楼梦里的贾宝玉是什么样的人？",
        assistant_response="贾宝玉是主人公，性格风流多情。",
    )

    # 使用返回的记忆包
    print(f"相关 Chunk: {len(result.ranked_chunks)}")
    print(f"相关摘要: {len(result.ranked_summaries)}")
    print(f"话题切换: {result.topic_changed}")
```

更多示例参见 [`sdk/example_usage.py`](sdk/example_usage.py)。

## 核心 API

### `POST /submit_turn` — 核心交互

提交一轮对话，返回结构化记忆包（MemoryPackage）。

```json
{
  "session_id": "session_001",
  "user_message": "用户消息",
  "assistant_response": "助手回复",
  "max_chunks": 10,
  "max_summaries": 5,
  "min_similarity": 0.5,
  "enable_adjacent_chunks": false
}
```

**返回**：`ranked_chunks`、`ranked_summaries`、`graph_context`、`extra_chunk_ids`、`topic_changed`、`topic_id`、`pending_archive_summary`、`token_estimate`、`usage`

### `POST /ingest_document` — 文档摄入

将文档切分为 Chunk，建立向量索引和知识图谱。

### `GET /session/{session_id}` — Session 状态

### `POST /chunks/by_ids` — 按 ID 批量拉取 Chunk

### `GET /chunks/{chunk_id}/adjacent` — 逆向召回

### `DELETE /topic/{topic_id}` — 删除话题

完整 API 文档：启动服务后访问 `http://localhost:8000/docs`

## 目录结构

```text
.
├── api/                  # REST API 层
│   ├── memory_api.py     # 独立记忆服务 API（submit_turn 等）
│   ├── chat.py           # 对话服务 API
│   └── query.py          # 查询监控 API
├── database/             # 数据库客户端
│   ├── pg_client.py      # PostgreSQL 客户端
│   ├── milvus_client.py  # Milvus 向量数据库（双集合）
│   ├── es_client.py      # Elasticsearch（可选）
│   ├── neo4j_client.py   # Neo4j 知识图谱
│   └── models.py         # 数据模型定义
├── services/             # 核心服务逻辑
│   ├── memory_service.py # 记忆服务核心（submit_turn 实现）
│   ├── memory_package.py # MemoryPackage + RetrievalConfig 定义
│   ├── session_manager.py# Session 管理 + 临时缓存
│   ├── hybrid_retrieval.py# 混合检索（RRF 融合）
│   ├── query_rewriter.py # 查询拆解与重写
│   ├── rerank_service.py # Rerank 精排
│   ├── memory_agent.py   # 记忆检索 Agent
│   ├── kg_manager.py     # 知识图谱管理
│   ├── document_processor.py # 文档切分
│   ├── ingestion_pipeline.py # 摄入管道
│   ├── embedding_service.py  # Embedding 服务
│   ├── llm_client.py     # LLM 调用封装
│   └── summary_service.py# 摘要生成
├── sdk/                  # Python SDK
│   ├── synapse_client.py # 客户端封装
│   └── example_usage.py  # 使用示例
├── prompts/              # 系统提示词（Markdown）
├── docs/                 # 设计文档
├── images/               # 架构图等图片资源
├── tests/                # 测试
├── config.py             # 配置管理
├── main.py               # 服务入口
├── requirements.txt      # Python 依赖
└── .env.example          # 环境变量模板
```

## 检索架构

```
用户消息 → QueryRewriter 拆解多条查询
  → Milvus 并行检索（向量 + 关键词双通道）
  → RRF 融合 → Rerank → Top K

  [可选] Agent 增强层
  → 基于基础层结果 + 用户问题焦点
  → Agent 自主调用工具（补充检索 / 逆向召回 / 图谱追踪）
  → 最多 5 轮迭代 → 去重合并
```

## 配置说明

所有配置通过 `.env` 文件管理，参见 [`.env.example`](.env.example)。

关键配置项：
- `LLM_VERIFY_SSL` — SSL 验证开关（生产环境建议设为 `true`）
- `EMBEDDING_DIM` — Embedding 维度（默认 1024）
- `MAX_MEMORY_TOKENS` — 记忆检索的 token 预算

## License

[MIT](LICENSE)
