"""
数据摄入管道 (Ingestion Pipeline) - 优化版

核心改进：
1. 3库并行入库（PgSQL + ES + Milvus）
2. LLM 三元组抽取（实体-关系-实体）
3. 流式处理，减少内存占用
"""
import asyncio
import logging
import uuid
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
from dataclasses import dataclass

from services.document_processor import DocumentProcessor, Chunk
from services.embedding_service import EmbeddingService
from services.llm_client import LLMClient
from config import ModelConfig, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_VERIFY_SSL

import config

logger = logging.getLogger(__name__)


@dataclass
class Triple:
    """三元组"""
    subject: str  # 主体
    predicate: str  # 谓词/关系
    object: str  # 客体
    chunk_id: str  # 来源 chunk
    doc_id: str  # 来源文档


class IngestionPipeline:
    """
    数据摄入管道 - 优化版

    3库并行入库 + 三元组抽取
    """

    def __init__(self):
        self.processor = DocumentProcessor(overlap_size=128)
        self.embedding_service = EmbeddingService()
        self.llm_client = LLMClient(ModelConfig(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            model=LLM_MODEL,
            verify_ssl=LLM_VERIFY_SSL,
        ))

        # 数据库客户端（延迟初始化）
        self._pg_client = None
        self._es_client = None
        self._milvus_client = None

    @property
    def pg_client(self):
        if self._pg_client is None:
            from database.pg_client import PGClient
            self._pg_client = PGClient()
            self._pg_client.connect()
        return self._pg_client

    @property
    def es_client(self):
        if self._es_client is None:
            from database.es_client import ESClient
            self._es_client = ESClient()
        return self._es_client

    @property
    def milvus_client(self):
        if self._milvus_client is None:
            from database.milvus_client import MilvusVectorClient
            self._milvus_client = MilvusVectorClient()
            self._milvus_client.connect()
            self._milvus_client.init_collections()
        return self._milvus_client

    async def ingest_document(
        self,
        text: str,
        doc_id: str,
        doc_title: str,
        source_type: str = "article",
        source_path: Optional[str] = None,
        metadata: Optional[dict] = None,
        use_es: bool = False,  # ES 作为可选项，默认禁用
    ) -> Dict[str, Any]:
        """
        摄入单个文档 - 并行入库

        Args:
            text: 文档原始文本
            doc_id: 文档唯一标识
            doc_title: 文档标题
            source_type: 来源类型 (article/conversation)
            source_path: 来源路径
            metadata: 额外元数据
            use_es: 是否启用 ES 全文索引 (默认 False)

        Returns:
            摄入结果统计
        """
        logger.info(f"开始摄入文档: {doc_id} - {doc_title}")

        # 1. 创建文档记录
        await self._create_document(doc_id, doc_title, source_type, source_path, metadata)

        # 2. 文档处理 → Chunk 生成（含 128 字符重叠）
        chunks = self.processor.process(text, doc_id, doc_title)
        logger.info(f"文档切分完成: {len(chunks)} 个 Chunk")

        # 3. 批量获取 Embedding
        embeddings = await self._get_embeddings(chunks)

        # 4. 三元组抽取
        triples = await self._extract_triples(chunks)
        logger.info(f"三元组抽取完成: {len(triples)} 个")

        # 5. 并行入库 (PgSQL + Milvus, 可选 ES)
        await self._parallel_store(chunks, embeddings, triples, use_es=use_es)

        # 6. 生成摘要
        summaries = await self._generate_summaries(doc_id, chunks)
        logger.info(f"摘要生成完成: {len(summaries)} 个")

        # 7. 摘要向量化入库
        await self._vectorize_summaries(summaries)

        return {
            "doc_id": doc_id,
            "doc_title": doc_title,
            "chunk_count": len(chunks),
            "triple_count": len(triples),
            "summary_count": len(summaries),
            "status": "success",
        }

    async def _get_embeddings(self, chunks: List[Chunk]) -> List[List[float]]:
        """批量获取 Embedding"""
        texts = [c.text_content for c in chunks]
        return await self.embedding_service.embed_texts(texts)

    async def _parallel_store(
        self,
        chunks: List[Chunk],
        embeddings: List[List[float]],
        triples: List[Triple],
        use_es: bool = False,
    ):
        """
        并行入库

        默认：PgSQL + Milvus
        可选：ES 全文索引
        """
        logger.info(f"开始并行入库 (ES={'启用' if use_es else '禁用'})...")

        # 准备各库数据
        from database.models import ChunkCreate, RelationshipCreate

        # PgSQL 数据 - Chunks
        pg_tasks = []
        for chunk in chunks:
            chunk_create = ChunkCreate(
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                text_content=chunk.text_content,
                section_name=chunk.section_name,
                section_hierarchy=chunk.section_hierarchy,
                section_index=chunk.section_index,
                paragraph_index=chunk.paragraph_index,
                sub_chunk_index=chunk.sub_chunk_index,
                char_count=chunk.char_count,
            )
            pg_tasks.append(self.pg_client.create_chunk(chunk_create))

        # PgSQL 数据 - 三元组（关系）
        for triple in triples:
            rel_create = RelationshipCreate(
                subject_entity=triple.subject,
                object_entity=triple.object,
                relation_type=triple.predicate,
                predicate=triple.predicate,
                chunk_id=triple.chunk_id,
                doc_id=triple.doc_id,
            )
            pg_tasks.append(self.pg_client.create_relationship(rel_create))

        # Milvus 数据
        milvus_chunks = []
        for chunk, embedding in zip(chunks, embeddings):
            if embedding:
                milvus_chunks.append({
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "vector": embedding,
                    "text_content": chunk.text_content,
                    "section_name": chunk.section_name[:1024] if chunk.section_name else "",
                })

        # 构建任务列表
        tasks = [
            asyncio.gather(*pg_tasks, return_exceptions=True),  # PgSQL (chunks + triples)
            self.milvus_client.insert_chunk_vectors(milvus_chunks),  # Milvus
        ]

        # 可选：ES 索引
        if use_es:
            es_docs = [
                {
                    "chunk_id": c.chunk_id,
                    "doc_id": c.doc_id,
                    "text_content": c.text_content,
                    "section_name": c.section_name,
                    "section_hierarchy": c.section_hierarchy,
                }
                for c in chunks
            ]
            tasks.append(self.es_client.bulk_index_chunks(es_docs))

        # 并行执行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 检查结果
        pg_results = results[0]
        milvus_result = results[1]

        pg_success = sum(1 for r in pg_results if not isinstance(r, Exception))
        milvus_success = milvus_result if not isinstance(milvus_result, Exception) else False

        status = f"PgSQL={pg_success}/{len(chunks) + len(triples)}, Milvus={milvus_success}"
        if use_es:
            es_result = results[2]
            es_success = es_result if not isinstance(es_result, Exception) else False
            status += f", ES={es_success}"

        logger.info(f"✅ 并行入库完成: {status}")

    async def _extract_triples(self, chunks: List[Chunk]) -> List[Triple]:
        """
        使用 LLM 从 Chunk 中抽取三元组

        三元组格式：(主体, 关系, 客体)
        """
        system_prompt = """你是一个专业的知识抽取助手。请从以下文本中抽取实体关系三元组。

三元组格式：主体 | 关系 | 客体

示例：
文本：贾宝玉是荣国府的公子，他和林黛玉青梅竹马。
抽取：
贾宝玉 | 是 | 荣国府公子
贾宝玉 | 青梅竹马 | 林黛玉

要求：
1. 只抽取明确的关系，不要推测
2. 实体名称保持原文
3. 关系用简短动词或名词
4. 每行一个三元组，用 | 分隔
5. 最多抽取 10 个三元组"""

        all_triples = []

        for chunk in chunks[:20]:  # 限制数量避免过多 API 调用
            try:
                content, _ = await self.llm_client.simple_complete(
                    system_prompt,
                    chunk.text_content[:1000]  # 限制长度
                )

                # 解析三元组
                for line in content.strip().split('\n'):
                    if '|' in line:
                        parts = [p.strip() for p in line.split('|')]
                        if len(parts) >= 3:
                            all_triples.append(Triple(
                                subject=parts[0],
                                predicate=parts[1],
                                object=parts[2],
                                chunk_id=chunk.chunk_id,
                                doc_id=chunk.doc_id,
                            ))

            except Exception as e:
                logger.warning(f"三元组抽取失败: {chunk.chunk_id}: {e}")

        return all_triples

    async def _create_document(self, doc_id: str, doc_title: str, source_type: str,
                              source_path: Optional[str], metadata: Optional[dict]):
        """创建文档记录"""
        from database.models import DocumentCreate
        doc = DocumentCreate(
            doc_id=doc_id,
            doc_title=doc_title,
            source_type=source_type,
            source_path=source_path,
            metadata=metadata or {},
        )
        await self.pg_client.create_document(doc)

    async def _generate_summaries(self, doc_id: str, chunks: List[Chunk]) -> List[Dict]:
        """生成摘要"""
        # 按章节分组
        section_chunks: Dict[int, List[Chunk]] = {}
        for chunk in chunks:
            if chunk.section_index not in section_chunks:
                section_chunks[chunk.section_index] = []
            section_chunks[chunk.section_index].append(chunk)

        summaries = []
        for section_idx, section_chunk_list in section_chunks.items():
            combined_text = "\n\n".join([c.text_content for c in section_chunk_list])
            if len(combined_text) > 4000:
                combined_text = combined_text[:4000] + "..."

            summary_text = await self._llm_summarize(combined_text, section_chunk_list[0].section_name)

            if summary_text:
                summary_id = f"{doc_id}_summary_{section_idx}"
                source_chunk_ids = [c.chunk_id for c in section_chunk_list]

                from database.models import SummaryCreate
                await self.pg_client.create_summary(SummaryCreate(
                    summary_id=summary_id,
                    doc_id=doc_id,
                    summary_type="section",
                    summary_text=summary_text,
                    source_chunks=source_chunk_ids,
                ))

                summaries.append({
                    "summary_id": summary_id,
                    "doc_id": doc_id,
                    "summary_text": summary_text,
                    "summary_type": "section",
                    "source_chunks": source_chunk_ids,
                })

        return summaries

    async def _llm_summarize(self, text: str, section_name: str) -> Optional[str]:
        """LLM 生成摘要"""
        system_prompt = """你是一个专业的文本摘要助手。请将以下文本内容总结为一个简洁的事件摘要。

要求：
1. 保留关键信息和重要细节
2. 摘要长度控制在 200-500 字
3. 使用清晰、流畅的语言"""

        try:
            content, _ = await self.llm_client.simple_complete(system_prompt, f"章节：{section_name}\n\n{text}")
            return content.strip()
        except Exception as e:
            logger.error(f"LLM 摘要生成失败: {e}")
            return None

    async def _vectorize_summaries(self, summaries: List[Dict]):
        """向量化摘要"""
        for summary in summaries:
            embedding = await self.embedding_service.embed_text(summary["summary_text"])
            if embedding:
                await self.milvus_client.insert_summary_vector({
                    "summary_id": summary["summary_id"],
                    "doc_id": summary["doc_id"],
                    "vector": embedding,
                    "summary_text": summary["summary_text"],
                    "summary_type": summary["summary_type"],
                })

    async def ingest_file(
        self,
        file_path: str,
        doc_id: Optional[str] = None,
        use_es: bool = False,
    ) -> Dict[str, Any]:
        """
        摄入文件

        Args:
            file_path: 文件路径
            doc_id: 文档ID（可选）
            use_es: 是否启用 ES 索引（默认 False）
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()

        if doc_id is None:
            doc_id = f"doc_{uuid.uuid4().hex[:12]}"

        return await self.ingest_document(
            text=text,
            doc_id=doc_id,
            doc_title=path.stem,
            source_type="article",
            source_path=str(path.absolute()),
            use_es=use_es,
        )

    def close(self):
        """关闭所有连接"""
        if self._pg_client:
            self._pg_client.close()
        if self._milvus_client:
            self._milvus_client.close()


# 便捷函数
async def ingest_file(
    file_path: str,
    doc_id: Optional[str] = None,
    use_es: bool = False,
) -> Dict[str, Any]:
    """
    便捷函数：摄入文件

    Args:
        file_path: 文件路径
        doc_id: 文档ID（可选）
        use_es: 是否启用 ES 索引（默认 False）
    """
    pipeline = IngestionPipeline()
    try:
        return await pipeline.ingest_file(file_path, doc_id, use_es)
    finally:
        pipeline.close()
