"""
测试知识图谱构建功能 (Phase 2)
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.kg_manager import KnowledgeGraphManager
from database.pg_client import PGClient
from database.neo4j_client import Neo4jClient


async def test_entity_extraction():
    """测试实体抽取"""
    print("\n" + "=" * 60)
    print("测试实体抽取（带类型）")
    print("=" * 60)

    kg = KnowledgeGraphManager()

    test_text = """
    贾宝玉是荣国府的公子，生性风流多情。他与林黛玉青梅竹马，两人情投意合。
    林黛玉是林如海的女儿，寄居在荣国府。贾宝玉还有一个表姐薛宝钗，
    住在蘅芜苑。王熙凤是贾琏的妻子，掌管荣国府的家务大权。
    """

    triples = await kg.extract_entities_with_types(
        text=test_text,
        chunk_id="test_chunk_001",
        doc_id="test_doc"
    )

    print(f"\n抽取到 {len(triples)} 个三元组:")
    for t in triples:
        print(f"  [{t.subject_type}] {t.subject} --{t.predicate}--> [{t.object_type}] {t.object}")

    kg.close()
    return triples


async def test_neo4j_write():
    """测试 Neo4j 写入"""
    print("\n" + "=" * 60)
    print("测试 Neo4j 写入")
    print("=" * 60)

    kg = KnowledgeGraphManager()

    # 测试三元组
    test_triples = [
        {"subject": "贾宝玉", "subject_type": "person", "predicate": "青梅竹马", "object": "林黛玉", "object_type": "person"},
        {"subject": "贾宝玉", "subject_type": "person", "predicate": "居住", "object": "荣国府", "object_type": "location"},
        {"subject": "林黛玉", "subject_type": "person", "predicate": "寄居", "object": "荣国府", "object_type": "location"},
    ]

    from services.kg_manager import TripleWithMeta
    triples = [
        TripleWithMeta(
            subject=t["subject"],
            subject_type=t["subject_type"],
            predicate=t["predicate"],
            object=t["object"],
            object_type=t["object_type"],
            chunk_id="test_chunk",
            doc_id="test_doc"
        )
        for t in test_triples
    ]

    result = await kg.write_triples_to_neo4j(triples)
    print(f"\n写入结果: {result}")

    # 查询验证
    print("\n查询贾宝玉的关系:")
    rels = await kg.neo4j_client.get_relationships("贾宝玉")
    for rel in rels:
        print(f"  {rel['subject']} --{rel['relation']}--> {rel['object']}")

    kg.close()


async def test_similarity_edges():
    """测试相似度建边"""
    print("\n" + "=" * 60)
    print("测试相似度建边")
    print("=" * 60)

    kg = KnowledgeGraphManager()

    # 测试实体
    entities = ["贾宝玉", "宝玉", "林黛玉", "黛玉", "荣国府", "大观园"]

    # 计算 Embedding
    print("\n计算实体 Embedding...")
    embeddings = await kg.compute_entity_embeddings(entities)
    print(f"计算完成: {len(embeddings)} 个")

    # 找相似实体
    print("\n相似实体对:")
    for entity in entities[:3]:
        similar = await kg.find_similar_entities(entity, entities, embeddings)
        if similar:
            print(f"  {entity}:")
            for other, sim in similar:
                print(f"    -> {other} (similarity: {sim:.3f})")

    kg.close()


async def test_entity_dedup():
    """测试实体去重"""
    print("\n" + "=" * 60)
    print("测试实体去重")
    print("=" * 60)

    kg = KnowledgeGraphManager()

    # 测试可能重复的实体
    entities = ["贾宝玉", "宝玉", "宝二爷", "林黛玉", "黛玉", "潇湘妃子"]

    print("\n计算 Embedding...")
    embeddings = await kg.compute_entity_embeddings(entities)

    print("\n查找重复候选...")
    duplicates = await kg.find_duplicate_entities(entities, embeddings, threshold=0.85)

    print(f"发现 {len(duplicates)} 个可能重复的实体对:")
    for e1, e2, sim in duplicates:
        print(f"  {e1} <-> {e2} (similarity: {sim:.3f})")

        # 使用 LLM 判断
        should_merge, keep_name = await kg.rerank_entity_merge(e1, e2)
        print(f"    -> LLM 判断: {'合并' if should_merge else '不合并'} (保留: {keep_name})")

    kg.close()


async def build_kg_from_existing_data():
    """从现有 PostgreSQL 数据构建知识图谱"""
    print("\n" + "=" * 60)
    print("从现有数据构建知识图谱")
    print("=" * 60)

    pg = PGClient()
    pg.connect()

    try:
        # 获取所有 Chunks
        with pg.conn.cursor() as cur:
            cur.execute("""
                SELECT chunk_id, doc_id, text_content
                FROM chunks
                ORDER BY created_at
            """)
            chunks = [
                {"chunk_id": row[0], "doc_id": row[1], "text_content": row[2]}
                for row in cur.fetchall()
            ]

        print(f"从 PostgreSQL 获取 {len(chunks)} 个 Chunk")

        if not chunks:
            print("没有数据，请先运行数据摄入")
            return

        # 构建知识图谱
        kg = KnowledgeGraphManager()
        result = await kg.build_knowledge_graph_from_chunks(
            chunks=chunks,
            build_similarity_edges=True,
            deduplicate=True
        )

        print(f"\n知识图谱构建完成:")
        print(f"  - 抽取三元组: {result['triples_extracted']}")
        print(f"  - 唯一实体: {result['unique_entities']}")
        print(f"  - Neo4j 写入: {result['neo4j_write']}")
        print(f"  - 相似度边: {result['similarity_edges']}")
        if result['deduplication']:
            print(f"  - 去重候选: {result['deduplication'].get('duplicate_candidates', 0)}")

        kg.close()

    finally:
        pg.close()


async def query_neo4j_stats():
    """查询 Neo4j 统计信息"""
    print("\n" + "=" * 60)
    print("Neo4j 统计信息")
    print("=" * 60)

    neo4j = Neo4jClient()
    neo4j.connect()

    try:
        # 查询实体数量
        with neo4j.driver.session() as session:
            result = session.run("MATCH (e:Entity) RETURN count(e) as count")
            entity_count = result.single()["count"]

            result = session.run("MATCH ()-[r]->() RETURN count(r) as count")
            rel_count = result.single()["count"]

            # 按类型统计实体
            result = session.run("""
                MATCH (e:Entity)
                RETURN e.entity_type as type, count(e) as count
                ORDER BY count DESC
            """)
            type_stats = [(r["type"], r["count"]) for r in result]

            # 按类型统计关系
            result = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) as type, count(r) as count
                ORDER BY count DESC
            """)
            rel_stats = [(r["type"], r["count"]) for r in result]

        print(f"\n实体总数: {entity_count}")
        print(f"关系总数: {rel_count}")

        print(f"\n实体类型分布:")
        for t, c in type_stats[:10]:
            print(f"  - {t}: {c}")

        print(f"\n关系类型分布:")
        for t, c in rel_stats[:10]:
            print(f"  - {t}: {c}")

        # 查询一些示例关系
        print(f"\n示例关系（贾宝玉）:")
        rels = await neo4j.get_relationships("贾宝玉", limit=10)
        for rel in rels:
            print(f"  {rel['subject']} --{rel['relation']}--> {rel['object']}")

    finally:
        neo4j.close()


async def main():
    print("=" * 60)
    print("Phase 2 知识图谱构建测试")
    print("=" * 60)

    # 1. 测试实体抽取
    await test_entity_extraction()

    # 2. 测试 Neo4j 写入
    await test_neo4j_write()

    # 3. 测试相似度建边
    await test_similarity_edges()

    # 4. 测试实体去重
    await test_entity_dedup()

    # 5. 从现有数据构建知识图谱
    await build_kg_from_existing_data()

    # 6. 查询统计
    await query_neo4j_stats()

    print("\n" + "=" * 60)
    print("Phase 2 测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="知识图谱构建测试")
    parser.add_argument("--build", action="store_true", help="从现有数据构建知识图谱")
    parser.add_argument("--stats", action="store_true", help="查询 Neo4j 统计")
    parser.add_argument("--test", action="store_true", help="运行单元测试")
    args = parser.parse_args()

    if args.build:
        asyncio.run(build_kg_from_existing_data())
    elif args.stats:
        asyncio.run(query_neo4j_stats())
    elif args.test:
        asyncio.run(main())
    else:
        asyncio.run(main())
