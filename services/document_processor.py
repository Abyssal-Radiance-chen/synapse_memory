"""
文档处理器 - 两阶段文档切分策略

阶段一：结构化预处理
  - 解析文档结构 → 章节栈 → 带层级信息的内容块

阶段二：智能分块
  - 长段落(>1536): 硬切分，1024字符 + 128重叠
  - 中段落(512-1024): 独立提交
  - 小段落(<512): 合并到缓冲区，超过1536时提交
"""
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from pathlib import Path

import config

logger = logging.getLogger(__name__)


# ========== 数据结构定义 ==========

@dataclass
class Section:
    """章节内容块"""
    title: str
    level: int  # 标题级别 (1, 2, 3...)
    content: str
    hierarchy: List[str] = field(default_factory=list)  # 完整层级路径
    section_index: int = 0  # 在文档中的顺序索引


@dataclass
class Chunk:
    """文本块"""
    chunk_id: str
    doc_id: str
    text_content: str
    section_name: str
    section_hierarchy: List[str]
    section_index: int
    paragraph_index: int
    sub_chunk_index: int
    char_count: int

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "text_content": self.text_content,
            "section_name": self.section_name,
            "section_hierarchy": self.section_hierarchy,
            "section_index": self.section_index,
            "paragraph_index": self.paragraph_index,
            "sub_chunk_index": self.sub_chunk_index,
            "char_count": self.char_count,
        }


# ========== 分块配置 ==========

# 硬切分阈值（超过此长度强制切分）
HARD_SPLIT_THRESHOLD = int(getattr(config, 'CHUNK_HARD_SPLIT', 1536))
# 独立块最小长度
INDEPENDENT_MIN = int(getattr(config, 'CHUNK_INDEPENDENT_MIN', 512))
# 独立块最大长度
INDEPENDENT_MAX = int(getattr(config, 'CHUNK_INDEPENDENT_MAX', 1024))
# 缓冲区最大长度
BUFFER_MAX = int(getattr(config, 'CHUNK_BUFFER_MAX', 1536))
# 重叠字符数
OVERLAP = int(getattr(config, 'CHUNK_OVERLAP', 128))


# ========== 阶段一：结构化预处理 ==========

class StructuralParser:
    """
    阶段一：结构化预处理器
    解析 TXT 文档结构，识别标题层级，生成带层级信息的章节内容块
    """

    # 常见标题模式
    TITLE_PATTERNS = [
        # Markdown 风格: # Title, ## Title
        r'^(#{1,6})\s+(.+)$',
        # 数字编号: 1. Title, 1.1 Title, 第一章
        r'^(\d+(?:\.\d+)*)\s*[\.、\s]\s*(.+)$',
        r'^第[一二三四五六七八九十百千]+[章节回]\s*(.*)$',
        # 中括号: [一]、【标题】
        r'^[【\[「『]\s*([^】\]」』]+)\s*[】\]」』]\s*$',
    ]

    def __init__(self, min_content_length: int = 50):
        self.min_content_length = min_content_length

    def parse(self, text: str, doc_title: str = "") -> List[Section]:
        """
        解析文档文本，返回章节列表

        Args:
            text: 文档原始文本
            doc_title: 文档标题（作为根层级）

        Returns:
            章节列表，每个章节包含层级信息和内容
        """
        lines = text.split('\n')
        sections = []
        section_stack = [(doc_title, 0)] if doc_title else []  # (title, level)

        current_content = []
        current_hierarchy = [doc_title] if doc_title else []
        current_level = 0
        section_index = 0

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                current_content.append(line)
                continue

            # 检测是否为标题
            title_match, title_level, title_text = self._detect_title(line_stripped)

            if title_match:
                # 保存前一个章节的内容
                if current_content:
                    content = '\n'.join(current_content).strip()
                    if len(content) >= self.min_content_length:
                        section_index += 1
                        sections.append(Section(
                            title=current_hierarchy[-1] if current_hierarchy else "",
                            level=current_level,
                            content=content,
                            hierarchy=current_hierarchy.copy(),
                            section_index=section_index,
                        ))

                # 更新章节栈
                self._update_stack(section_stack, title_text, title_level)
                current_hierarchy = [s[0] for s in section_stack]
                current_level = title_level
                current_content = []
            else:
                current_content.append(line)

        # 保存最后一个章节
        if current_content:
            content = '\n'.join(current_content).strip()
            if len(content) >= self.min_content_length:
                section_index += 1
                sections.append(Section(
                    title=current_hierarchy[-1] if current_hierarchy else "",
                    level=current_level,
                    content=content,
                    hierarchy=current_hierarchy.copy(),
                    section_index=section_index,
                ))

        logger.info(f"结构化解析完成: {len(sections)} 个章节")
        return sections

    def _detect_title(self, line: str) -> Tuple[bool, int, str]:
        """
        检测是否为标题行

        Returns:
            (is_title, level, title_text)
        """
        # Markdown 风格
        md_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if md_match:
            level = len(md_match.group(1))
            return True, level, md_match.group(2).strip()

        # 数字编号: 1. Title, 1.1 Title
        num_match = re.match(r'^(\d+(?:\.\d+)*)\s*[\.、\s]\s*(.+)$', line)
        if num_match:
            level = len(num_match.group(1).split('.'))
            return True, level, num_match.group(2).strip()

        # 中文章节: 第一章、第二节
        cn_match = re.match(r'^第([一二三四五六七八九十百千]+)[章节回]\s*(.*)$', line)
        if cn_match:
            return True, 1, line

        # 中括号标题
        bracket_match = re.match(r'^[【\[「『]\s*([^】\]」』]+)\s*[】\]」』]\s*$', line)
        if bracket_match:
            return True, 2, bracket_match.group(1).strip()

        # 单独一行较短且不以标点结尾，可能是标题
        if len(line) < 50 and not re.search(r'[。！？，、；：]$', line):
            # 检查下一行是否为空（标题通常后跟空行）
            return True, 3, line

        return False, 0, ""

    def _update_stack(self, stack: List[Tuple[str, int]], title: str, level: int):
        """更新章节栈"""
        # 弹出所有同级或更深级的章节
        while stack and stack[-1][1] >= level:
            stack.pop()
        stack.append((title, level))


