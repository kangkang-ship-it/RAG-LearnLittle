"""
BM25 稀疏检索 + RRF 融合

为知识库混合召回提供关键词检索能力：
- 中文按字符二元组切分（无需分词依赖），英文/数字按词切分
- BM25Okapi 打分（rank-bm25，numpy 向量化）
- 与向量检索结果做 RRF（Reciprocal Rank Fusion）融合

纯逻辑模块：不依赖 ChromaDB / LLM / DB，可直接单元测试。
"""

import hashlib
import re
from typing import Dict, List, Optional, Tuple

from rank_bm25 import BM25Okapi

# 中文连续串 / 英文数字词
_CJK_RUN_RE = re.compile(r'[一-鿿]+')
_ASCII_WORD_RE = re.compile(r'[a-zA-Z0-9_]+')


def tokenize_chinese_mixed(text: str) -> List[str]:
    """
    中英混合切词：
    - 英文/数字连续串 → 小写词
    - 中文连续串 → 字符二元组（单字保留单字）
    """
    tokens: List[str] = []
    for word in _ASCII_WORD_RE.findall(text):
        tokens.append(word.lower())
    for run in _CJK_RUN_RE.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def build_bm25_index(documents: List[str]) -> BM25Okapi:
    """用统一切词器构建 BM25 索引"""
    return BM25Okapi([tokenize_chinese_mixed(doc) for doc in documents])


def bm25_search(index: BM25Okapi, query: str, top_k: int) -> List[Tuple[int, float]]:
    """
    检索 Top-K。

    Returns:
        [(语料索引, BM25 分数), ...]，分数越高越相关；全零分（无词命中）返回空列表
    """
    scores = index.get_scores(tokenize_chinese_mixed(query))
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return [(i, float(scores[i])) for i in ranked[:top_k] if scores[i] > 0]


def _dedup_key(item: Dict) -> Tuple:
    """结果去重键：优先 document_id+chunk_index，其次 note_id，兜底 content MD5"""
    metadata = item.get("metadata") or {}
    if metadata.get("document_id") is not None and metadata.get("chunk_index") is not None:
        return ("doc", str(metadata["document_id"]), str(metadata["chunk_index"]))
    if metadata.get("note_id"):
        return ("note", str(metadata["note_id"]))
    content = item.get("content") or ""
    return ("content", hashlib.md5(content.encode()).hexdigest())


def rrf_merge(
    *ranked_lists: List[Dict],
    rrf_k: int = 60,
    top_k: Optional[int] = None,
) -> List[Dict]:
    """
    RRF 融合多路检索结果。

    每路结果按名次贡献 1/(rrf_k + rank)，同名次得分相加后降序返回；
    去重键相同的条目只保留首次出现的 dict（保留其原有字段，如 note_id）。
    """
    merged: Dict[Tuple, Dict] = {}
    scores: Dict[Tuple, float] = {}

    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            key = _dedup_key(item)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
            if key not in merged:
                merged[key] = item

    results = []
    for key, item in merged.items():
        result = dict(item)
        result["score"] = scores[key]
        results.append(result)

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k] if top_k else results
