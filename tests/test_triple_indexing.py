"""
测试三元组索引功能
验证 chunk_id 和 doc_id 索引是否正确工作
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.pg_client import PGClient
from database.models import RelationshipCreate


async def test_triple_indexing():
    """测试三元组索引"""
    print("=" * 60)
    print("测试三元组索引功能")
    print("=" * 60)

    pg = PGClient()
    pg.connect()

    try:
        # 1. 创建测试关系（带 chunk_id 和 doc_id）
        print("\n1. 创建测试关系...")
        rel1 = RelationshipCreate(
            subject_entity="贾宝玉",
            object_entity="林黛玉",
            relation_type="青梅竹马",
            predicate="青梅竹马",
            chunk_id="doc_test_chunk_001",
            doc_id="doc_hongloumeng_001",
        )
        result1 = await pg.create_relationship(rel1)
        print(f"   [OK] 创建关系 1: {result1.get('subject_entity')} - {result1.get('relation_type')} - {result1.get('object_entity')}")
        print(f"      chunk_id: {result1.get('chunk_id')}, doc_id: {result1.get('doc_id')}")

        rel2 = RelationshipCreate(
            subject_entity="贾宝玉",
            object_entity="荣国府",
            relation_type="居住",
            predicate="居住",
            chunk_id="doc_test_chunk_002",
            doc_id="doc_hongloumeng_001",
        )
        result2 = await pg.create_relationship(rel2)
        print(f"   [OK] 创建关系 2: {result2.get('subject_entity')} - {result2.get('relation_type')} - {result2.get('object_entity')}")
        print(f"      chunk_id: {result2.get('chunk_id')}, doc_id: {result2.get('doc_id')}")

        # 2. 通过 chunk_id 查询关系（溯源）
        print("\n2. 通过 chunk_id 查询关系（溯源）...")
        chunk_rels = await pg.get_relationships_by_chunk("doc_test_chunk_001")
        print(f"   chunk_id='doc_test_chunk_001' 的关系数: {len(chunk_rels)}")
        for rel in chunk_rels:
            print(f"   - {rel['subject_entity']} | {rel['relation_type']} | {rel['object_entity']}")

        # 3. 通过 doc_id 查询关系网络
        print("\n3. 通过 doc_id 查询关系网络...")
        doc_rels = await pg.get_relationships_by_doc("doc_hongloumeng_001")
        print(f"   doc_id='doc_hongloumeng_001' 的关系数: {len(doc_rels)}")
        for rel in doc_rels:
            print(f"   - {rel['subject_entity']} | {rel['relation_type']} | {rel['object_entity']} (chunk: {rel.get('chunk_id')})")

        # 4. 通过实体查询关系
        print("\n4. 通过实体查询关系...")
        entity_rels = await pg.get_relationships_by_entity("贾宝玉")
        print(f"   实体='贾宝玉' 的关系数: {len(entity_rels)}")
        for rel in entity_rels:
            print(f"   - {rel['subject_entity']} | {rel['relation_type']} | {rel['object_entity']}")

        print("\n" + "=" * 60)
        print("[OK] 三元组索引测试完成！")
        print("=" * 60)

    except Exception as e:
        print(f"\n[FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        pg.close()


async def migrate_existing_table():
    """迁移现有表（添加 chunk_id 和 doc_id 列）"""
    print("检查是否需要迁移数据库表...")

    pg = PGClient()
    pg.connect()

    try:
        # 检查列是否存在
        with pg.conn.cursor() as cur:
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'entity_relationships'
                AND column_name IN ('chunk_id', 'doc_id')
            """)
            existing_cols = [row[0] for row in cur.fetchall()]

        if 'chunk_id' not in existing_cols:
            print("添加 chunk_id 列...")
            with pg.conn.cursor() as cur:
                cur.execute("ALTER TABLE entity_relationships ADD COLUMN chunk_id VARCHAR(255)")
            pg.conn.commit()
            print("[OK] chunk_id 列添加成功")

        if 'doc_id' not in existing_cols:
            print("添加 doc_id 列...")
            with pg.conn.cursor() as cur:
                cur.execute("ALTER TABLE entity_relationships ADD COLUMN doc_id VARCHAR(255)")
            pg.conn.commit()
            print("[OK] doc_id 列添加成功")

        # 删除旧的唯一约束，添加新的
        print("更新唯一约束...")
        try:
            with pg.conn.cursor() as cur:
                # 先删除旧约束
                cur.execute("""
                    ALTER TABLE entity_relationships
                    DROP CONSTRAINT IF EXISTS entity_relationships_subject_entity_object_entity_relation_type_key
                """)
                # 添加新约束
                cur.execute("""
                    ALTER TABLE entity_relationships
                    ADD CONSTRAINT entity_relationships_unique_triple_chunk
                    UNIQUE (subject_entity, object_entity, relation_type, chunk_id)
                """)
            pg.conn.commit()
            print("[OK] 唯一约束更新成功")
        except Exception as e:
            print(f"约束更新: {e}")
            pg.conn.rollback()

        # 添加索引
        print("添加索引...")
        try:
            with pg.conn.cursor() as cur:
                cur.execute("CREATE INDEX IF NOT EXISTS idx_entity_rels_chunk ON entity_relationships(chunk_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_entity_rels_doc ON entity_relationships(doc_id)")
            pg.conn.commit()
            print("[OK] 索引添加成功")
        except Exception as e:
            print(f"索引添加: {e}")
            pg.conn.rollback()

        print("\n[OK] 数据库迁移完成！")

    except Exception as e:
        print(f"[FAIL] 迁移失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        pg.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="三元组索引测试")
    parser.add_argument("--migrate", action="store_true", help="执行数据库迁移")
    args = parser.parse_args()

    if args.migrate:
        asyncio.run(migrate_existing_table())
    else:
        asyncio.run(test_triple_indexing())