# ========== 阶段二：智能分块 ==========

class SmartChunker:
    """
    阶段二：智能分块器
    基于缓冲区的合并/切分策略
    """

    def __init__(
        self,
        hard_split_threshold: int = HARD_SPLIT_THRESHOLD,
        independent_min: int = INDEPENDENT_MIN,
        independent_max: int = INDEPENDENT_MAX,
        buffer_max: int = BUFFER_MAX,
        overlap: int = OVERLAP,
    ):
        self.hard_split_threshold = hard_split_threshold
        self.independent_min = independent_min
        self.independent_max = independent_max
        self.buffer_max = buffer_max
        self.overlap = overlap

    def chunk_section(self, section: Section, doc_id: str) -> List[Chunk]:
        """
        对单个章节进行智能分块

        Args:
            section: 章节内容块
            doc_id: 文档ID

        Returns:
            Chunk 列表
        """
        # 按段落分割
        paragraphs = self._split_paragraphs(section.content)
        chunks = []
        buffer = []
        buffer_length = 0
        paragraph_index = 0

        for para in paragraphs:
            para_length = len(para)

            # 规则1: 长段落 > hard_split_threshold
            if para_length > self.hard_split_threshold:
                # 先提交缓冲区
                if buffer:
                    chunk = self._create_chunk_from_buffer(
                        buffer, section, doc_id, paragraph_index
                    )
                    chunks.append(chunk)
                    buffer = []
                    buffer_length = 0

                # 硬切分长段落
                sub_chunks, paragraph_index = self._hard_split(
                    para, section, doc_id, paragraph_index
                )
                chunks.extend(sub_chunks)

            # 规则2: 中段落 independent_min ~ independent_max
            elif self.independent_min <= para_length <= self.independent_max:
                # 先提交缓冲区
                if buffer:
                    chunk = self._create_chunk_from_buffer(
                        buffer, section, doc_id, paragraph_index
                    )
                    chunks.append(chunk)
                    buffer = []
                    buffer_length = 0

                # 该段落作为独立块
                chunk = Chunk(
                    chunk_id=f"{doc_id}_s{section.section_index}_p{paragraph_index}_c0",
                    doc_id=doc_id,
                    text_content=para,
                    section_name=section.title,
                    section_hierarchy=section.hierarchy,
                    section_index=section.section_index,
                    paragraph_index=paragraph_index,
                    sub_chunk_index=0,
                    char_count=para_length,
                )
                chunks.append(chunk)
                paragraph_index += 1

            # 规则3: 小段落 < independent_min
            else:
                # 检查是否会超过缓冲区上限
                if buffer_length + para_length > self.buffer_max:
                    # 提交当前缓冲区
                    if buffer:
                        chunk = self._create_chunk_from_buffer(
                            buffer, section, doc_id, paragraph_index
                        )
                        chunks.append(chunk)
                        buffer = []
                        buffer_length = 0

                # 添加到缓冲区
                buffer.append(para)
                buffer_length += para_length

        # 最终提交缓冲区残留
        if buffer:
            chunk = self._create_chunk_from_buffer(
                buffer, section, doc_id, paragraph_index
            )
            chunks.append(chunk)

        return chunks

    def _split_paragraphs(self, content: str) -> List[str]:
        """将内容分割为段落列表"""
        # 按连续空行分割
        paragraphs = re.split(r'\n\s*\n', content)
        # 过滤空段落并清理
        return [p.strip() for p in paragraphs if p.strip()]

    def _create_chunk_from_buffer(
        self,
        buffer: List[str],
        section: Section,
        doc_id: str,
        paragraph_index: int,
    ) -> Chunk:
        """从缓冲区创建 Chunk"""
        text = '\n\n'.join(buffer)
        return Chunk(
            chunk_id=f"{doc_id}_s{section.section_index}_p{paragraph_index}_c0",
            doc_id=doc_id,
            text_content=text,
            section_name=section.title,
            section_hierarchy=section.hierarchy,
            section_index=section.section_index,
            paragraph_index=paragraph_index,
            sub_chunk_index=0,
            char_count=len(text),
        )

    def _hard_split(
        self,
        text: str,
        section: Section,
        doc_id: str,
        start_para_idx: int,
    ) -> Tuple[List[Chunk], int]:
        """
        硬切分长文本

        按 1024 字符切分，带 128 字符重叠
        """
        chunks = []
        chunk_size = self.independent_max  # 1024
        overlap_size = self.overlap  # 128

        start = 0
        sub_idx = 0

        while start < len(text):
            end = start + chunk_size

            # 如果不是最后一块，尝试在句子边界切分
            if end < len(text):
                # 寻找最近的句子边界
                boundary = self._find_sentence_boundary(text, end - 50, end + 50)
                if boundary:
                    end = boundary

            chunk_text = text[start:end].strip()

            # 添加重叠
            if start > 0 and overlap_size > 0:
                # 从上一块的末尾取 overlap 字符
                prev_end = start
                prev_start = max(0, prev_end - overlap_size)
                overlap_text = text[prev_start:prev_end].strip()
                if overlap_text:
                    chunk_text = overlap_text + " " + chunk_text

            chunk = Chunk(
                chunk_id=f"{doc_id}_s{section.section_index}_p{start_para_idx}_c{sub_idx}",
                doc_id=doc_id,
                text_content=chunk_text,
                section_name=section.title,
                section_hierarchy=section.hierarchy,
                section_index=section.section_index,
                paragraph_index=start_para_idx,
                sub_chunk_index=sub_idx,
                char_count=len(chunk_text),
            )
            chunks.append(chunk)
            sub_idx += 1

            # 下一块的起始位置（考虑重叠）
            start = end - overlap_size if end < len(text) else len(text)

        return chunks, start_para_idx + 1

    def _find_sentence_boundary(self, text: str, min_pos: int, max_pos: int) -> Optional[int]:
        """在指定范围内寻找句子边界"""
        search_range = text[min_pos:max_pos]

        # 优先寻找句号、问号、感叹号
        for marker in ['。', '！', '？', '."', '!"', '?"', '. ', '! ', '? ']:
            pos = search_range.rfind(marker)
            if pos != -1:
                return min_pos + pos + len(marker)

        # 其次寻找逗号、分号
        for marker in ['，', '；', ',', ';']:
            pos = search_range.rfind(marker)
            if pos != -1:
                return min_pos + pos + 1

        return None


