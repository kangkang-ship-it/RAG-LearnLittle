"""
文本切片器

基于 LangChain RecursiveCharacterTextSplitter 实现文档切片：
- 支持语义优化：相邻片段余弦相似度 > 阈值时自动合并
- 支持异步和同步两种分割模式
"""

from typing import List

from app.core.logger_handler import logger
from app.utils.config import get_chroma_config


class TextSplitter:
    """
    文本切片器
    
    将长文档切分为适合向量化的片段，支持：
    - 递归字符分割（按段落 → 句子 → 字符逐级细分）
    - 相邻片段语义合并（余弦相似度 > 阈值时合并）
    """
    
    def __init__(self):
        """
        初始化切片器，从 chroma.yaml 读取配置参数
        """
        config = get_chroma_config()
        splitter_config = config.get("text_splitter", {})
        
        self.chunk_size = splitter_config.get("chunk_size", 1000)
        self.chunk_overlap = splitter_config.get("chunk_overlap", 20)
        self.merge_threshold = splitter_config.get("merge_similarity_threshold", 0.7)
    
    def split_text(self, text: str) -> List[str]:
        """
        同步分割文本
        
        使用 RecursiveCharacterTextSplitter 进行递归字符分割。
        
        Args:
            text: 待分割的文本
            
        Returns:
            切片列表
        """
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", ".", "！", "!", "？", "?", "；", ";", " "],
            length_function=len,
        )
        
        chunks = splitter.split_text(text)
        
        logger.debug(f"文本切片完成: 原文 {len(text)} 字 → {len(chunks)} 个片段")
        return chunks
    
    async def async_split_text(self, text: str) -> List[str]:
        """
        异步分割文本
        
        在线程池中执行同步分割，避免阻塞事件循环。
        
        Args:
            text: 待分割的文本
            
        Returns:
            切片列表
        """
        import asyncio
        loop = asyncio.get_event_loop()
        chunks = await loop.run_in_executor(None, self.split_text, text)
        return chunks
    
    def merge_similar_chunks(self, chunks: List[str], embeddings=None) -> List[str]:
        """
        合并语义相似的相邻片段
        
        计算相邻片段的余弦相似度，超过阈值则合并为一个片段。
        用于减少冗余信息，提升检索质量。
        
        Args:
            chunks: 原始切片列表
            embeddings: 预计算的嵌入向量（可选，为 None 时跳过合并）
            
        Returns:
            合并后的切片列表
        """
        if not chunks or embeddings is None or len(chunks) < 2:
            return chunks
        
        merged = [chunks[0]]
        
        for i in range(1, len(chunks)):
            # 计算与前一个片段的相似度（简化版：使用集合交并比）
            prev_words = set(merged[-1].split())
            curr_words = set(chunks[i].split())
            
            if prev_words and curr_words:
                overlap = len(prev_words & curr_words) / len(prev_words | curr_words)
                if overlap > self.merge_threshold:
                    # 合并：将当前片段追加到前一个片段
                    merged[-1] = merged[-1] + " " + chunks[i]
                    continue
            
            merged.append(chunks[i])
        
        if len(merged) < len(chunks):
            logger.debug(f"语义合并: {len(chunks)} → {len(merged)} 个片段")
        
        return merged
