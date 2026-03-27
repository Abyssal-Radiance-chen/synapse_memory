"""
Phase 1 数据摄入管道测试

测试内容：
1. 文档处理器 - 两阶段切分
2. Embedding 服务
3. 摄入管道 - 完整流程
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

from services.document_processor import DocumentProcessor, Chunk
from services.embedding_service import EmbeddingService


def test_document_processor():
    """测试文档处理器"""
    print("\n" + "="*60)
    print("文档处理器测试")
    print("="*60)

    processor = DocumentProcessor()

    # 测试文本（模拟红楼梦片段）
    test_text = """
第一回 甄士隐梦幻识通灵 贾雨村风尘怀闺秀

此开卷第一回也。作者自云：因曾历过一番梦幻之后，故将真事隐去，而借"通灵"之说，撰此《石头记》一书也。故曰"甄士隐"云云。

当日地陷东南，这东南一隅有处曰姑苏，有城曰阊门者，最是红尘中一二等富贵风流之地。

这阊门外有个十里街，街内有个仁清巷，巷内有个古庙，因地方窄狭，人皆呼作葫芦庙。庙旁住着一家乡宦，姓甄，名费，字士隐。嫡妻封氏，情性贤淑，深明礼义。家中虽不甚富贵，然本地便也推他为望族了。

只因这甄士隐禀性恬淡，不以功名为念，每日只以观花修竹、酌酒吟诗为乐，倒是神仙一流人品。只是一件不足：如今年已半百，膝下无儿，只有一女，乳名唤作英莲，年方三岁。

第二回 贾夫人仙逝扬州城 冷子兴演说荣国府

却说封肃因听见公差传唤，忙出来陪笑启问。那差人道："你女婿是那个？"封肃道："女婿姓贾，名化，字雨村，本系胡州人氏。"

雨村听说，忙作揖谢道："谬承紫誉，实不敢当。小侄因王兄说起，才知道老先生原是金陵人民。"
"""

    chunks = processor.process(test_text, "test_doc_001", "红楼梦测试文本")

    print(f"✅ 处理完成: {len(chunks)} 个 Chunk")

    for i, chunk in enumerate(chunks[:5]):  # 只显示前5个
        print(f"\n--- Chunk {i+1} ---")
        print(f"ID: {chunk.chunk_id}")
        print(f"Section: {chunk.section_name}")
        print(f"Hierarchy: {chunk.section_hierarchy}")
        print(f"Length: {chunk.char_count} chars")
        print(f"Content preview: {chunk.text_content[:100]}...")

    return len(chunks) > 0


async def test_embedding_service():
    """测试 Embedding 服务"""
    print("\n" + "="*60)
    print("Embedding 服务测试")
    print("="*60)

    service = EmbeddingService()

    # 测试单个文本
    text = "贾宝玉是《红楼梦》中的男主角，是荣国府的公子。"
    embedding = await service.embed_text(text)

    print(f"✅ 单文本 Embedding: 维度 {len(embedding)}")
    print(f"   前5个值: {embedding[:5]}")

    # 测试批量
    texts = [
        "林黛玉是贾母的外孙女，性格敏感多情。",
        "薛宝钗是薛姨妈的女儿，端庄大方。",
    ]
    embeddings = await service.embed_texts(texts)

    print(f"✅ 批量 Embedding: {len(embeddings)} 个向量")

    return len(embedding) > 0


async def test_ingestion_pipeline():
    """测试完整摄入管道"""
    print("\n" + "="*60)
    print("摄入管道测试（使用红楼梦第一章）")
    print("="*60)

    # 读取红楼梦文本
    hongloumeng_path = Path(__file__).parent.parent / "docs" / "hongloumeng.txt"

    if not hongloumeng_path.exists():
        print("⚠️ 未找到 hongloumeng.txt，跳过完整管道测试")
        return True

    with open(hongloumeng_path, 'r', encoding='utf-8') as f:
        content = f.read()

    print(f"读取文件: {len(content)} 字符")

    # 只测试前5000字符
    test_content = content[:5000]

    from services.ingestion_pipeline import ingest_text

    try:
        result = await ingest_text(
            text=test_content,
            doc_id="hongloumeng_ch1_test",
            doc_title="红楼梦第一章测试",
            source_type="article",
        )

        print(f"\n✅ 摄入完成:")
        print(f"   Doc ID: {result['doc_id']}")
        print(f"   Chunk 数量: {result['chunk_count']}")
        print(f"   Summary 数量: {result['summary_count']}")

        return result['status'] == 'success'

    except Exception as e:
        print(f"❌ 摄入失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """运行所有测试"""
    print("\n" + "="*60)
    print("Phase 1 数据摄入管道测试")
    print("="*60)

    results = {}

    # 1. 测试文档处理器
    results['document_processor'] = test_document_processor()

    # 2. 测试 Embedding 服务
    results['embedding_service'] = await test_embedding_service()

    # 3. 测试完整管道（需要数据库连接）
    results['ingestion_pipeline'] = await test_ingestion_pipeline()

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
