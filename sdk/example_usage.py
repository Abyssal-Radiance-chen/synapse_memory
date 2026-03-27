"""
Synapse Memory 使用示例

展示如何通过 SDK/API 接入系统
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdk.synapse_client import SynapseClient, submit_turn, ingest_document


async def example_basic_usage():
    """基础使用示例"""
    print("\n" + "=" * 60)
    print("示例 1: 基础使用")
    print("=" * 60)

    # 方式 1: 使用上下文管理器
    async with SynapseClient("http://localhost:8000") as client:
        # 健康检查
        health = await client.health_check()
        print(f"健康状态: {health['status']}")

        # 提交第一轮对话
        result1 = await client.submit_turn(
            session_id="demo_session_001",
            user_message="红楼梦里的贾宝玉是个什么样的人？",
            assistant_response="贾宝玉是《红楼梦》的主人公，性格风流多情，与林黛玉青梅竹马。",
        )

        print(f"\n--- Turn 1 ---")
        print(f"返回 {len(result1.ranked_chunks)} 个相关 Chunk")
        print(f"返回 {len(result1.ranked_summaries)} 个摘要")
        print(f"Token 估算: {result1.token_estimate}")

        if result1.ranked_chunks:
            print(f"Top Chunk: {result1.ranked_chunks[0].text_content[:100]}...")

        # 提交第二轮对话
        result2 = await client.submit_turn(
            session_id="demo_session_001",
            user_message="林黛玉呢？",
            assistant_response="林黛玉是贾宝玉的表妹，两人情投意合，但她体弱多病。",
        )

        print(f"\n--- Turn 2 ---")
        print(f"返回 {len(result2.ranked_chunks)} 个相关 Chunk")
        print(f"话题是否切换: {result2.topic_changed}")

        # 提交第三轮（模拟话题切换）
        result3 = await client.submit_turn(
            session_id="demo_session_001",
            user_message="好的，我们换个话题吧。今天天气怎么样？",
            assistant_response="抱歉，我无法获取实时天气信息。",
        )

        print(f"\n--- Turn 3 (话题切换) ---")
        print(f"话题是否切换: {result3.topic_changed}")
        if result3.topic_id:
            print(f"新话题 ID: {result3.topic_id}")
        if result3.pending_archive_summary:
            print(f"上一轮归档摘要: {result3.pending_archive_summary[:100]}...")


async def example_document_ingestion():
    """文档摄入示例"""
    print("\n" + "=" * 60)
    print("示例 2: 文档摄入")
    print("=" * 60)

    async with SynapseClient("http://localhost:8000") as client:
        # 摄入文档
        result = await client.ingest_document(
            doc_id="doc_example_001",
            doc_title="人工智能简介",
            text_content="""
人工智能（Artificial Intelligence，简称 AI）是计算机科学的一个分支，
旨在创建能够执行通常需要人类智能的任务的系统。这些任务包括学习、推理、
问题解决、感知和语言理解。

机器学习是人工智能的核心技术之一，它使计算机能够从数据中学习，
而无需明确编程。深度学习是机器学习的一个子集，使用神经网络来模拟人脑的工作方式。

自然语言处理（NLP）是 AI 的另一个重要领域，专注于计算机与人类语言之间的交互。
应用包括机器翻译、情感分析和聊天机器人等。
            """.strip(),
            source_type="article",
        )

        print(f"文档摄入结果:")
        print(f"  Doc ID: {result['doc_id']}")
        print(f"  Chunk 数量: {result['chunk_count']}")
        print(f"  消息: {result['message']}")

        # 现在可以检索这个文档
        search_result = await client.submit_turn(
            session_id="doc_search_session",
            user_message="什么是机器学习？",
            assistant_response="机器学习是 AI 的核心技术，让计算机从数据中学习。",
        )

        print(f"\n检索结果: {len(search_result.ranked_chunks)} 个 Chunk")


async def example_adjacent_chunks():
    """逆向召回示例"""
    print("\n" + "=" * 60)
    print("示例 3: 逆向召回")
    print("=" * 60)

    async with SynapseClient("http://localhost:8000") as client:
        # 先获取一些 chunks
        result = await client.submit_turn(
            session_id="adjacent_demo",
            user_message="贾宝玉和林黛玉",
            assistant_response="他们是青梅竹马。",
        )

        if result.ranked_chunks:
            chunk_id = result.ranked_chunks[0].chunk_id
            print(f"中心 Chunk ID: {chunk_id}")

            # 获取相邻 chunks
            adjacent = await client.get_adjacent_chunks(chunk_id, window=2)
            print(f"相邻 Chunks 数量: {len(adjacent)}")

            for i, c in enumerate(adjacent):
                print(f"  [{i}] section_index={c.section_index}: {c.text_content[:50]}...")


async def example_session_management():
    """Session 管理示例"""
    print("\n" + "=" * 60)
    print("示例 4: Session 管理")
    print("=" * 60)

    async with SynapseClient("http://localhost:8000") as client:
        session_id = "mgmt_demo_session"

        # 创建一些对话
        await client.submit_turn(
            session_id=session_id,
            user_message="你好",
            assistant_response="你好！有什么可以帮你的？",
        )

        # 获取 Session 状态
        state = await client.get_session_state(session_id)
        if state:
            print(f"Session ID: {state['session_id']}")
            print(f"状态: {state['status']}")
            print(f"对话轮次: {state['turn_count']}")

        # 获取系统统计
        stats = await client.get_stats()
        print(f"系统统计: {stats}")


async def example_convenience_functions():
    """便捷函数示例"""
    print("\n" + "=" * 60)
    print("示例 5: 便捷函数")
    print("=" * 60)

    # 使用便捷函数（不需要管理 client）
    result = await submit_turn(
        session_id="convenience_demo",
        user_message="红楼梦的作者是谁？",
        assistant_response="《红楼梦》的作者一般认为是曹雪芹。",
        base_url="http://localhost:8000",
        max_chunks=5,
    )

    print(f"返回 {len(result.ranked_chunks)} 个 Chunk")
    print(f"Token 估算: {result.token_estimate}")


async def example_full_workflow():
    """完整工作流示例"""
    print("\n" + "=" * 60)
    print("示例 6: 完整工作流")
    print("=" * 60)

    async with SynapseClient("http://localhost:8000") as client:
        session_id = "full_workflow_demo"

        # 1. 摄入文档
        print("1. 摄入文档...")
        await client.ingest_document(
            doc_id="workflow_doc",
            doc_title="红楼梦简介",
            text_content="""
