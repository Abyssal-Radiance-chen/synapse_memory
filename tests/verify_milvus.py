"""
详细验证数据状态
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.pg_client import PGClient
from database.milvus_client import MilvusVectorClient
from services.embedding_service import EmbeddingService
import config


async def verify_all():
    print("=" * 60)
    print("详细数据验证")
    print("=" * 60)

    # PostgreSQL
    print("\n[PostgreSQL]")
    pg = PGClient()
    pg.connect()

    try:
        with pg.conn.cursor() as cur:
            cur.execute("SELECT doc_id, doc_title, chunk_count FROM documents")
            docs = cur.fetchall()
            for doc in docs:
                print(f"  Document: {doc[0]} - {doc[1]} ({doc[2]} chunks)")

            cur.execute("SELECT COUNT(*) FROM chunks")
            print(f"  Total Chunks: {cur.fetchone()[0]}")

            cur.execute("SELECT COUNT(*) FROM entity_relationships")
            print(f"  Total Relationships: {cur.fetchone()[0]}")

            cur.execute("SELECT COUNT(*) FROM entity_relationships WHERE chunk_id IS NOT NULL")
            print(f"  Relationships with chunk_id: {cur.fetchone()[0]}")

            cur.execute("SELECT COUNT(*) FROM summaries")
            print(f"  Total Summaries: {cur.fetchone()[0]}")
    finally:
        pg.close()

    # Milvus
    print("\n[Milvus]")
    milvus = MilvusVectorClient()
    milvus.connect()

    try:
        # 检查集合
        collections = milvus.client.list_collections()
        print(f"  Collections: {collections}")

        # 尝试查询 chunk_vectors
        try:
            result = milvus.client.query(
                collection_name=config.MILVUS_CHUNK_COLLECTION,
                filter="chunk_id != ''",
                limit=10,
                output_fields=["chunk_id", "doc_id"]
            )
            print(f"  Chunk vectors sample: {len(result)} records")
            if result:
                print(f"    Example: {result[0]}")
        except Exception as e:
            print(f"  Chunk query error: {e}")

        # 尝试查询 summary_vectors
        try:
            result = milvus.client.query(
                collection_name=config.MILVUS_SUMMARY_COLLECTION,
                filter="summary_id != ''",
                limit=10,
                output_fields=["summary_id", "doc_id"]
            )
            print(f"  Summary vectors sample: {len(result)} records")
            if result:
                print(f"    Example: {result[0]}")
        except Exception as e:
            print(f"  Summary query error: {e}")

    finally:
        milvus.close()

    # Embedding Service 测试
    print("\n[Embedding Service]")
    try:
        emb = EmbeddingService()
        test_embedding = await emb.embed_text("测试文本")
        if test_embedding:
            print(f"  Embedding dimension: {len(test_embedding)}")
            print(f"  Sample values: {test_embedding[:5]}")
        else:
            print("  Embedding failed!")
    except Exception as e:
        print(f"  Error: {e}")

    # 测试向量搜索
    print("\n[Vector Search Test]")
    try:
        milvus = MilvusVectorClient()
        milvus.connect()

        emb = EmbeddingService()
        query_vec = await emb.embed_text("贾宝玉林黛玉的故事")

        if query_vec:
            results = await milvus.search_chunks(query_vec, top_k=3)
            print(f"  Search results: {len(results)}")
            for r in results:
                print(f"    - {r['chunk_id']}: {r['text_content'][:50]}... (dist={r['distance']:.4f})")

        milvus.close()
    except Exception as e:
        print(f"  Search error: {e}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(verify_all())
