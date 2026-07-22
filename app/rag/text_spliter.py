"""
文本切片器

实现文档切片的核心逻辑，支持：
- Markdown 结构感知分割：按标题层级切分章节，章节内再细切
- 文档类型区分：Markdown / 纯文本 / PDF 各自采用合适策略
- 真正语义合并：基于 embedding 余弦相似度合并相邻高度相似的片段
- 递归字符分割：按段落 → 句子 → 字符逐级细分（LangChain）
"""

import re
from dataclasses import dataclass
from typing import List, Tuple

from app.core.logger_handler import logger
from app.utils.config import get_chroma_config


@dataclass
class _Chunk:
    """切片数据（内部使用）"""
    content: str
    section_title: str = ""   # 所属章节标题，如 "## 安装指南"


class TextSplitter:
    """
    文本切片器

    根据文档类型自动选择最优分割策略：
    - Markdown：按 #/##/###/#### 标题切分章节，章节内再细切
    - 纯文本 / PDF：递归字符分割

    可选语义合并：基于 embedding 余弦相似度合并相邻的高度相似片段。
    """

    def __init__(self, embed_model=None):
        """
        初始化切片器

        Args:
            embed_model: 可选的 embedding 模型实例（用于语义合并）
        """
        config = get_chroma_config()
        splitter_config = config.get("text_splitter", {})

        self.chunk_size = splitter_config.get("chunk_size", 1000)
        self.chunk_overlap = splitter_config.get("chunk_overlap", 200)
        self.merge_threshold = splitter_config.get("merge_similarity_threshold", 0.85)
        self.embed_model = embed_model

    # ================================================================
    # 公开 API
    # ================================================================

    def split_text(self, text: str, doc_type: str = "txt") -> List[str]:
        """
        同步分割文本，返回纯文本切片列表（向后兼容）

        Args:
            text:     待分割的文本
            doc_type: 文档类型（"md" / "txt" / "pdf"）

        Returns:
            切片文本列表
        """
        chunks = self._split_by_type(text, doc_type)
        return [c.content if isinstance(c, _Chunk) else c for c in chunks]

    def split_with_sections(
        self, text: str, doc_type: str = "txt"
    ) -> Tuple[List[str], List[dict]]:
        """
        同步分割文本，返回切片内容及其章节元数据

        Args:
            text:     待分割的文本
            doc_type: 文档类型（"md" / "txt" / "pdf"）

        Returns:
            (contents, metadatas) 元组
            - contents:  切片文本列表
            - metadatas: 补充元数据（含 section_title / chunk_index）
        """
        chunks = self._split_by_type(text, doc_type)
        contents, metadatas = [], []

        for i, chunk in enumerate(chunks):
            if isinstance(chunk, _Chunk):
                contents.append(chunk.content)
                metadatas.append({
                    "section_title": chunk.section_title,
                    "chunk_index": i,
                })
            else:
                contents.append(chunk)
                metadatas.append({"section_title": "", "chunk_index": i})

        return contents, metadatas

    async def async_split_text(
        self, text: str, doc_type: str = "txt"
    ) -> List[str]:
        """异步分割文本（线程池包装，向后兼容）"""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.split_text, text, doc_type)

    async def async_split_with_sections(
        self, text: str, doc_type: str = "txt"
    ) -> Tuple[List[str], List[dict]]:
        """异步分割文本，返回内容及章节元数据"""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.split_with_sections, text, doc_type
        )

    def merge_similar_chunks(self, chunks: List[str]) -> List[str]:
        """
        使用 embedding 做真正的语义合并

        计算相邻片段的 embedding 余弦相似度，超过 merge_threshold 则合并。
        需要初始化时传入 embed_model，否则直接返回原列表。

        Args:
            chunks: 原始切片列表

        Returns:
            合并后的切片列表
        """
        if not chunks or len(chunks) < 2:
            return chunks

        if self.embed_model is None:
            logger.debug("未配置 embed_model，跳过语义合并")
            return chunks

        try:
            embeddings = self.embed_model.embed_documents(chunks)

            merged_texts = [chunks[0]]
            merged_embs = [embeddings[0]]

            for i in range(1, len(chunks)):
                sim = self._cosine_similarity(merged_embs[-1], embeddings[i])

                if sim >= self.merge_threshold:
                    merged_texts[-1] = merged_texts[-1] + "\n\n" + chunks[i]
                    # 合并后的 embedding 取移动平均
                    merged_embs[-1] = [
                        (a + b) / 2
                        for a, b in zip(merged_embs[-1], embeddings[i])
                    ]
                else:
                    merged_texts.append(chunks[i])
                    merged_embs.append(embeddings[i])

            if len(merged_texts) < len(chunks):
                logger.info(
                    f"语义合并: {len(chunks)} → {len(merged_texts)} 个片段 "
                    f"(阈值={self.merge_threshold})"
                )

            return merged_texts

        except Exception as e:
            logger.warning(f"语义合并失败，返回原始切片: {e}")
            return chunks

    # ================================================================
    # 文档类型路由
    # ================================================================

    def _split_by_type(self, text: str, doc_type: str) -> List:
        """
        根据文档类型选择分割策略

        Markdown 走结构感知分割；其他类型走通用递归字符分割。
        """
        doc_type = doc_type.lower().replace("text/", "")
        if doc_type in ("md", "markdown"):
            return self._split_markdown(text)
        return self._split_generic(text)

    # ================================================================
    # Markdown 结构感知分割
    # ================================================================

    # 匹配 Markdown 标题行：# 到 ####
    _HEADING_RE = re.compile(r'^(#{1,4})\s+(.+)$', re.MULTILINE)

    def _split_markdown(self, text: str) -> List[_Chunk]:
        """
        Markdown 结构感知分割

        步骤：
        1. 扫描所有 #/##/###/#### 标题行，将文档切分为逻辑章节
        2. 每个章节段落内用 RecursiveCharacterTextSplitter 细切
        3. 每个切片携带所属章节标题

        如果文档完全没有标题，退化为通用分割。
        """
        sections = self._parse_markdown_sections(text)

        if not sections:
            raw = self._split_generic(text)
            return [_Chunk(content=c) for c in raw]

        all_chunks: List[_Chunk] = []

        for sec in sections:
            section_text = text[sec["start"]:sec["end"]]
            if not section_text.strip():
                continue

            sub_chunks = self._split_generic(section_text)
            for sub in sub_chunks:
                content = sub.strip()
                if content:
                    all_chunks.append(_Chunk(
                        content=content,
                        section_title=sec["title"],
                    ))

        logger.debug(
            f"Markdown 分割完成: {len(sections)} 个章节 → {len(all_chunks)} 个片段"
        )
        return all_chunks

    def _parse_markdown_sections(self, text: str) -> List[dict]:
        """
        扫描 Markdown 标题行，将文本划分为章节区段

        Returns:
            [{"start": int, "end": int, "title": str, "level": int}, ...]
            title 格式如 "## 安装指南"
        """
        heading_positions = []  # [(char_position, level, title), ...]

        for m in self._HEADING_RE.finditer(text):
            level = len(m.group(1))
            title = m.group(2).strip()
            heading_positions.append((m.start(), level, title))

        if not heading_positions:
            return []

        sections = []
        for i, (pos, level, title) in enumerate(heading_positions):
            end = (
                heading_positions[i + 1][0]
                if i + 1 < len(heading_positions)
                else len(text)
            )
            sections.append({
                "start": pos,
                "end": end,
                "title": f"{'#' * level} {title}",
                "level": level,
            })

        # 如果正文在第一个标题之前，作为无标题前言
        if heading_positions and heading_positions[0][0] > 0:
            preamble = text[:heading_positions[0][0]].strip()
            if preamble:
                sections.insert(0, {
                    "start": 0,
                    "end": heading_positions[0][0],
                    "title": "",
                    "level": 0,
                })

        return sections

    # ================================================================
    # 通用递归字符分割
    # ================================================================

    def _split_generic(self, text: str) -> List[str]:
        """
        通用递归字符分割

        分隔符优先级从高到低：
        多空行 → 段落 → 换行 → 中文句号 → 英文句号+空格 →
        感叹号 → 问号 → 分号 → 逗号 → 空格（最终兜底）
        """
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=[
                "\n\n\n",           # 多空行分隔的章节
                "\n\n",             # 段落
                "\n",               # 单换行
                "。",               # 中文句号
                ". ",               # 英文句号 + 空格
                "！", "!",          # 感叹号
                "？", "?",          # 问号
                "；", ";",          # 分号
                "，", ",",          # 逗号
                " ",                # 空格（最终兜底）
            ],
            length_function=len,
        )

        chunks = splitter.split_text(text)
        logger.debug(f"通用分割: {len(text)} 字 → {len(chunks)} 个片段")
        return chunks

    # ================================================================
    # 工具方法
    # ================================================================

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """计算两个向量的余弦相似度"""
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0

        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = (sum(a * a for a in vec_a)) ** 0.5
        norm_b = (sum(b * b for b in vec_b)) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
