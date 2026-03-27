"""
Phase 5 集成测试

全流程测试：
1. 摄入文档
2. submit_turn 对话
3. 检索返回
4. 话题结束
5. 异步归档
6. 新话题继续检索
"""
import asyncio
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.memory_service import MemoryService
from services.memory_package import RetrievalConfig
from services.ingestion_pipeline import IngestionPipeline
from services.session_manager import SessionManager, get_session_manager


async def test_full_workflow():
    """完整工作流测试"""
    print("\n" + "=" * 60)
    print("集成测试：完整工作流")
    print("=" * 60)

    # 清理旧的测试数据
    sm = get_session_manager()
    sm.delete_session("integration_test_session")
    sm.delete_session("integration_test_session_2")

    # ==================== Phase 1: 文档摄入 ====================
    print("\n[Phase 1] 文档摄入")
    print("-" * 40)

    pipeline = IngestionPipeline()

    doc_content = """
《红楼梦》人物关系简介

贾宝玉
贾宝玉是《红楼梦》的主人公，荣国府贾政与王夫人之次子。他性格风流多情，厌恶科举功名，与林黛玉青梅竹马。
贾宝玉衔玉而诞，故得名"宝玉"。他自幼与林黛玉情投意合，两人感情深厚。

林黛玉
林黛玉是贾宝玉的姑表妹，贾敏与林如海之女。她聪慧敏感，体弱多病，寄居在荣国府。
林黛玉与贾宝玉青梅竹马，情深意笃，但最终未能结合，在贾宝玉与薛宝钗成婚之夜病逝。

薛宝钗
薛宝钗是贾宝玉的姨表姐，薛姨妈之女。她端庄大方，识大体，最终与贾宝玉成婚。
薛宝钗虽与贾宝玉成婚，但贾宝玉心念林黛玉，最终出家。

王熙凤
王熙凤是贾琏之妻，荣国府的管家奶奶。她精明能干，心机深沉，是荣国府的实际管理者。
王熙凤在贾府中地位显赫，但也因过于精明而树敌众多。

贾母
贾母是荣国府的最高长辈，贾宝玉的祖母。她疼爱贾宝玉，对林黛玉也十分关爱。
贾母是贾府的核心人物，她的态度往往决定了贾府的重大决策。
    """.strip()

    result = await pipeline.ingest_document(
        text=doc_content,
        doc_id="integration_test_doc",
        doc_title="红楼梦人物关系",
        source_type="article",
    )
    pipeline.close()

    print(f"  Doc ID: {result['doc_id']}")
    print(f"  Chunks: {result['chunk_count']}")
    print(f"  Triples: {result['triple_count']}")
    print(f"  Summaries: {result['summary_count']}")

    # 等待索引完成
    print("  等待索引...")
    await asyncio.sleep(2)

    # ==================== Phase 2: 对话检索 ====================
    print("\n[Phase 2] 对话检索")
    print("-" * 40)

    service = MemoryService()

    try:
        # Turn 1
        print("\n  Turn 1: 贾宝玉是谁？")
        result1 = await service.submit_turn(
            session_id="integration_test_session",
            user_message="贾宝玉是谁？",
            assistant_response="贾宝玉是《红楼梦》的主人公，荣国府贾政与王夫人之次子。",
        )

        print(f"    Chunks: {len(result1.ranked_chunks)}")
        print(f"    Summaries: {len(result1.ranked_summaries)}")
        print(f"    Token estimate: {result1.token_estimate}")
        print(f"    Topic changed: {result1.topic_changed}")

        if result1.ranked_chunks:
            top_chunk = result1.ranked_chunks[0]
            print(f"    Top chunk score: {top_chunk.score:.4f}")
            print(f"    Top chunk text: {top_chunk.text_content[:60]}...")

        # Turn 2
        print("\n  Turn 2: 林黛玉呢？")
        result2 = await service.submit_turn(
            session_id="integration_test_session",
            user_message="林黛玉呢？",
            assistant_response="林黛玉是贾宝玉的姑表妹，聪慧敏感，体弱多病。",
        )

        print(f"    Chunks: {len(result2.ranked_chunks)}")
        print(f"    Topic changed: {result2.topic_changed}")

        # Turn 3 - 话题切换
        print("\n  Turn 3: 换个话题，天气怎么样？")
        result3 = await service.submit_turn(
            session_id="integration_test_session",
            user_message="好的，我们换个话题吧。今天天气怎么样？",
            assistant_response="抱歉，我无法获取实时天气信息。",
        )

        print(f"    Chunks: {len(result3.ranked_chunks)}")
        print(f"    Topic changed: {result3.topic_changed}")
        print(f"    Topic ID: {result3.topic_id}")

        # 等待异步归档
        print("    等待异步归档...")
        await asyncio.sleep(3)

        # ==================== Phase 3: 新话题继续 ====================
        print("\n[Phase 3] 新话题继续")
        print("-" * 40)

        # Turn 4 - 新话题
        print("\n  Turn 4: 王熙凤是谁？")
        result4 = await service.submit_turn(
            session_id="integration_test_session",
            user_message="王熙凤是谁？",
            assistant_response="王熙凤是贾琏之妻，荣国府的管家奶奶。",
        )

        print(f"    Chunks: {len(result4.ranked_chunks)}")
        print(f"    Topic changed: {result4.topic_changed}")
        if result4.pending_archive_summary:
            print(f"    Pending archive: {result4.pending_archive_summary[:60]}...")

        # ==================== Phase 4: 按 ID 获取 ====================
        print("\n[Phase 4] 按 ID 获取")
        print("-" * 40)

        if result1.extra_chunk_ids:
            print(f"  Extra IDs: {len(result1.extra_chunk_ids)}")
            chunks = await service.get_chunks_by_ids(result1.extra_chunk_ids[:3])
            print(f"  Fetched: {len(chunks)} chunks")
            for c in chunks:
                print(f"    - {c.chunk_id}: {c.text_content[:40]}...")

        # ==================== Phase 5: 逆向召回 ====================
        print("\n[Phase 5] 逆向召回")
        print("-" * 40)

        if result1.ranked_chunks:
            chunk_id = result1.ranked_chunks[0].chunk_id
            print(f"  Center chunk: {chunk_id}")
            adjacent = await service.get_adjacent_chunks(chunk_id, window=2)
            print(f"  Adjacent chunks: {len(adjacent)}")
            for c in adjacent:
                print(f"    - section={c.section_index}: {c.text_content[:40]}...")

        # ==================== Phase 6: Session 状态 ====================
        print("\n[Phase 6] Session 状态")
        print("-" * 40)

        state = await service.get_session_state("integration_test_session")
        if state:
            print(f"  Session ID: {state['session_id']}")
            print(f"  Status: {state['status']}")
            print(f"  Turn count: {len(state.get('turns', []))}")

        # ==================== Phase 7: 统计信息 ====================
        print("\n[Phase 7] 统计信息")
        print("-" * 40)

        stats = sm.get_stats()
        print(f"  Total sessions: {stats['total_sessions']}")
        print(f"  Active: {stats['active']}")
        print(f"  Topic ended: {stats['topic_ended']}")

        print("\n" + "=" * 60)
        print("集成测试通过!")
        print("=" * 60)

    finally:
        service.close()


