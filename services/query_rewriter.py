"""
查询拆解与重写服务

功能：
1. 多意图拆解 - 将复杂查询拆解为多个子查询
2. 查询扩展 - 添加同义词、相关词
3. 关键词提取 - 提取核心关键词用于 BM25
"""
import asyncio
import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from services.llm_client import LLMClient
from config import ModelConfig, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL_QUERY, LLM_VERIFY_SSL

logger = logging.getLogger(__name__)


@dataclass
class QueryAnalysis:
    """查询分析结果"""
    original_query: str
    sub_queries: List[str]  # 拆解后的子查询
    keywords: List[str]  # 核心关键词
    expanded_terms: List[str]  # 扩展词
    intent: str  # 意图类型 (search/qa/compare/summarize)


class QueryRewriter:
    """
    查询拆解与重写服务

    使用 LLM 进行智能查询分析和拆解
    """

    def __init__(self):
        self.llm_client = LLMClient(ModelConfig(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            model=LLM_MODEL_QUERY,
            verify_ssl=LLM_VERIFY_SSL,
        ))

        self.system_prompt = """你是一个专业的查询分析助手。请分析用户的查询，并按照以下格式输出：

1. 如果查询包含多个意图，将其拆解为多个独立的子查询
2. 提取查询中的核心关键词（用于全文检索）
3. 添加相关的扩展词（同义词、近义词）
4. 判断查询意图类型

请严格按照以下 JSON 格式输出：
{
    "sub_queries": ["子查询1", "子查询2"],
    "keywords": ["关键词1", "关键词2"],
    "expanded_terms": ["扩展词1", "扩展词2"],
    "intent": "search/qa/compare/summarize"
}

注意：
- sub_queries 最多 3 个
- keywords 最多 5 个
- expanded_terms 最多 5 个
- intent 只能是 search、qa、compare、summarize 之一"""

    async def analyze(self, query: str) -> QueryAnalysis:
        """
        分析并拆解查询

        Args:
            query: 原始查询

        Returns:
            QueryAnalysis: 查询分析结果
        """
        try:
            content, usage = await self.llm_client.simple_complete(
                self.system_prompt,
                f"用户查询：{query}"
            )

            # 解析 JSON
            import json
            # 提取 JSON 部分
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = {}

            return QueryAnalysis(
                original_query=query,
                sub_queries=data.get("sub_queries", [query]),
                keywords=data.get("keywords", self._extract_keywords_simple(query)),
                expanded_terms=data.get("expanded_terms", []),
                intent=data.get("intent", "search"),
            )

        except Exception as e:
            logger.error(f"查询分析失败: {e}")
            # 降级处理：返回原始查询
            return QueryAnalysis(
                original_query=query,
                sub_queries=[query],
                keywords=self._extract_keywords_simple(query),
                expanded_terms=[],
                intent="search",
            )

    def _extract_keywords_simple(self, query: str) -> List[str]:
        """
        简单的关键词提取（降级方案）
        使用规则提取，不依赖 LLM
        """
        # 移除常见停用词
        stopwords = {"的", "是", "在", "有", "和", "了", "不", "这", "我", "你", "他", "她", "它"}

        # 分词（简单按空格和标点）
        words = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', query)

        # 过滤停用词和短词
        keywords = [w for w in words if w not in stopwords and len(w) >= 2]

        return keywords[:5]

    async def rewrite_for_retrieval(self, query: str) -> List[str]:
        """
        为检索重写查询

        Returns:
            用于检索的查询列表（包含原始查询 + 拆解后的子查询）
        """
        analysis = await self.analyze(query)

        # 合并原始查询和子查询
        queries = [query] + [sq for sq in analysis.sub_queries if sq != query]

        # 去重
        return list(dict.fromkeys(queries))

    async def get_search_keywords(self, query: str) -> List[str]:
        """
        获取用于 BM25 检索的关键词

        Returns:
            关键词列表（包含扩展词）
        """
        analysis = await self.analyze(query)

        # 合并关键词和扩展词
        all_terms = analysis.keywords + analysis.expanded_terms

        # 去重
        return list(dict.fromkeys(all_terms))


# 便捷函数
async def rewrite_query(query: str) -> QueryAnalysis:
    """便捷函数：分析查询"""
    rewriter = QueryRewriter()
    return await rewriter.analyze(query)
