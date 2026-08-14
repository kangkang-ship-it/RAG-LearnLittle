"""
BM25 混合召回单元测试（纯逻辑，无 ChromaDB / DB / LLM 依赖）

覆盖：
- 中英混合切词（中文字符二元组 + 英文/数字词）
- BM25 索引构建与 Top-K 检索
- RRF 融合：去重、名次融合分、截断、字段保留
"""

from app.rag.bm25 import (
    tokenize_chinese_mixed,
    build_bm25_index,
    bm25_search,
    rrf_merge,
)


class TestTokenize:
    def test_chinese_run_to_bigrams(self):
        assert tokenize_chinese_mixed("机器学习") == ["机器", "器学", "学习"]

    def test_single_chinese_char(self):
        assert tokenize_chinese_mixed("中") == ["中"]

    def test_mixed_ascii_and_chinese(self):
        tokens = tokenize_chinese_mixed("Python3 语言处理")
        assert tokens == ["python3", "语言", "言处", "处理"]

    def test_empty_text(self):
        assert tokenize_chinese_mixed("") == []


class TestBm25Search:
    CORPUS = [
        "苹果香蕉橙子都很好吃",
        "机器学习是人工智能的核心分支",
        "今天天气很好",
    ]

    def test_hit_ranking(self):
        index = build_bm25_index(self.CORPUS)
        hits = bm25_search(index, "香蕉", top_k=3)
        assert hits, "应命中结果"
        assert hits[0][0] == 0, "含'香蕉'的文档应排第一"
        assert all(score > 0 for _, score in hits), "命中分数应为正"

    def test_no_hit_returns_empty(self):
        index = build_bm25_index(self.CORPUS)
        assert bm25_search(index, "量子计算机", top_k=3) == []

    def test_top_k_limit(self):
        index = build_bm25_index(self.CORPUS)
        # "天气" 仅出现在文档 2；两篇文档含"很好"类二元组不受影响
        hits = bm25_search(index, "天气", top_k=1)
        assert len(hits) == 1
        assert hits[0][0] == 2

    def test_single_char_query_no_bigram_hit(self):
        # 单字查询无法命中二元组索引，属预期行为（返回空）
        index = build_bm25_index(self.CORPUS)
        assert bm25_search(index, "很", top_k=3) == []


class TestRrfMerge:
    def _item(self, doc_id, chunk, content):
        return {
            "content": content,
            "metadata": {"document_id": doc_id, "chunk_index": chunk},
            "score": 0.9,
        }

    def test_merge_dedup_and_rank_scores(self):
        a = self._item(1, 0, "苹果香蕉")
        b = self._item(2, 0, "机器学习")
        list1 = [a, b]
        list2 = [a]  # a 在第二路也出现
        merged = rrf_merge(list1, list2, rrf_k=60, top_k=10)
        # 去重后只剩 2 条
        assert len(merged) == 2
        # a 的融合分 = 1/61(第一路第1名) + 1/61(第二路第1名)
        assert abs(merged[0]["score"] - (1 / 61 + 1 / 61)) < 1e-9
        assert merged[0]["content"] == "苹果香蕉"

    def test_top_k_truncation(self):
        items = [self._item(i, 0, f"doc{i}") for i in range(5)]
        merged = rrf_merge(items, top_k=3)
        assert len(merged) == 3
        assert merged[0]["content"] == "doc0"

    def test_empty_inputs(self):
        assert rrf_merge([], [], top_k=5) == []

    def test_single_list_fallback(self):
        items = [self._item(1, 0, "only")]
        merged = rrf_merge([], items, top_k=5)
        assert len(merged) == 1
        assert abs(merged[0]["score"] - 1 / 61) < 1e-9

    def test_preserves_extra_keys(self):
        note_item = {
            "content": "一条笔记",
            "metadata": {"note_id": "n1"},
            "note_id": "n1",
            "score": 0.8,
        }
        merged = rrf_merge([note_item], top_k=5)
        assert merged[0]["note_id"] == "n1"