async def test_rerank_connection():
    """测试 Rerank 连接"""
    print("\n" + "=" * 60)
    print("测试 Rerank 连接")
    print("=" * 60)

    from services.rerank_service import RerankService

    service = RerankService()
    try:
        result = await service.rerank(
            query="贾宝玉和林黛玉的关系",
            candidates=[
                {"text_content": "贾宝玉与林黛玉青梅竹马，情深意笃"},
                {"text_content": "今天天气真不错"},
                {"text_content": "王熙凤是荣国府的管家"},
            ],
            top_k=3,
        )

        print(f"Rerank 结果: {len(result)}")
        for r in result:
            print(f"  index={r.index}, score={r.score:.4f}")
        print("\nRerank 连接正常!")

    finally:
        await service.close()


async def main():
    print("=" * 60)
    print("Phase 5 集成测试")
    print("=" * 60)

    # 测试 Rerank
    await test_rerank_connection()

    # 完整工作流
    await test_full_workflow()

    print("\n全部测试完成!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Phase 5 集成测试")
    parser.add_argument("--rerank", action="store_true", help="只测试 Rerank")
    parser.add_argument("--workflow", action="store_true", help="只测试工作流")
    args = parser.parse_args()

    if args.rerank:
        asyncio.run(test_rerank_connection())
    elif args.workflow:
        asyncio.run(test_full_workflow())
    else:
        asyncio.run(main())
