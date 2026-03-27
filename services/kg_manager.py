"""
知识图谱管理服务 (Knowledge Graph Manager)

Phase 2 核心功能：
1. 实体抽取 + 类型识别
2. 三元组写入 Neo4j
3. 高维相似度建边（实体 Embedding 相似度 + LLM 判断）
4. Cross-Encoder 实体合并（Rerank 模型判断实体是否可合并）
"""
import asyncio
import logging
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
import numpy as np

from services.llm_client import LLMClient
from services.embedding_service import EmbeddingService
from database.neo4j_client import Neo4jClient
from database.pg_client import PGClient
from config import ModelConfig, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_VERIFY_SSL

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """实体"""
    name: str
    entity_type: str  # person, location, object, event, concept
    aliases: List[str]
    description: str
    embedding: Optional[List[float]] = None


@dataclass
class TripleWithMeta:
    """带元数据的三元组"""
    subject: str
    predicate: str
    object: str
    subject_type: str = "unknown"
    object_type: str = "unknown"
    chunk_id: str = ""
    doc_id: str = ""


class KnowledgeGraphManager:
    """
    知识图谱管理器

    整合实体抽取、图谱写入、相似度建边、实体合并
    """

    # 实体类型映射（中文 -> 英文）
    ENTITY_TYPE_MAP = {
        "人": "person",
        "人物": "person",
        "地点": "location",
        "位置": "location",
        "物品": "object",
        "事件": "event",
        "概念": "concept",
        "组织": "organization",
        "时间": "time",
    }

    # 相似度建边阈值
    SIMILARITY_THRESHOLD = 0.85
    # LLM 判断建边的阈值
    LLM_EDGE_THRESHOLD = 0.7

    def __init__(self):
        self.llm_client = LLMClient(ModelConfig(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            model=LLM_MODEL,
            verify_ssl=LLM_VERIFY_SSL,
        ))
        self.embedding_service = EmbeddingService()

        # 数据库客户端（延迟初始化）
        self._neo4j_client = None
        self._pg_client = None

    @property
    def neo4j_client(self):
        if self._neo4j_client is None:
            self._neo4j_client = Neo4jClient()
            self._neo4j_client.connect()
            self._neo4j_client.init_schema()
        return self._neo4j_client

    @property
    def pg_client(self):
        if self._pg_client is None:
            self._pg_client = PGClient()
            self._pg_client.connect()
        return self._pg_client

    # --------------------------------------------------
    # 2.1 实体抽取服务
    # --------------------------------------------------

    async def extract_entities_with_types(self, text: str, chunk_id: str = "", doc_id: str = "") -> List[TripleWithMeta]:
        """
        使用 LLM 从文本中抽取实体和关系（带类型）

        Returns:
            带类型的三元组列表
        """
        system_prompt = """你是一个专业的知识抽取助手。请从以下文本中抽取实体关系三元组。

三元组格式：主体|主体类型|关系|客体|客体类型

实体类型包括：person(人物), location(地点), object(物品), event(事件), concept(概念), organization(组织)

示例：
文本：贾宝玉是荣国府的公子，他和林黛玉青梅竹马，住在荣国府。
抽取：
贾宝玉|person|是|荣国府公子|concept
贾宝玉|person|青梅竹马|林黛玉|person
贾宝玉|person|居住|荣国府|location

要求：
1. 只抽取明确的关系，不要推测
2. 实体名称保持原文
3. 关系用简短动词或名词
4. 每行一个三元组，用 | 分隔
5. 最多抽取 15 个三元组
6. 必须包含实体类型"""

        try:
            content, _ = await self.llm_client.simple_complete(
                system_prompt,
                text[:2000]  # 限制长度
            )

            triples = []
            for line in content.strip().split('\n'):
                if '|' in line:
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) >= 5:
                        triples.append(TripleWithMeta(
                            subject=parts[0],
                            subject_type=self._normalize_entity_type(parts[1]),
                            predicate=parts[2],
                            object=parts[3],
                            object_type=self._normalize_entity_type(parts[4]),
                            chunk_id=chunk_id,
                            doc_id=doc_id,
                        ))
                    elif len(parts) >= 3:
                        # 兼容旧格式
                        triples.append(TripleWithMeta(
                            subject=parts[0],
                            predicate=parts[1],
                            object=parts[2],
                            chunk_id=chunk_id,
                            doc_id=doc_id,
                        ))

            return triples

        except Exception as e:
            logger.error(f"实体抽取失败: {e}")
            return []

    def _normalize_entity_type(self, type_str: str) -> str:
        """标准化实体类型"""
        type_lower = type_str.lower().strip()
        return self.ENTITY_TYPE_MAP.get(type_lower, type_lower)

    # --------------------------------------------------
    # 2.2 图谱写入
    # --------------------------------------------------

    async def write_triples_to_neo4j(self, triples: List[TripleWithMeta]) -> Dict[str, int]:
        """
        将三元组写入 Neo4j

        Returns:
            统计信息 {"entities": n, "relationships": m}
        """
        entity_count = 0
        rel_count = 0

        for triple in triples:
            try:
                # 创建主体实体
                await self.neo4j_client.create_entity(
                    name=triple.subject,
                    entity_type=triple.subject_type,
                    aliases=[],
                )
                entity_count += 1

                # 创建客体实体
                await self.neo4j_client.create_entity(
                    name=triple.object,
                    entity_type=triple.object_type,
                    aliases=[],
                )
                entity_count += 1

                # 创建关系
                await self.neo4j_client.create_relationship(
                    subject=triple.subject,
                    predicate=triple.predicate,
                    obj=triple.object,
                    relation_type="RELATED_TO",
                    properties={
                        "chunk_id": triple.chunk_id,
                        "doc_id": triple.doc_id,
                        "predicate": triple.predicate,
                    }
                )
                rel_count += 1

            except Exception as e:
                logger.warning(f"写入三元组失败: {triple.subject} - {triple.predicate} - {triple.object}: {e}")

        logger.info(f"Neo4j 写入完成: {entity_count} 实体, {rel_count} 关系")
        return {"entities": entity_count, "relationships": rel_count}

    async def link_chunk_to_entities(self, chunk_id: str, entity_names: List[str], doc_id: str = "") -> bool:
        """将 Chunk 关联到实体"""
        return await self.neo4j_client.link_chunk_to_entities(chunk_id, entity_names, doc_id)

    # --------------------------------------------------
    # 2.3 高维相似度建边
    # --------------------------------------------------

    async def compute_entity_embeddings(self, entity_names: List[str]) -> Dict[str, List[float]]:
        """
        为实体计算 Embedding

        Args:
            entity_names: 实体名称列表

        Returns:
            实体名称 -> Embedding 映射
        """
        embeddings = {}
        for name in entity_names:
            try:
                emb = await self.embedding_service.embed_text(name)
                if emb:
                    embeddings[name] = emb
            except Exception as e:
                logger.warning(f"实体 Embedding 计算失败: {name}: {e}")
        return embeddings

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        a = np.array(vec1)
        b = np.array(vec2)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    async def find_similar_entities(
        self,
        entity_name: str,
        all_entities: List[str],
        embeddings: Dict[str, List[float]],
        threshold: float = None
    ) -> List[Tuple[str, float]]:
        """
        找到与给定实体相似的其他实体

        Returns:
            [(entity_name, similarity), ...]
        """
        if entity_name not in embeddings:
            return []

        threshold = threshold or self.SIMILARITY_THRESHOLD
        target_emb = embeddings[entity_name]
        similar = []

        for other_name in all_entities:
            if other_name == entity_name:
                continue
            if other_name not in embeddings:
                continue

            sim = self.cosine_similarity(target_emb, embeddings[other_name])
            if sim >= threshold:
                similar.append((other_name, sim))

        return sorted(similar, key=lambda x: x[1], reverse=True)

    async def llm_judge_edge(self, entity1: str, entity2: str, similarity: float) -> Tuple[bool, str]:
        """
        使用 LLM 判断两个实体是否应该建立关系边

        Returns:
            (should_create_edge, relation_type)
        """
        prompt = f"""请判断以下两个实体是否应该建立关系：

实体1: {entity1}
实体2: {entity2}
语义相似度: {similarity:.2f}

请回答：
1. 是否应该建立关系？(是/否)
2. 如果是，关系类型是什么？（如：同义词、相关、上下位等）

请用以下格式回答：
判断: 是/否
关系: xxx（如果判断为是）"""

        try:
            content, _ = await self.llm_client.simple_complete(
                "你是一个知识图谱专家，负责判断实体间是否应该建立关系。",
                prompt
            )

            should_create = "是" in content or "yes" in content.lower()

            # 提取关系类型
            relation = "SIMILAR_TO"
            if "同义" in content:
                relation = "SYNONYM"
            elif "相关" in content:
                relation = "RELATED_TO"
            elif "上下位" in content or "父子" in content:
                relation = "HIERARCHICAL"

            return should_create, relation

        except Exception as e:
            logger.warning(f"LLM 判断建边失败: {e}")
            return False, ""

    async def build_similarity_edges(
        self,
        entity_names: List[str],
        use_llm_judge: bool = True,
        batch_size: int = 20
    ) -> int:
        """
        基于实体相似度建立边

        Args:
            entity_names: 实体名称列表
            use_llm_judge: 是否使用 LLM 判断
            batch_size: 批处理大小

        Returns:
            新建边数量
        """
        logger.info(f"开始相似度建边，共 {len(entity_names)} 个实体...")

        # 计算所有实体 Embedding
        embeddings = await self.compute_entity_embeddings(entity_names)

        edge_count = 0
        processed = set()

        for i, entity in enumerate(entity_names):
            if entity not in embeddings:
                continue

            # 找相似实体
            similar = await self.find_similar_entities(entity, entity_names, embeddings)

            for other, sim in similar[:5]:  # 每个实体最多建 5 条相似边
                pair = tuple(sorted([entity, other]))
                if pair in processed:
                    continue
                processed.add(pair)

                # LLM 判断
                if use_llm_judge:
                    should_create, relation = await self.llm_judge_edge(entity, other, sim)
                    if not should_create:
                        continue
                else:
                    relation = "SIMILAR_TO"

                # 创建边
                try:
                    await self.neo4j_client.create_relationship(
                        subject=entity,
                        predicate=relation,
                        obj=other,
                        relation_type=relation,
                        properties={"similarity": sim, "source": "similarity"}
                    )
                    edge_count += 1
                except Exception as e:
                    logger.warning(f"建边失败: {entity} - {other}: {e}")

            if (i + 1) % batch_size == 0:
                logger.info(f"相似度建边进度: {i + 1}/{len(entity_names)}")

        logger.info(f"相似度建边完成: 新建 {edge_count} 条边")
        return edge_count

    # --------------------------------------------------
    # 2.4 Cross-Encoder 实体合并
    # --------------------------------------------------

    async def find_duplicate_entities(
        self,
        entity_names: List[str],
        embeddings: Dict[str, List[float]],
        threshold: float = 0.92
    ) -> List[Tuple[str, str, float]]:
        """
        找出可能是重复的实体对

        Returns:
            [(entity1, entity2, similarity), ...]
        """
        duplicates = []
        checked = set()

        for i, e1 in enumerate(entity_names):
            if e1 not in embeddings:
                continue

            for e2 in entity_names[i + 1:]:
                if e2 not in embeddings:
                    continue

                pair = tuple(sorted([e1, e2]))
                if pair in checked:
                    continue
                checked.add(pair)

                sim = self.cosine_similarity(embeddings[e1], embeddings[e2])
                if sim >= threshold:
                    duplicates.append((e1, e2, sim))

        return sorted(duplicates, key=lambda x: x[2], reverse=True)

    async def rerank_entity_merge(self, entity1: str, entity2: str) -> Tuple[bool, str]:
        """
        使用 Rerank 模型判断两个实体是否应该合并

        Returns:
            (should_merge, reason)
        """
        # 如果有 Rerank 服务，使用 Rerank
        # 否则使用 LLM 判断
        prompt = f"""请判断以下两个实体是否应该合并为同一个实体：

实体1: {entity1}
实体2: {entity2}

判断标准：
1. 是否是同一个人的不同称呼？（如：宝玉、贾宝玉）
2. 是否是同一地点的不同名称？
3. 是否是完全不同的实体？

请回答：
判断: 合并/不合并
原因: xxx
保留名称: xxx（如果判断为合并）"""

        try:
            content, _ = await self.llm_client.simple_complete(
                "你是一个知识图谱专家，负责判断实体是否应该合并。",
                prompt
            )

            should_merge = "合并" in content and "不合并" not in content

            # 提取保留名称
            keep_name = entity1  # 默认保留第一个
            if "保留名称" in content:
                for line in content.split('\n'):
                    if "保留名称" in line:
                        parts = line.split(':')
                        if len(parts) > 1:
                            keep_name = parts[1].strip()
                            break

            return should_merge, keep_name

        except Exception as e:
            logger.warning(f"实体合并判断失败: {e}")
            return False, ""

    async def merge_entities(
        self,
        primary_name: str,
        secondary_name: str,
        aliases: List[str] = None
    ) -> bool:
        """
        合并两个实体

        将 secondary 的所有关系转移到 primary，并删除 secondary
        """
        try:
            # 获取 secondary 的所有关系
            rels = await self.neo4j_client.get_relationships(secondary_name)

            # 转移关系到 primary
            for rel in rels:
                if rel['subject'] == secondary_name:
                    await self.neo4j_client.create_relationship(
                        subject=primary_name,
                        predicate=rel['properties'].get('predicate', 'RELATED_TO'),
                        obj=rel['object'],
                        relation_type=rel['relation'],
                        properties=rel['properties']
                    )
                elif rel['object'] == secondary_name:
                    await self.neo4j_client.create_relationship(
                        subject=rel['subject'],
                        predicate=rel['properties'].get('predicate', 'RELATED_TO'),
                        obj=primary_name,
                        relation_type=rel['relation'],
                        properties=rel['properties']
                    )

            # 删除 secondary 实体
            await self.neo4j_client.delete_entity(secondary_name)

            # 更新 primary 的 aliases
            # TODO: 需要获取现有实体信息并更新

            logger.info(f"实体合并完成: {secondary_name} -> {primary_name}")
            return True

        except Exception as e:
            logger.error(f"实体合并失败: {e}")
            return False

    async def deduplicate_entities(
        self,
        entity_names: List[str] = None,
        auto_merge: bool = False
    ) -> Dict[str, Any]:
        """
        实体去重

        Args:
            entity_names: 要检查的实体列表（为空则从数据库获取）
            auto_merge: 是否自动合并（否则返回候选列表供人工确认）

        Returns:
            去重结果统计
        """
        if entity_names is None:
            # 从 Neo4j 获取所有实体
            # TODO: 实现获取所有实体的方法
            logger.warning("需要实现获取所有实体的方法")
            return {"status": "error", "message": "需要提供实体列表"}

        logger.info(f"开始实体去重，共 {len(entity_names)} 个实体...")

        # 计算 Embedding
        embeddings = await self.compute_entity_embeddings(entity_names)

        # 找重复候选
        duplicates = await self.find_duplicate_entities(entity_names, embeddings)

        result = {
            "total_entities": len(entity_names),
            "duplicate_candidates": len(duplicates),
            "merged": 0,
            "candidates": []
        }

        if auto_merge:
            for e1, e2, sim in duplicates:
                should_merge, keep_name = await self.rerank_entity_merge(e1, e2)
                if should_merge:
                    primary = keep_name if keep_name in [e1, e2] else e1
                    secondary = e2 if primary == e1 else e1
                    success = await self.merge_entities(primary, secondary)
                    if success:
                        result["merged"] += 1
        else:
            # 返回候选列表
            for e1, e2, sim in duplicates[:20]:  # 最多返回 20 个候选
                result["candidates"].append({
                    "entity1": e1,
                    "entity2": e2,
                    "similarity": sim
                })

        logger.info(f"实体去重完成: 发现 {result['duplicate_candidates']} 个候选，合并 {result['merged']} 个")
        return result

    # --------------------------------------------------
    # 综合流程
    # --------------------------------------------------

    async def build_knowledge_graph_from_chunks(
        self,
        chunks: List[Dict[str, str]],
        build_similarity_edges: bool = True,
        deduplicate: bool = True
    ) -> Dict[str, Any]:
        """
        从 Chunk 列表构建知识图谱

        Args:
            chunks: [{"chunk_id": str, "doc_id": str, "text_content": str}, ...]
            build_similarity_edges: 是否建立相似度边
            deduplicate: 是否去重

        Returns:
            构建结果统计
        """
        logger.info(f"开始构建知识图谱，共 {len(chunks)} 个 Chunk...")

        all_triples = []
        all_entities = set()

        # 1. 从每个 Chunk 抽取实体和关系
        for i, chunk in enumerate(chunks):
            triples = await self.extract_entities_with_types(
                text=chunk['text_content'],
                chunk_id=chunk['chunk_id'],
                doc_id=chunk['doc_id']
            )
            all_triples.extend(triples)

            for t in triples:
                all_entities.add(t.subject)
                all_entities.add(t.object)

            if (i + 1) % 10 == 0:
                logger.info(f"实体抽取进度: {i + 1}/{len(chunks)}")

        logger.info(f"实体抽取完成: {len(all_triples)} 个三元组, {len(all_entities)} 个实体")

        # 2. 写入 Neo4j
        write_result = await self.write_triples_to_neo4j(all_triples)

        # 3. 建立相似度边
        edge_count = 0
        if build_similarity_edges and all_entities:
            edge_count = await self.build_similarity_edges(list(all_entities))

        # 4. 实体去重
        dedup_result = {}
        if deduplicate and all_entities:
            dedup_result = await self.deduplicate_entities(list(all_entities), auto_merge=False)

        return {
            "triples_extracted": len(all_triples),
            "unique_entities": len(all_entities),
            "neo4j_write": write_result,
            "similarity_edges": edge_count,
            "deduplication": dedup_result
        }

    def close(self):
        """关闭连接"""
        if self._neo4j_client:
            self._neo4j_client.close()
        if self._pg_client:
            self._pg_client.close()
