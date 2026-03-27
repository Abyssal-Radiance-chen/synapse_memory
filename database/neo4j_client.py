"""
Neo4j 知识图谱客户端（异步兼容）
用于实体关系存储和查询
"""
import asyncio
import logging
from typing import List, Optional, Dict, Any

from neo4j import GraphDatabase

import config

logger = logging.getLogger(__name__)


class Neo4jClient:
    """Neo4j 知识图谱客户端"""

    def __init__(self):
        self.driver = None
        self.database = config.NEO4J_DATABASE

    # --------------------------------------------------
    # 连接管理
    # --------------------------------------------------

    def connect(self):
        self.driver = GraphDatabase.driver(
            config.NEO4J_URI,
            auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)
        )
        # 验证连接
        self.driver.verify_connectivity()
        logger.info("✅ Neo4j 连接成功")

    def close(self):
        if self.driver:
            self.driver.close()
            logger.info("Neo4j 连接已关闭")

    def _ensure_connection(self):
        if self.driver is None:
            self.connect()

    # --------------------------------------------------
    # 初始化图结构
    # --------------------------------------------------

    def init_schema(self):
        """初始化图结构（创建约束和索引）"""
        def _create_constraints(tx):
            # Entity 约束
            tx.run("""
                CREATE CONSTRAINT entity_name_unique IF NOT EXISTS
                FOR (e:Entity) REQUIRE e.name IS UNIQUE
            """)

            # Entity 索引
            tx.run("""
                CREATE INDEX entity_type_index IF NOT EXISTS
                FOR (e:Entity) ON (e.entity_type)
            """)

            # Summary 索引
            tx.run("""
                CREATE INDEX summary_type_index IF NOT EXISTS
                FOR (s:Summary) ON (s.summary_type)
            """)

            # Chunk 索引
            tx.run("""
                CREATE INDEX chunk_doc_index IF NOT EXISTS
                FOR (c:Chunk) ON (c.doc_id)
            """)

        with self.driver.session() as session:
            session.execute_write(_create_constraints)
            logger.info("✅ Neo4j 图结构初始化完成")

    # --------------------------------------------------
    # 实体操作
    # --------------------------------------------------

    def _create_entity_sync(self, name: str, entity_type: str, aliases: List[str] = None, embedding: List[float] = None) -> bool:
        """创建或更新实体"""
        def _tx(tx):
            query = """
                MERGE (e:Entity {name: $name})
                SET e.entity_type = $entity_type,
                    e.aliases = $aliases,
                    e.embedding = $embedding
                RETURN e
            """
            result = tx.run(query, 
                name=name, 
                entity_type=entity_type,
                aliases=aliases or [],
                embedding=embedding or []
            )
            return result.single() is not None
        
        with self.driver.session() as session:
            return session.execute_write(_tx)

    def _get_entity_sync(self, name: str) -> Optional[Dict]:
        """获取实体"""
        def _tx(tx):
            query = "MATCH (e:Entity {name: $name}) RETURN e"
            result = tx.run(query, name=name)
            record = result.single()
            if record:
                entity = dict(record["e"])
                return entity
            return None
        
        with self.driver.session() as session:
            return session.execute_read(_tx)

    def _search_entities_sync(self, name_pattern: str, limit: int = 10) -> List[Dict]:
        """模糊搜索实体"""
        def _tx(tx):
            query = """
                MATCH (e:Entity)
                WHERE e.name CONTAINS $pattern OR ANY(alias IN e.aliases WHERE alias CONTAINS $pattern)
                RETURN e
                LIMIT $limit
            """
            result = tx.run(query, pattern=name_pattern, limit=limit)
            return [dict(record["e"]) for record in result]
        
        with self.driver.session() as session:
            return session.execute_read(_tx)

    def _delete_entity_sync(self, name: str) -> bool:
        """删除实体及其关系"""
        def _tx(tx):
            query = """
                MATCH (e:Entity {name: $name})
                DETACH DELETE e
                RETURN count(e) as deleted
            """
            result = tx.run(query, name=name)
            record = result.single()
            return record and record["deleted"] > 0
        
        with self.driver.session() as session:
            return session.execute_write(_tx)

    # --------------------------------------------------
    # 关系操作
    # --------------------------------------------------

    def _create_relationship_sync(self, subject: str, predicate: str, obj: str, 
                                   relation_type: str = "RELATED_TO", 
                                   properties: Dict = None) -> bool:
        """创建实体间的关系"""
        def _tx(tx):
            query = f"""
                MERGE (s:Entity {{name: $subject}})
                MERGE (o:Entity {{name: $object}})
                MERGE (s)-[r:{relation_type}]->(o)
                SET r.predicate = $predicate,
                    r.weight = coalesce(r.weight, 0.0) + 1
                SET r += $properties
                RETURN r
            """
            result = tx.run(query, 
                subject=subject, 
                object=obj, 
                predicate=predicate,
                properties=properties or {}
            )
            return result.single() is not None
        
        with self.driver.session() as session:
            return session.execute_write(_tx)

    def _get_relationships_sync(self, entity_name: str, relation_type: str = None, limit: int = 50) -> List[Dict]:
        """获取实体的所有关系"""
        def _tx(tx):
            if relation_type:
                query = f"""
                    MATCH (e:Entity {{name: $name}})-[r:{relation_type}]-(other)
                    RETURN e.name as subject, type(r) as relation, other.name as object, r as properties
                    LIMIT $limit
                """
            else:
                query = """
                    MATCH (e:Entity {name: $name})-[r]-(other)
                    RETURN e.name as subject, type(r) as relation, other.name as object, r as properties
                    LIMIT $limit
                """
            result = tx.run(query, name=entity_name, limit=limit)
            relationships = []
            for record in result:
                rel = {
                    "subject": record["subject"],
                    "relation": record["relation"],
                    "object": record["object"],
                    "properties": dict(record["properties"]) if record["properties"] else {}
                }
                relationships.append(rel)
            return relationships
        
        with self.driver.session() as session:
            return session.execute_read(_tx)

    # --------------------------------------------------
    # Chunk 关联操作
    # --------------------------------------------------

    def _link_chunk_to_entities_sync(self, chunk_id: str, entity_names: List[str], doc_id: str = None) -> bool:
        """将 Chunk 关联到实体"""
        def _tx(tx):
            # 创建 Chunk 节点
            tx.run("""
                MERGE (c:Chunk {chunk_id: $chunk_id})
                SET c.doc_id = $doc_id
            """, chunk_id=chunk_id, doc_id=doc_id)
            
            # 关联实体
            for entity_name in entity_names:
                tx.run("""
                    MATCH (c:Chunk {chunk_id: $chunk_id})
                    MERGE (e:Entity {name: $entity_name})
                    MERGE (c)-[:MENTIONS]->(e)
                """, chunk_id=chunk_id, entity_name=entity_name)
            
            return True
        
        with self.driver.session() as session:
            return session.execute_write(_tx)

    def _get_chunks_by_entity_sync(self, entity_name: str, limit: int = 20) -> List[Dict]:
        """获取与实体关联的所有 Chunk"""
        def _tx(tx):
            query = """
                MATCH (c:Chunk)-[:MENTIONS]->(e:Entity {name: $name})
                RETURN c.chunk_id as chunk_id, c.doc_id as doc_id
                LIMIT $limit
            """
            result = tx.run(query, name=entity_name, limit=limit)
            return [dict(record) for record in result]
        
        with self.driver.session() as session:
            return session.execute_read(_tx)

    # --------------------------------------------------
    # 图谱查询
    # --------------------------------------------------

    def _get_entity_subgraph_sync(self, entity_names: List[str], depth: int = 1) -> Dict:
        """获取实体周围的子图"""
        def _tx(tx):
            query = """
                MATCH path = (e:Entity)-[r*1..%d]-(other)
                WHERE e.name IN $names
                RETURN distinct e.name as entity, 
                       [node in nodes(path) | node.name] as path_nodes,
                       [rel in relationships(path) | type(rel)] as path_rels
                LIMIT 100
            """ % depth
            result = tx.run(query, names=entity_names)
            
            entities = set()
            relationships = []
            
            for record in result:
                entities.add(record["entity"])
                nodes = record["path_nodes"]
                rels = record["path_rels"]
                for i, rel in enumerate(rels):
                    if i < len(nodes) - 1:
                        relationships.append({
                            "subject": nodes[i],
                            "relation": rel,
                            "object": nodes[i + 1]
                        })
                        entities.add(nodes[i])
                        entities.add(nodes[i + 1])
            
            return {
                "entities": list(entities),
                "relationships": relationships
            }
        
        with self.driver.session() as session:
            return session.execute_read(_tx)

    # --------------------------------------------------
    # 异步公开接口
    # --------------------------------------------------

    async def create_entity(self, name: str, entity_type: str, aliases: List[str] = None, embedding: List[float] = None) -> bool:
        return await asyncio.to_thread(self._create_entity_sync, name, entity_type, aliases, embedding)

    async def get_entity(self, name: str) -> Optional[Dict]:
        return await asyncio.to_thread(self._get_entity_sync, name)

    async def search_entities(self, name_pattern: str, limit: int = 10) -> List[Dict]:
        return await asyncio.to_thread(self._search_entities_sync, name_pattern, limit)

    async def delete_entity(self, name: str) -> bool:
        return await asyncio.to_thread(self._delete_entity_sync, name)

    async def create_relationship(self, subject: str, predicate: str, obj: str, 
                                   relation_type: str = "RELATED_TO", 
                                   properties: Dict = None) -> bool:
        return await asyncio.to_thread(self._create_relationship_sync, subject, predicate, obj, relation_type, properties)

    async def get_relationships(self, entity_name: str, relation_type: str = None, limit: int = 50) -> List[Dict]:
        return await asyncio.to_thread(self._get_relationships_sync, entity_name, relation_type, limit)

    async def link_chunk_to_entities(self, chunk_id: str, entity_names: List[str], doc_id: str = None) -> bool:
        return await asyncio.to_thread(self._link_chunk_to_entities_sync, chunk_id, entity_names, doc_id)

    async def get_chunks_by_entity(self, entity_name: str, limit: int = 20) -> List[Dict]:
        return await asyncio.to_thread(self._get_chunks_by_entity_sync, entity_name, limit)

    async def get_entity_subgraph(self, entity_names: List[str], depth: int = 1) -> Dict:
        return await asyncio.to_thread(self._get_entity_subgraph_sync, entity_names, depth)
