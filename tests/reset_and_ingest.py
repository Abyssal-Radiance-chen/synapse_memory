"""
清空数据库并重新摄入红楼梦片段
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.pg_client import PGClient
from database.milvus_client import MilvusVectorClient
from services.ingestion_pipeline import IngestionPipeline
import config


async def clear_postgresql():
    """清空 PostgreSQL 数据"""
    print("\n[1] 清空 PostgreSQL...")
    pg = PGClient()
    pg.connect()

    try:
        with pg.conn.cursor() as cur:
            # 按依赖顺序删除
            tables = [
                "chunk_entities",
                "entity_relationships",
                "entities",
                "summaries",
                "chunks",
                "documents",
                "event_summaries",
                "conversation_history",
                "current_event_context",
                "rolling_summary_window",
                "character_profiles",
                "system_state",
            ]
            for table in tables:
                cur.execute(f"TRUNCATE TABLE {table} CASCADE")
                print(f"   - TRUNCATE {table}")
        pg.conn.commit()
        print("[OK] PostgreSQL 清空完成")
    except Exception as e:
        print(f"[FAIL] PostgreSQL 清空失败: {e}")
        pg.conn.rollback()
    finally:
        pg.close()


async def clear_milvus():
    """清空 Milvus 向量"""
    print("\n[2] 清空 Milvus...")
    milvus = MilvusVectorClient()
    milvus.connect()

    try:
        # 删除集合并重建
        for collection in [config.MILVUS_CHUNK_COLLECTION, config.MILVUS_SUMMARY_COLLECTION]:
            try:
                milvus.client.drop_collection(collection)
                print(f"   - DROP {collection}")
            except Exception:
                pass

        # 重新初始化
        milvus.init_collections()
        print("[OK] Milvus 清空完成")
    except Exception as e:
        print(f"[FAIL] Milvus 清空失败: {e}")
    finally:
        milvus.close()


async def ingest_hongloumeng():
    """摄入红楼梦片段"""
    print("\n[3] 摄入红楼梦片段...")

    # 查找红楼梦文件
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 尝试多个可能的位置
    possible_paths = [
        os.path.join(base_dir, "docs", "hongloumeng.txt"),
        os.path.join(base_dir, "data", "hongloumeng_chapters.txt"),
        "docs/hongloumeng.txt",
        "data/hongloumeng_chapters.txt",
    ]

    hongloumeng_file = None
    for path in possible_paths:
        if os.path.exists(path):
            hongloumeng_file = path
            break

    if not hongloumeng_file:
        print(f"[FAIL] 找不到红楼梦文件，尝试过: {possible_paths}")
        return None

    print(f"   找到文件: {hongloumeng_file}")

    pipeline = IngestionPipeline()
    try:
        result = await pipeline.ingest_file(
            file_path=hongloumeng_file,
            doc_id="hongloumeng_ch1_5",
            use_es=False,  # ES 可选
        )
        print(f"\n[OK] 摄入完成!")
        print(f"   - 文档ID: {result['doc_id']}")
        print(f"   - Chunk数: {result['chunk_count']}")
        print(f"   - 三元组数: {result['triple_count']}")
        print(f"   - 摘要数: {result['summary_count']}")
        return result
    except Exception as e:
        print(f"[FAIL] 摄入失败: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        pipeline.close()


async def verify_data():
    """验证数据"""
    print("\n[4] 验证数据...")

    pg = PGClient()
    pg.connect()
    milvus = MilvusVectorClient()
    milvus.connect()

    try:
        # PostgreSQL 统计
        with pg.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM documents")
            doc_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM chunks")
            chunk_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM entity_relationships")
            rel_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM summaries")
            summary_count = cur.fetchone()[0]

            # 检查三元组是否有 chunk_id 和 doc_id
            cur.execute("""
                SELECT COUNT(*) FROM entity_relationships
                WHERE chunk_id IS NOT NULL AND doc_id IS NOT NULL
            """)
            indexed_rel_count = cur.fetchone()[0]

        print(f"\n   PostgreSQL:")
        print(f"   - Documents: {doc_count}")
        print(f"   - Chunks: {chunk_count}")
        print(f"   - Relationships: {rel_count} (带索引: {indexed_rel_count})")
        print(f"   - Summaries: {summary_count}")

        # Milvus 统计
        try:
            chunk_stats = milvus.client.get_collection_stats(config.MILVUS_CHUNK_COLLECTION)
            summary_stats = milvus.client.get_collection_stats(config.MILVUS_SUMMARY_COLLECTION)

            # 解析统计
            chunk_count_milvus = 0
            summary_count_milvus = 0

            if hasattr(chunk_stats, 'row_count'):
                chunk_count_milvus = chunk_stats.row_count
            if hasattr(summary_stats, 'row_count'):
                summary_count_milvus = summary_stats.row_count

            print(f"\n   Milvus:")
            print(f"   - Chunk vectors: {chunk_count_milvus}")
            print(f"   - Summary vectors: {summary_count_milvus}")
        except Exception as e:
            print(f"   Milvus 统计获取失败: {e}")

        # 显示几个三元组示例
        print(f"\n   三元组示例 (前5条):")
        with pg.conn.cursor() as cur:
            cur.execute("""
                SELECT subject_entity, relation_type, object_entity, chunk_id
                FROM entity_relationships
                WHERE chunk_id IS NOT NULL
                LIMIT 5
            """)
            for row in cur.fetchall():
                print(f"   - {row[0]} | {row[1]} | {row[2]} (chunk: {row[3][:30]}...)")

        print("\n[OK] 验证完成!")

    except Exception as e:
        print(f"[FAIL] 验证失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        pg.close()
        milvus.close()


async def main():
    print("=" * 60)
    print("清空数据库并重新摄入红楼梦")
    print("=" * 60)

    # 1. 清空 PostgreSQL
    await clear_postgresql()

    # 2. 清空 Milvus
    await clear_milvus()

    # 3. 摄入红楼梦
    result = await ingest_hongloumeng()

    # 4. 验证数据
    await verify_data()

    print("\n" + "=" * 60)
    print("全部完成!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
