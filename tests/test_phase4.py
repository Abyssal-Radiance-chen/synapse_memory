"""
测试 Phase 4: 记忆服务核心
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.memory_service import MemoryService
from services.memory_package import RetrievalConfig
from services.session_manager import get_session_manager


async def test_session_manager():
    """测试 Session 管理"""
    print("\n" + "=" * 60)
    print("Test 1: Session Manager")
    print("=" * 60)

    from services.session_manager import SessionManager
    sm = SessionManager()

    # 创建 session
    session = sm.create_session("test_session_001")
    print(f"Created session: {session.session_id}")

    # 添加对话
    turn1 = sm.add_turn("test_session_001", "你好", "你好！有什么可以帮你的？")
    print(f"Added turn {turn1.turn_index}: {turn1.user_message}")

    turn2 = sm.add_turn("test_session_001", "红楼梦里贾宝玉是谁？", "贾宝玉是《红楼梦》的主人公...")
    print(f"Added turn {turn2.turn_index}: {turn2.user_message}")

    # 获取状态
    state = sm.get_session("test_session_001")
    print(f"Session state: {state.status}, turns: {len(state.turns)}")

    # 结束话题
    topic_id = sm.end_topic("test_session_001")
    print(f"Ended topic: {topic_id}")

    # 统计
    stats = sm.get_stats()
    print(f"Stats: {stats}")


async def test_submit_turn():
    """测试 submit_turn 接口"""
    print("\n" + "=" * 60)
    print("Test 2: submit_turn")
    print("=" * 60)

    service = MemoryService()

    try:
        # 第一轮对话
        print("\n--- Turn 1 ---")
        result1 = await service.submit_turn(
            session_id="test_session_002",
            user_message="红楼梦里的贾宝玉是个什么样的人？",
            assistant_response="贾宝玉是《红楼梦》的主人公，性格风流多情，与林黛玉青梅竹马。",
        )

        print(f"Chunks returned: {len(result1.ranked_chunks)}")
        print(f"Summaries returned: {len(result1.ranked_summaries)}")
        print(f"Topic changed: {result1.topic_changed}")
        print(f"Token estimate: {result1.token_estimate}")
        print(f"Total time: {result1.usage.total_time_ms:.1f}ms")

        if result1.ranked_chunks:
            print(f"Top chunk: {result1.ranked_chunks[0].text_content[:100]}...")

        # 第二轮对话
        print("\n--- Turn 2 ---")
        result2 = await service.submit_turn(
            session_id="test_session_002",
            user_message="林黛玉呢？",
            assistant_response="林黛玉是贾宝玉的表妹，两人情投意合，但她体弱多病。",
        )

        print(f"Chunks returned: {len(result2.ranked_chunks)}")
        print(f"Topic changed: {result2.topic_changed}")

        # 第三轮对话（模拟话题切换）
        print("\n--- Turn 3 (Topic Change) ---")
        result3 = await service.submit_turn(
            session_id="test_session_002",
            user_message="好的，我们换个话题吧。今天的天气怎么样？",
            assistant_response="抱歉，我无法获取实时天气信息。建议您查看天气应用。",
        )

        print(f"Chunks returned: {len(result3.ranked_chunks)}")
        print(f"Topic changed: {result3.topic_changed}")
        print(f"Topic ID: {result3.topic_id}")
        if result3.pending_archive_summary:
            print(f"Pending archive: {result3.pending_archive_summary[:100]}...")

    finally:
        service.close()


async def test_get_chunks_by_ids():
    """测试按 ID 获取 Chunk"""
    print("\n" + "=" * 60)
    print("Test 3: get_chunks_by_ids")
    print("=" * 60)

    service = MemoryService()

    try:
        # 先检索获取一些 chunk_id
        result = await service.submit_turn(
            session_id="test_session_003",
            user_message="贾宝玉和林黛玉的关系",
            assistant_response="他们青梅竹马，情投意合。",
        )

        if result.extra_chunk_ids:
            print(f"Got {len(result.extra_chunk_ids)} extra chunk IDs")

            # 按需获取
            chunks = await service.get_chunks_by_ids(result.extra_chunk_ids[:3])
            print(f"Fetched {len(chunks)} chunks by ID")

            for c in chunks:
                print(f"  - {c.chunk_id}: {c.text_content[:50]}...")
        else:
            print("No extra chunk IDs available")

    finally:
        service.close()


async def test_adjacent_chunks():
    """测试逆向召回"""
    print("\n" + "=" * 60)
    print("Test 4: get_adjacent_chunks")
    print("=" * 60)

    service = MemoryService()

    try:
        # 获取一个 chunk_id
        result = await service.submit_turn(
            session_id="test_session_004",
            user_message="荣国府",
            assistant_response="荣国府是《红楼梦》中的重要场景。",
        )

        if result.ranked_chunks:
            chunk_id = result.ranked_chunks[0].chunk_id
            print(f"Using chunk: {chunk_id}")

            # 获取相邻 chunk
            adjacent = await service.get_adjacent_chunks(chunk_id, window=2)
            print(f"Found {len(adjacent)} adjacent chunks")

            for c in adjacent:
                print(f"  - {c.chunk_id}: section={c.section_index}")

    finally:
        service.close()


async def test_retrieval_config():
    """测试检索配置"""
    print("\n" + "=" * 60)
    print("Test 5: RetrievalConfig")
    print("=" * 60)

    # 自定义配置
    config = RetrievalConfig(
        max_chunks=5,
        max_summaries=3,
        min_similarity=0.3,
        include_extra_ids=True,
    )

    print(f"Config: max_chunks={config.max_chunks}, max_summaries={config.max_summaries}")

    service = MemoryService(config=config)

    try:
        result = await service.submit_turn(
            session_id="test_session_005",
            user_message="王熙凤",
            assistant_response="王熙凤是荣国府的管家奶奶。",
            config=config,  # 使用自定义配置
        )

        print(f"Chunks: {len(result.ranked_chunks)} (max: {config.max_chunks})")
        print(f"Summaries: {len(result.ranked_summaries)} (max: {config.max_summaries})")

    finally:
        service.close()


async def main():
    print("=" * 60)
    print("Phase 4 记忆服务测试")
    print("=" * 60)

    # 1. Session 管理
    await test_session_manager()

    # 2. submit_turn 核心接口
    await test_submit_turn()

    # 3. 按 ID 获取
    await test_get_chunks_by_ids()

    # 4. 逆向召回
    await test_adjacent_chunks()

    # 5. 配置测试
    await test_retrieval_config()

    print("\n" + "=" * 60)
    print("Phase 4 测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Phase 4 测试")
    parser.add_argument("--session", action="store_true", help="只测 Session 管理")
    parser.add_argument("--submit", action="store_true", help="只测 submit_turn")
    parser.add_argument("--adjacent", action="store_true", help="只测逆向召回")
    args = parser.parse_args()

    if args.session:
        asyncio.run(test_session_manager())
    elif args.submit:
        asyncio.run(test_submit_turn())
    elif args.adjacent:
        asyncio.run(test_adjacent_chunks())
    else:
        asyncio.run(main())
