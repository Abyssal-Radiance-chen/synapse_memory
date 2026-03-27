"""
Phase 3 混合检索 + Rerank 测试

测试内容：
1. 查询拆解服务
2. ES 全文检索
3. 混合检索 + RRF 融合
4. Rerank 精排
5. 完整检索管道
"""
import asyncio
import sys
import os
import io
from pathlib import Path

# Windows UTF-8 编码
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_query_rewriter():
    """测试查询拆解服务"""
    print("\n" + "="*60)
    print("查询拆解服务测试")
    print("="*60)

    from services.query_rewriter import QueryRewriter

    rewriter = QueryRewriter()

    # 测试简单查询
    query = "贾宝玉和林黛玉的关系"
    print(f"原始查询: {query}")

    analysis = await rewriter.analyze(query)

    print(f"子查询: {analysis.sub_queries}")
    print(f"关键词: {analysis.keywords}")
    print(f"扩展词: {analysis.expanded_terms}")
    print(f"意图: {analysis.intent}")

    return len(analysis.keywords) > 0


async def test_es_retrieval():
    """测试 ES 全文检索"""
    print("\n" + "="*60)
    print("ES 全文检索测试")
    print("="*60)

    from services.es_retrieval import ESRetrievalService

    service = ESRetrievalService()

    # 测试 Chunk 检索
    query = "贾宝玉"
    print(f"查询: {query}")

    chunks = await service.search_chunks(query, top_k=5)
    print(f"✅ Chunk 检索结果: {len(chunks)} 个")

    for i, chunk in enumerate(chunks[:3]):
        print(f"  [{i+1}] {chunk.get('chunk_id', '')}: {chunk.get('text_content', '')[:50]}...")

    return True


async def test_hybrid_retrieval():
    """测试混合检索"""
    print("\n" + "="*60)
    print("混合检索 + RRF 融合测试")
    print("="*60)

    from services.hybrid_retrieval import HybridRetrievalService

    service = HybridRetrievalService()

    try:
        query = "林黛玉的性格特点"
        print(f"查询: {query}")

        results = await service.retrieve(query, top_k=10)

        print(f"✅ 混合检索结果: {len(results)} 个")

        for i, r in enumerate(results[:5]):
            print(f"  [{i+1}] 分数={r.final_score:.4f} | ES={r.es_score:.4f} | 摘要Vec={r.summary_vec_score:.4f} | ChunkVec={r.chunk_vec_score:.4f}")
            print(f"       {r.text_content[:60]}...")

        return len(results) > 0

    finally:
        service.close()


async def test_rerank():
    """测试 Rerank 精排"""
    print("\n" + "="*60)
    print("Rerank 精排测试")
    print("="*60)

    from services.rerank_service import RerankService

    service = RerankService()

    try:
        query = "贾宝玉喜欢谁"
        candidates = [
            {"text_content": "贾宝玉对林黛玉有着深厚的感情，两人青梅竹马。", "id": 1},
            {"text_content": "薛宝钗端庄大方，深得贾母喜爱。", "id": 2},
            {"text_content": "王熙凤是荣国府的管家，精明能干。", "id": 3},
            {"text_content": "林黛玉多愁善感，常为小事伤心。", "id": 4},
            {"text_content": "贾宝玉和薛宝钗成婚后，林黛玉郁郁而终。", "id": 5},
        ]

        print(f"查询: {query}")
        print(f"候选数: {len(candidates)}")

        results = await service.rerank(query, candidates, top_k=3)

        print(f"✅ Rerank 结果: {len(results)} 个")
        for i, r in enumerate(results):
            print(f"  [{i+1}] 分数={r.score:.4f}")
            print(f"       {r.content[:60]}...")

        return len(results) > 0

    finally:
        await service.close()


async def test_full_pipeline():
    """测试完整检索管道"""
    print("\n" + "="*60)
    print("完整检索管道测试")
    print("="*60)

    from services.hybrid_retrieval import HybridRetrievalService
    from services.rerank_service import RerankService

    hybrid_service = HybridRetrievalService()
    rerank_service = RerankService()

    try:
        query = "红楼梦中的爱情故事"
        print(f"查询: {query}")

        # 1. 混合检索
        candidates = await hybrid_service.retrieve(query, top_k=20)
        print(f"混合检索: {len(candidates)} 个候选")

        # 2. Rerank 精排
        candidate_dicts = [
            {
                "chunk_id": r.chunk_id,
                "text_content": r.text_content,
                "final_score": r.final_score,
            }
            for r in candidates
        ]

        reranked = await rerank_service.rerank(query, candidate_dicts, top_k=10)
        print(f"Rerank 精排: {len(reranked)} 个结果")

        # 3. 显示最终结果
        print("\n最终 Top-5 结果:")
        for i, r in enumerate(reranked[:5]):
            print(f"  [{i+1}] Rerank分数={r.score:.4f}")
            print(f"       {r.content[:80]}...")

        return len(reranked) > 0

    finally:
        hybrid_service.close()
        await rerank_service.close()


async def main():
    """运行所有测试"""
    print("\n" + "="*60)
    print("Phase 3 混合检索 + Rerank 测试")
    print("="*60)

    results = {}

    # 1. 查询拆解
    results['query_rewriter'] = await test_query_rewriter()

    # 2. ES 全文检索
    results['es_retrieval'] = await test_es_retrieval()

    # 3. 混合检索
    results['hybrid_retrieval'] = await test_hybrid_retrieval()

    # 4. Rerank
    results['rerank'] = await test_rerank()

    # 5. 完整管道
    results['full_pipeline'] = await test_full_pipeline()

    # 汇总
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
        print("\n⚠️ 部分测试失败")

    return all_passed


if __name__ == "__main__":
    asyncio.run(main())
