"""
Phase 0 基础设施连接测试
测试 PostgreSQL, Elasticsearch, Neo4j, Milvus 连接
"""
import asyncio
import sys
import os
from pathlib import Path

# 设置 UTF-8 编码输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.pg_client import PGClient
from database.es_client import ESClient
from database.neo4j_client import Neo4jClient
from database.models import DocumentCreate, ChunkCreate, SummaryCreate
import config


async def test_postgresql():
    """测试 PostgreSQL 连接"""
    print("\n" + "="*60)
    print("PostgreSQL 连接测试")
    print("="*60)

    pg = PGClient()
    try:
        pg.connect()
        print("✅ PostgreSQL 连接成功")

        # 测试初始化表
        pg.init_tables()
        print("✅ 数据库表初始化成功")

        # 测试创建文档
        doc = await pg.create_document(DocumentCreate(
            doc_id="test_doc_001",
            doc_title="测试文档",
            source_type="text",
            metadata={"test": "data"}
        ))
        print(f"✅ 创建文档: {doc['doc_id']}")

        # 测试获取文档
        retrieved = await pg.get_document("test_doc_001")
        print(f"✅ 获取文档: {retrieved['doc_title']}")

        # 测试创建分块
        chunk = await pg.create_chunk(ChunkCreate(
            chunk_id="test_chunk_001",
            doc_id="test_doc_001",
            text_content="这是一个测试分块。",
            section_name="测试章节",
            section_index=1,
            paragraph_index=1
        ))
        print(f"✅ 创建分块: {chunk['chunk_id']}")

        # 测试获取分块
        chunks = await pg.get_chunks_by_document("test_doc_001")
        print(f"✅ 获取分块数量: {len(chunks)}")

        # 测试创建摘要
        summary = await pg.create_summary(SummaryCreate(
            summary_id="test_summary_001",
            doc_id="test_doc_001",
            summary_type="scene_summary",
            summary_text="这是一个测试摘要。",
            source_chunks=["test_chunk_001"],
            time_info="2026-03-24"
        ))
        print(f"✅ 创建摘要: {summary['summary_id']}")

        # 测试获取摘要
        summaries = await pg.get_summaries_by_doc("test_doc_001")
        print(f"✅ 获取摘要数量: {len(summaries)}")

        print("\n✅ PostgreSQL 测试通过")
        return True

    except Exception as e:
        print(f"\n❌ PostgreSQL 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        pg.close()
        print("\nPostgreSQL 连接已关闭")


async def test_elasticsearch():
    """测试 Elasticsearch 连接"""
    print("\n" + "="*60)
    print("Elasticsearch 连接测试")
    print("="*60)

    es = ESClient()
    try:
        # 测试创建索引（使用异步方法）
        chunks_indexed = await es.create_chunks_index_async()
        if chunks_indexed:
            print("✅ Chunks 索引创建成功")
        else:
            print("⚠️ Chunks 索引已存在或创建失败")

        summaries_indexed = await es.create_summaries_index_async()
        if summaries_indexed:
            print("✅ Summaries 索引创建成功")
        else:
            print("⚠️ Summaries 索引已存在或创建失败")

        # 测试索引文档
        chunk_doc = {
            "chunk_id": "test_chunk_es_001",
            "doc_id": "test_doc_001",
            "text_content": "这是一个用于 Elasticsearch 测试的分块内容。",
            "section_name": "ES测试章节",
            "created_at": "2026-03-24T13:14:00Z"
        }
        success = await es.index_chunk("test_chunk_es_001", chunk_doc)
        print(f"✅ Chunks 索引文档: {'成功' if success else '失败'}")

        # 测试全文搜索
        results = await es.search_chunks("Elasticsearch 测试", top_k=5)
        print(f"✅ 搜索结果数量: {len(results)}")
        if results:
            print(f"   - 第一个结果: {results[0].get('text_content', '')[:50]}...")

        # 测试 BM25 搜索
        bm25_results = await es.bm25_search_chunks("测试", top_k=5)
        print(f"✅ BM25 搜索结果数量: {len(bm25_results)}")

        print("\n✅ Elasticsearch 测试通过")
        return True

    except Exception as e:
        print(f"\n❌ Elasticsearch 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_neo4j():
    """测试 Neo4j 连接"""
    print("\n" + "="*60)
    print("Neo4j 连接测试")
    print("="*60)

    neo4j = Neo4jClient()
    try:
        # 测试连接
        neo4j.connect()
        print("✅ Neo4j 连接成功")

        # 测试初始化图结构
        neo4j.init_schema()
        print("✅ Neo4j 图结构初始化成功")

        # 测试创建实体
        entity1 = await neo4j.create_entity(
            name="测试实体1",
            entity_type="Person",
            aliases=["Test Entity 1", "T1"]
        )
        print(f"✅ 创建实体: {entity1}")

        entity2 = await neo4j.create_entity(
            name="测试实体2",
            entity_type="Location",
            aliases=["Test Entity 2", "T2"]
        )
        print(f"✅ 创建实体: {entity2}")

        # 测试创建关系
        relation = await neo4j.create_relationship(
            subject="测试实体1",
            predicate="位于",
            obj="测试实体2",
            relation_type="AT_LOCATION",
            properties={"weight": 1.0}
        )
        print(f"✅ 创建关系: 测试实体1 - 位于 - 测试实体2")

        # 测试搜索实体
        results = await neo4j.search_entities("测试实体", limit=5)
        print(f"✅ 搜索实体数量: {len(results)}")

        # 测试获取实体的关系
        rels = await neo4j.get_relationships("测试实体1")
        print(f"✅ 获取关系数量: {len(rels)}")

        # 测试 Chunk 关联
        chunk_link = await neo4j.link_chunk_to_entities(
            chunk_id="test_chunk_001",
            entity_names=["测试实体1", "测试实体2"],
            doc_id="test_doc_001"
        )
        print(f"✅ Chunk 关联到实体: {chunk_link}")

        # 测试获取 Chunk 的实体
        chunks = await neo4j.get_chunks_by_entity("测试实体1", limit=10)
        print(f"✅ 获取 Chunk 数量: {len(chunks)}")

        print("\n✅ Neo4j 测试通过")
        return True

    except Exception as e:
        print(f"\n❌ Neo4j 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        neo4j.close()
        print("\nNeo4j 连接已关闭")


async def test_milvus():
    """测试 Milvus 连接"""
    print("\n" + "="*60)
    print("Milvus 连接测试")
    print("="*60)

    try:
        from pymilvus import connections, utility

        print(f"Milvus URI: {config.MILVUS_URI}")
        print(f"Collection Name: {config.MILVUS_COLLECTION_NAME}")

        # 测试连接
        connections.connect(
            alias="default",
            uri=config.MILVUS_URI,
            token=config.MILVUS_TOKEN
        )
        print("✅ Milvus 连接成功")

        # 检查集合是否存在
        collection_name = config.MILVUS_COLLECTION_NAME
        if utility.has_collection(collection_name):
            print(f"✅ 集合 '{collection_name}' 已存在")
        else:
            print(f"⚠️ 集合 '{collection_name}' 不存在（需要先创建）")

        # 检查另一个集合
        chunk_collection = config.MILVUS_CHUNK_COLLECTION
        if utility.has_collection(chunk_collection):
            print(f"✅ 集合 '{chunk_collection}' 已存在")
        else:
            print(f"⚠️ 集合 '{chunk_collection}' 不存在（需要先创建）")

        # 关闭连接
        connections.disconnect("default")
        print("✅ Milvus 连接已关闭")

        print("\n✅ Milvus 连接测试通过")
        return True

    except Exception as e:
        print(f"\n❌ Milvus 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """运行所有测试"""
    print("\n" + "="*60)
    print("Phase 0 - 基础设施连接测试")
    print("="*60)

    results = {
        "PostgreSQL": await test_postgresql(),
        "Elasticsearch": await test_elasticsearch(),
        "Neo4j": await test_neo4j(),
        "Milvus": await test_milvus(),
    }

    print("\n" + "="*60)
    print("测试结果汇总")
    print("="*60)
    for name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{name}: {status}")

    all_passed = all(results.values())
    if all_passed:
        print("\n🎉 所有测试通过！")
    else:
        print("\n⚠️ 部分测试失败，请检查日志")

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
