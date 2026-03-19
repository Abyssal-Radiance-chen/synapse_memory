# 开发文档 (DEVELOPMENT)

## 环境要求

- **Python**: 3.9+
- **Node.js**: 18+
- **PostgreSQL**: 13+
- **Milvus**: 2.3+ (云端 Serverless 或本地 docker 部署均可)

## 后端开发

后端使用 FastAPI 框架。所有的状态管理、数据库连接均集中在 `main.py` 的 生命周期 (Lifespan) 中进行初始化。

### 服务分解
- **`ChatService`**: 负责处理自然语言对话的主要流程，组装上下文流、请求 LLM 并返回流式响应。同时负责判定话题切换、触发后台异步任务。
- **`MemoryAgent`**: 提取对话中的核心记忆，决策是否覆盖当前话题。
- **`EmbeddingService`**: 将文本转化为向量。
- **`SummaryService`**: 提炼并生成事件段落摘要。

### 数据库设计

1. **PostgreSQL** (`database/pg_client.py`)
   - 存储持久化：`conversation_history`, `event_summaries`, `character_profiles`, `system_state`, `current_event_context`, `rolling_summary_window`。
   - 所有数据库调用都使用 `_execute_with_retry` 进行封装，增加容错能力和并发锁。

2. **Milvus** (`database/milvus_client.py`)
   - 集合为 `event_vectors`，主要存储事件 ID，对应的文本向量(`embedding`)及前置摘要 (`summary_preview`)。

## 前端开发

前端为 Vite 创建的 Vue3 项目，位于 `web/` 目录。不依赖于任何大体积组件库。

- **`src/views/`**: 主要布局试图。
- **`src/components/`**: 会话气泡、历史面版、输入框等纯 UI 组件。
- **`src/composables/`**: 逻辑分离 (`useChat.ts` 负责实时流式通信和对话管理, `useHistory.ts` 处理 PostgreSQL API 中的查询逻辑)。

本地开发时，Vite 的 proxy 配置会将 `/v1`, `/api/characters`, `/health`, 和 `/api/pg` 重定向至后台的 8000 端口。

## 环境变量说明

运行前需确保 `.env` 全面覆盖各项配置：
```dotenv
# PG 数据库凭据
PG_USER=xxx
PG_PASSWORD=xxx
PG_HOST=xxx
PG_PORT=xxx
PG_DBNAME=xxx

# Milvus 凭据 
MILVUS_URI=xxx
MILVUS_TOKEN=xxx
MILVUS_COLLECTION_NAME=event_vectors

# LLM 模型设置 (Chat / Summary / Memory_Agent / Character)
..._MODEL_BASE_URL=xxx
..._MODEL_API_KEY=xxx
..._MODEL_NAME=xxx

# Embedding 模型设置 (基于 Qwen 或其他，需返回固定维度)
EMBEDDING_BASE_URL=xxx
EMBEDDING_API_KEY=xxx
EMBEDDING_MODEL=xxx
EMBEDDING_DIM=1024
```
