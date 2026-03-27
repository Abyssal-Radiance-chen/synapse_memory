"""
记忆服务核心 - Memory Service

Phase 4 核心实现：
- submit_turn 接口
- 基础检索层
- 话题检测
- 异步归档
"""
import asyncio
import logging
import time
from typing import Optional, List, Dict, Any
from datetime import datetime

from services.session_manager import SessionManager, SessionState, ConversationTurn, get_session_manager
from services.memory_package import (
    RetrievalConfig, MemoryPackage, ChunkInfo, SummaryInfo,
    GraphContext, SessionStateInfo, UsageStats, TurnInput, TopicArchiveInfo
)
from services.query_rewriter import QueryRewriter
from services.hybrid_retrieval import HybridRetrievalService
from services.rerank_service import RerankService
from services.kg_manager import KnowledgeGraphManager
from services.llm_client import LLMClient
from services.embedding_service import EmbeddingService
from database.pg_client import PGClient
from database.milvus_client import MilvusVectorClient
from database.neo4j_client import Neo4jClient
from config import ModelConfig, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_VERIFY_SSL

logger = logging.getLogger(__name__)


class MemoryService:
    """
    记忆服务核心

    提供 submit_turn 接口，返回结构化 MemoryPackage
    """

    def __init__(self, config: RetrievalConfig = None):
        self.config = config or RetrievalConfig()

        # 核心组件
        self.session_manager = get_session_manager()
        self.query_rewriter = QueryRewriter()
        self.hybrid_retriever = HybridRetrievalService()
        self.rerank_service = RerankService()
        self.kg_manager = KnowledgeGraphManager()
        self.llm_client = LLMClient(ModelConfig(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            model=LLM_MODEL,
            verify_ssl=LLM_VERIFY_SSL,
        ))
        self.embedding_service = EmbeddingService()

        # 数据库客户端（延迟初始化）
        self._pg_client = None
        self._milvus_client = None
        self._neo4j_client = None

    @property
    def pg_client(self):
        if self._pg_client is None:
            self._pg_client = PGClient()
            self._pg_client.connect()
        return self._pg_client

    @property
    def milvus_client(self):
        if self._milvus_client is None:
            self._milvus_client = MilvusVectorClient()
            self._milvus_client.connect()
        return self._milvus_client

    @property
    def neo4j_client(self):
        if self._neo4j_client is None:
            self._neo4j_client = Neo4jClient()
            self._neo4j_client.connect()
        return self._neo4j_client

    # --------------------------------------------------
    # 核心 API: submit_turn
    # --------------------------------------------------

    async def submit_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_response: str,
        metadata: Dict[str, Any] = None,
        config: RetrievalConfig = None
    ) -> MemoryPackage:
        """
        提交一轮对话，返回记忆包

        Args:
            session_id: Session ID
            user_message: 用户消息
            assistant_response: 助手回复（必填）
            metadata: 额外元数据
            config: 可选的配置覆盖

        Returns:
            MemoryPackage: 结构化记忆包
        """
        start_time = time.time()
        effective_config = config or self.config

        # 1. 获取或创建 Session
        session = self.session_manager.get_session(session_id)
        if not session:
            session = self.session_manager.create_session(session_id)

        # 2. 添加对话轮次
        turn = self.session_manager.add_turn(
            session_id=session_id,
            user_message=user_message,
            assistant_response=assistant_response
        )

        # 3. 执行检索（基础层）
        retrieval_start = time.time()
        retrieval_result = await self._basic_retrieval(user_message, effective_config)
        retrieval_time = (time.time() - retrieval_start) * 1000

        # 4. Rerank
        rerank_start = time.time()
        ranked_chunks = await self._rerank_results(
            user_message,
            retrieval_result.get("chunks", []),
            effective_config.max_chunks
        )
        rerank_time = (time.time() - rerank_start) * 1000

        # 5. 获取图谱上下文
        graph_context = await self._get_graph_context(
            retrieval_result.get("entities", []),
            effective_config
        )

        # 6. 话题检测
        topic_changed = await self._detect_topic_change(
            session,
            user_message,
            assistant_response
        )

        # 7. 处理话题切换
        topic_id = None
        pending_summary = session.pending_archive_summary

        if topic_changed:
            # 结束当前话题
            topic_id = self.session_manager.end_topic(session_id)

            # 立即触发异步归档
            asyncio.create_task(self._archive_topic(session_id, topic_id))

            # 获取上一轮的待归档摘要（如果有）
            # 注意：这里不置空，下一轮会轮换覆盖

        # 8. 组装 MemoryPackage
        total_time = (time.time() - start_time) * 1000

        memory_package = MemoryPackage(
            ranked_chunks=ranked_chunks,
            ranked_summaries=retrieval_result.get("summaries", [])[:effective_config.max_summaries],
            graph_context=graph_context,
            extra_chunk_ids=retrieval_result.get("chunk_ids", []) if effective_config.include_extra_ids else [],
            pending_archive_summary=pending_summary,
            topic_changed=topic_changed,
            topic_id=topic_id,
            token_estimate=self._estimate_tokens(ranked_chunks, retrieval_result.get("summaries", [])),
            session_state=self._build_session_state(session, turn),
            usage=UsageStats(
                retrieval_time_ms=retrieval_time,
                rerank_time_ms=rerank_time,
                total_time_ms=total_time,
            )
        )

        logger.info(f"submit_turn 完成: session={session_id}, topic_changed={topic_changed}, time={total_time:.1f}ms")
        return memory_package

    # --------------------------------------------------
    # 基础检索层
    # --------------------------------------------------

    async def _basic_retrieval(
        self,
        query: str,
        config: RetrievalConfig
    ) -> Dict[str, Any]:
        """
        基础检索层

        QueryRewriter → Milvus 双通道 → RRF 融合
        """
        result = {
            "chunks": [],
            "summaries": [],
            "chunk_ids": [],
            "entities": [],
        }

        try:
            # 1. 查询重写/拆解
            rewritten_queries = await self.query_rewriter.rewrite_for_retrieval(query)
            if not rewritten_queries:
                rewritten_queries = [query]

            # 2. 向量检索
            all_chunks = []
            all_summaries = []

            for q in rewritten_queries[:3]:  # 最多处理 3 个查询
                # 获取 query embedding
                query_embedding = await self.embedding_service.embed_text(q)
                if not query_embedding:
                    continue

                # 检索 chunks
                chunk_results = await self.milvus_client.search_chunks(
                    query_embedding,
                    top_k=config.max_chunks * 2
                )

                for r in chunk_results:
                    if r.get("distance", 1) < config.min_similarity:
                        continue
                    all_chunks.append(ChunkInfo(
                        chunk_id=r["chunk_id"],
                        doc_id=r.get("doc_id", ""),
                        text_content=r.get("text_content", ""),
                        section_name=r.get("section_name"),
                        score=1 - r.get("distance", 0),
                    ))

                # 检索 summaries
                summary_results = await self.milvus_client.search_summaries(
                    query_embedding,
                    top_k=config.max_summaries * 2
                )

                for r in summary_results:
                    all_summaries.append(SummaryInfo(
                        summary_id=r.get("summary_id", ""),
                        doc_id=r.get("doc_id", ""),
                        summary_text=r.get("summary_text", ""),
                        summary_type=r.get("summary_type", ""),
                        score=1 - r.get("distance", 0),
                    ))

            # 3. 去重
            seen_chunks = set()
            unique_chunks = []
            for c in all_chunks:
                if c.chunk_id not in seen_chunks:
                    seen_chunks.add(c.chunk_id)
                    unique_chunks.append(c)
                if len(unique_chunks) >= config.max_chunks * 3:
                    break

            seen_summaries = set()
            unique_summaries = []
            for s in all_summaries:
                if s.summary_id not in seen_summaries:
                    seen_summaries.add(s.summary_id)
                    unique_summaries.append(s)
                if len(unique_summaries) >= config.max_summaries * 2:
                    break

            result["chunks"] = unique_chunks
            result["summaries"] = unique_summaries
            result["chunk_ids"] = [c.chunk_id for c in unique_chunks[config.max_chunks:]]

            # 4. 提取实体用于图谱
            entities = set()
            for c in unique_chunks[:10]:
                # 简单实体提取（可增强）
                pass
            result["entities"] = list(entities)

        except Exception as e:
            logger.error(f"基础检索失败: {e}")

        return result

    async def _rerank_results(
        self,
        query: str,
        chunks: List[ChunkInfo],
        top_k: int
    ) -> List[ChunkInfo]:
        """Rerank 检索结果"""
        if not chunks:
            return []

        try:
            # 准备 Rerank 输入 - 转换为字典列表
            candidates = [{"text_content": c.text_content} for c in chunks]

            # 调用 Rerank
            rerank_results = await self.rerank_service.rerank(
                query=query,
                candidates=candidates,
                top_k=top_k,
                text_key="text_content"
            )

            # 根据 rerank 结果重新排序 chunks
            reranked_chunks = []
            for result in rerank_results:
                if 0 <= result.index < len(chunks):
                    chunk = chunks[result.index]
                    chunk.score = result.score
                    reranked_chunks.append(chunk)

            # 设置排名
            for i, c in enumerate(reranked_chunks):
                c.rank = i + 1

            return reranked_chunks

        except Exception as e:
            error_msg = f"Rerank 夳败: {type(e).__name__}: {e}"
            logger.error(error_msg)
            raise ConnectionError(error_msg) from e

    # --------------------------------------------------
    # 图谱上下文
    # --------------------------------------------------

    async def _get_graph_context(
        self,
        entities: List[str],
        config: RetrievalConfig
    ) -> GraphContext:
        """获取图谱上下文"""
        context = GraphContext()

        if not entities:
            return context

        try:
            # 获取实体子图
            subgraph = await self.neo4j_client.get_entity_subgraph(
                entity_names=entities[:10],
                depth=1
            )

            # 限制数量
            context.entities = subgraph.get("entities", [])[:config.max_graph_entities]
            context.edges = subgraph.get("relationships", [])[:config.max_graph_edges]

        except Exception as e:
            logger.warning(f"获取图谱上下文失败: {e}")

        return context

    # --------------------------------------------------
    # 话题检测
    # --------------------------------------------------

    async def _detect_topic_change(
        self,
        session: SessionState,
        user_message: str,
        assistant_response: str
    ) -> bool:
        """
        使用 LLM 判断话题是否结束

        Returns:
            True 表示话题切换
        """
        # 至少要有几轮对话才判断
        if len(session.turns) < 2:
            return False

        # 构建对话历史
        history = ""
        for turn in session.turns[-5:]:  # 最近 5 轮
            history += f"用户: {turn.user_message}\n助手: {turn.assistant_response}\n\n"

        prompt = f"""请判断当前对话的话题是否已经结束，用户是否开始了新的话题。

对话历史：
{history}

当前用户消息：{user_message}

判断标准：
1. 用户是否提出了与之前完全无关的新问题？
2. 用户是否明确表示话题结束（如"好的"、"谢谢"、"换个话题"）？
3. 对话是否已经完整解决了用户的问题？

请回答：话题结束 或 话题继续
只需要回答这四个字之一。"""

        try:
            content, _ = await self.llm_client.simple_complete(
                "你是一个话题判断助手，负责判断对话话题是否已经结束。",
                prompt
            )

            result = "结束" in content or "end" in content.lower()
            logger.debug(f"话题检测: {'结束' if result else '继续'}")
            return result

        except Exception as e:
            logger.warning(f"话题检测失败: {e}")
            return False

    # --------------------------------------------------
    # 异步归档
    # --------------------------------------------------

    async def _archive_topic(self, session_id: str, topic_id: str):
        """
        异步归档话题

        1. 生成摘要
        2. 实体抽取
        3. 对话 Chunk 索引化
        4. 图谱更新
        """
        logger.info(f"开始归档话题: {topic_id}")

        try:
            session = self.session_manager.get_session(session_id)
            if not session:
                logger.warning(f"Session 不存在: {session_id}")
                return

            turns = self.session_manager.get_turns_for_archive(session_id)
            if not turns:
                logger.warning(f"没有对话轮次可归档: {session_id}")
                return

            # 1. 生成对话摘要
            conversation_text = "\n".join([
                f"用户: {t['user_message']}\n助手: {t['assistant_response']}"
                for t in turns
            ])

            summary = await self._generate_conversation_summary(conversation_text)

            # 2. 对话 Chunk 索引化
            doc_id = f"conv_{topic_id}"
            chunks_indexed = 0

            for i, turn in enumerate(turns):
                # 每轮对话一个 Chunk
                chunk_text = f"用户: {turn['user_message']}\n助手: {turn['assistant_response']}"
                chunk_id = f"{doc_id}_turn_{i}"

                # 存入 PostgreSQL
                from database.models import ChunkCreate
                await self.pg_client.create_chunk(ChunkCreate(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    text_content=chunk_text,
                    section_name=f"话题: {topic_id}",
                    section_index=i,
                    char_count=len(chunk_text),
                ))

                # 存入 Milvus
                embedding = await self.embedding_service.embed_text(chunk_text)
                if embedding:
                    await self.milvus_client.insert_chunk_vectors([{
                        "chunk_id": chunk_id,
                        "doc_id": doc_id,
                        "vector": embedding,
                        "text_content": chunk_text[:2000],
                        "section_name": f"话题: {topic_id}",
                    }])

                chunks_indexed += 1

            # 3. 创建文档记录
            from database.models import DocumentCreate
            await self.pg_client.create_document(DocumentCreate(
                doc_id=doc_id,
                doc_title=f"对话归档: {topic_id}",
                source_type="conversation",
                metadata={
                    "topic_id": topic_id,
                    "session_id": session_id,
                    "turn_count": len(turns),
                }
            ))

            # 4. 实体抽取和图谱更新
            entities_extracted = 0
            for turn in turns:
                text = f"{turn['user_message']} {turn['assistant_response']}"
                triples = await self.kg_manager.extract_entities_with_types(
                    text=text,
                    chunk_id=f"{doc_id}_turn_{turn['turn_index']}",
                    doc_id=doc_id
                )
                if triples:
                    await self.kg_manager.write_triples_to_neo4j(triples)
                    entities_extracted += len(triples) * 2

            # 5. 设置归档摘要（供下一轮使用）
            archive_summary = f"[归档摘要] {summary}\n话题ID: {topic_id}\n对话轮次: {len(turns)}"
            self.session_manager.set_pending_archive_summary(session_id, archive_summary)

            # 6. 标记归档完成
            self.session_manager.mark_archive_completed(session_id)

            logger.info(f"话题归档完成: {topic_id}, chunks={chunks_indexed}, entities={entities_extracted}")

        except Exception as e:
            logger.error(f"话题归档失败: {e}")
            import traceback
            traceback.print_exc()

    async def _generate_conversation_summary(self, conversation_text: str) -> str:
        """生成对话摘要"""
        prompt = f"""请为以下对话生成一个简洁的摘要，包括：
1. 主要讨论的话题
2. 关键结论或决定
3. 提到的重要实体（人物、地点、物品等）

对话内容：
{conversation_text[:3000]}

请用简洁的中文总结："""

        try:
            summary, _ = await self.llm_client.simple_complete(
                "你是一个对话摘要助手。",
                prompt
            )
            return summary
        except Exception as e:
            logger.warning(f"摘要生成失败: {e}")
            return "摘要生成失败"

    # --------------------------------------------------
    # 辅助方法
    # --------------------------------------------------

    def _estimate_tokens(
        self,
        chunks: List[ChunkInfo],
        summaries: List[SummaryInfo]
    ) -> int:
        """估算 token 数（简单按字符数估算）"""
        total_chars = 0
        for c in chunks:
            total_chars += len(c.text_content)
        for s in summaries:
            total_chars += len(s.summary_text)
        # 中文约 1.5 字符/token
        return int(total_chars / 1.5)

    def _build_session_state(
        self,
        session: SessionState,
        current_turn: ConversationTurn
    ) -> SessionStateInfo:
        """构建 Session 状态信息"""
        return SessionStateInfo(
            session_id=session.session_id,
            status=session.status,
            turn_count=len(session.turns),
            topic_id=session.topic_id,
            created_at=session.created_at,
            last_activity=session.last_activity,
        )

    # --------------------------------------------------
    # 其他 API
    # --------------------------------------------------

    async def get_session_state(self, session_id: str) -> Optional[Dict]:
        """获取 Session 状态"""
        session = self.session_manager.get_session(session_id)
        if not session:
            return None
        return session.to_dict()

    async def get_chunks_by_ids(self, chunk_ids: List[str]) -> List[ChunkInfo]:
        """按 ID 批量获取 Chunk"""
        chunks = []
        for chunk_id in chunk_ids:
            try:
                data = await self.pg_client.get_chunk(chunk_id)
                if data:
                    chunks.append(ChunkInfo(
                        chunk_id=data["chunk_id"],
                        doc_id=data["doc_id"],
                        text_content=data["text_content"],
                        section_name=data.get("section_name"),
                        section_index=data.get("section_index"),
                    ))
            except Exception as e:
                logger.warning(f"获取 chunk 失败: {chunk_id}: {e}")
        return chunks

    async def get_adjacent_chunks(
        self,
        chunk_id: str,
        window: int = 2
    ) -> List[ChunkInfo]:
        """逆向召回：获取相邻 Chunk"""
        try:
            # 获取当前 chunk 信息
            chunk = await self.pg_client.get_chunk(chunk_id)
            if not chunk:
                return []

            doc_id = chunk["doc_id"]
            section_index = chunk.get("section_index", 0)
            para_index = chunk.get("paragraph_index", 0)

            # 查询相邻 chunk
            # 简单实现：按 section_index 范围查询
            adjacent = await self.pg_client.get_chunks_by_doc(doc_id, limit=100)

            chunks = []
            for c in adjacent:
                c_section = c.get("section_index", 0)
                if abs(c_section - section_index) <= window:
                    chunks.append(ChunkInfo(
                        chunk_id=c["chunk_id"],
                        doc_id=c["doc_id"],
                        text_content=c["text_content"],
                        section_name=c.get("section_name"),
                        section_index=c.get("section_index"),
                    ))

            return chunks[:window * 2 + 1]

        except Exception as e:
            logger.warning(f"获取相邻 chunk 失败: {e}")
            return []

    def close(self):
        """关闭连接"""
        if self._pg_client:
            self._pg_client.close()
        if self._milvus_client:
            self._milvus_client.close()
        if self._neo4j_client:
            self._neo4j_client.close()