《红楼梦》是中国古典四大名著之一，作者是曹雪芹。
小说以贾宝玉、林黛玉、薛宝钗的爱情故事为主线,描绘了贾府的兴衰史。

主要人物：
- 贾宝玉：主人公，性格风流多情
- 林黛玉：贾宝玉的表妹，体弱多病
- 薛宝钗：贾宝玉的表姐,端庄大方
- 王熙凤: 贾琏之妻,精明能干
            """.strip(),
        )
        print("  文档摄入完成")

        # 2. 开始对话
        print("\n2. 开始对话...")
        result1 = await client.submit_turn(
            session_id=session_id,
            user_message="请介绍一下红楼梦的主要人物",
            assistant_response="红楼梦的主要人物有贾宝玉、林黛玉、薛宝钗和王熙凤等。",
        )
        print(f"  返回 {len(result1.ranked_chunks)} 个相关 Chunk")

        # 3. 继续对话
        print("\n3. 继续对话...")
        result2 = await client.submit_turn(
            session_id=session_id,
            user_message="王熙凤是什么角色？",
            assistant_response="王熙凤是贾琏的妻子，荣国府的管家奶奶，精明能干。",
        )
        print(f"  返回 {len(result2.ranked_chunks)} 个相关 Chunk")

        # 4. 切换话题
        print("\n4. 切换话题...")
        result3 = await client.submit_turn(
            session_id=session_id,
            user_message="好的，我们换个话题。今天天气怎么样？",
            assistant_response="抱歉，我无法获取实时天气信息。",
        )
        print(f"  话题切换: {result3.topic_changed}")
        if result3.topic_id:
            print(f"  新话题 ID: {result3.topic_id}")

        # 5. 获取 Session 状态
        print("\n5. 获取 Session 状态...")
        state = await client.get_session_state(session_id)
        if state:
            print(f"  Session 状态: {state['status']}")
            print(f"  对话轮次: {state['turn_count']}")

        # 6. 开始新话题
        print("\n6. 开始新话题...")
        success = await client.start_new_topic(session_id)
        print(f"  开始新话题: {'成功' if success else '失败'}")

        # 7. 清理
        print("\n7. 清理 Session...")
        deleted = await client.delete_session(session_id)
        print(f"  删除 Session: {'成功' if deleted else '失败'}")


async def main():
    """运行所有示例"""
    print("=" * 60)
    print("Synapse Memory SDK 使用示例")
    print("=" * 60)

    try:
        await example_basic_usage()
        await example_document_ingestion()
        await example_adjacent_chunks()
        await example_session_management()
        await example_convenience_functions()
        await example_full_workflow()

        print("\n" + "=" * 60)
        print("所有示例完成!")
        print("=" * 60)

    except Exception as e:
        print(f"\n示例运行失败: {e}")
        print("请确保 Synapse Memory API 服务正在运行 (http://localhost:8000)")
        raise


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SDK 使用示例")
    parser.add_argument("--example", choices=[
        "basic", "ingest", "adjacent", "session", "convenience", "workflow"
    ], help="运行特定示例")
    args = parser.parse_args()

    if args.example == "basic":
        asyncio.run(example_basic_usage())
    elif args.example == "ingest":
        asyncio.run(example_document_ingestion())
    elif args.example == "adjacent":
        asyncio.run(example_adjacent_chunks())
    elif args.example == "session":
        asyncio.run(example_session_management())
    elif args.example == "convenience":
        asyncio.run(example_convenience_functions())
    elif args.example == "workflow":
        asyncio.run(example_full_workflow())
    else:
        asyncio.run(main())