# ========== 主处理器 ==========

class DocumentProcessor:
    """
    文档处理器 - 整合两阶段处理
    """

    def __init__(self, overlap_size: int = 128):
        self.parser = StructuralParser()
        self.chunker = SmartChunker()
        self.overlap_size = overlap_size

    def process(self, text: str, doc_id: str, doc_title: str = "") -> List[Chunk]:
        """
        处理文档：解析 → 分块 → 添加重叠

        Args:
            text: 文档原始文本
            doc_id: 文档唯一标识
            doc_title: 文档标题

        Returns:
            Chunk 列表
        """
        # 阶段一：结构化解析
        sections = self.parser.parse(text, doc_title)

        # 阶段二：智能分块
        all_chunks = []
        for section in sections:
            chunks = self.chunker.chunk_section(section, doc_id)
            all_chunks.extend(chunks)

        # 阶段三：添加 chunk 之间的重叠（保证语义连贯）
        all_chunks = self._add_overlap(all_chunks)

        logger.info(f"文档处理完成: {doc_id} → {len(all_chunks)} 个 Chunk")
        return all_chunks

    def _add_overlap(self, chunks: List[Chunk]) -> List[Chunk]:
        """
        为每个 chunk 添加前一个 chunk 的末尾 overlap_size 字符

        保证语义连贯性
        """
        if len(chunks) <= 1:
            return chunks

        result = []
        for i, chunk in enumerate(chunks):
            if i == 0:
                # 第一个 chunk 不需要添加重叠
                result.append(chunk)
            else:
                # 获取前一个 chunk 的末尾 overlap_size 字符
                prev_text = chunks[i - 1].text_content
                overlap_text = prev_text[-self.overlap_size:] if len(prev_text) > self.overlap_size else prev_text

                # 创建新的 chunk，在前面添加重叠文本
                new_text = overlap_text + "\n---\n" + chunk.text_content
                new_chunk = Chunk(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    text_content=new_text,
                    section_name=chunk.section_name,
                    section_hierarchy=chunk.section_hierarchy,
                    section_index=chunk.section_index,
                    paragraph_index=chunk.paragraph_index,
                    sub_chunk_index=chunk.sub_chunk_index,
                    char_count=len(new_text),
                )
                result.append(new_chunk)

        return result

    def process_file(self, file_path: str, doc_id: str) -> List[Chunk]:
        """
        处理文件

        Args:
            file_path: 文件路径
            doc_id: 文档ID

        Returns:
            Chunk 列表
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 读取文件
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()

        # 从文件名提取标题
        doc_title = path.stem

        return self.process(text, doc_id, doc_title)
