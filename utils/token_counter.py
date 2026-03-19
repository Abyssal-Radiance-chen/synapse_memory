"""
Token 计数工具
用于控制注入记忆的 token 限制
"""
import tiktoken


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """
    估算文本的 token 数

    Args:
        text: 输入文本
        model: 使用的模型（用于选择编码器）

    Returns:
        token 数量
    """
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")

    return len(enc.encode(text))


def truncate_to_tokens(text: str, max_tokens: int, model: str = "gpt-4") -> str:
    """
    截断文本到指定 token 数

    Args:
        text: 输入文本
        max_tokens: 最大token数
        model: 模型

    Returns:
        截断后的文本
    """
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")

    tokens = enc.encode(text)
    if len(tokens) <= max_tokens:
        return text

    return enc.decode(tokens[:max_tokens])
