"""
Embedding 缓存 LRU 上限测试（生产风险分析·风险1）

验证：缓存无上限 → 加 LRU 淘汰后：
1. 超过 max_entries 时淘汰最久未使用的条目
2. 命中条目 move_to_end（保持 LRU 顺序，不被误淘汰）
"""

import hashlib

import pytest

from app.rag.vector_store import VectorStoreService


class FakeEmbedModel:
    """模拟 LangChain Embeddings（内容无关的确定性向量）"""

    async def aembed_documents(self, texts):
        return [[float(len(t))] * 8 for t in texts]


def _hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


@pytest.fixture
def service():
    vs = VectorStoreService()  # 单例（测试进程内首次创建）
    vs.embed_model = FakeEmbedModel()
    vs._embedding_cache.clear()
    # 用小上限验证淘汰逻辑
    vs._embedding_cache_max_entries = 5
    vs._embedding_cache_ttl = 300
    return vs


@pytest.mark.asyncio
async def test_cache_evicts_oldest_when_over_limit(service):
    await service._generate_embeddings([f"text-{i}" for i in range(6)])

    assert len(service._embedding_cache) == 5, "超出上限后应只保留 5 条"
    assert _hash("text-0") not in service._embedding_cache, "最旧的 text-0 应被淘汰"
    assert _hash("text-5") in service._embedding_cache, "最新的 text-5 应保留"


@pytest.mark.asyncio
async def test_cache_hit_keeps_entry_alive(service):
    # 写入 5 条填满缓存
    await service._generate_embeddings([f"text-{i}" for i in range(5)])

    # 命中 text-0 → move_to_end（成为最新）
    result = await service._generate_embeddings(["text-0"])
    assert result[0] == [6.0] * 8, "命中应返回缓存向量（'text-0' 长度为 6）"

    # 再写一条新文本 → 淘汰的应是最旧的 text-1，而非刚命中的 text-0
    await service._generate_embeddings(["text-new"])
    assert _hash("text-0") in service._embedding_cache, "刚命中的 text-0 不应被淘汰"
    assert _hash("text-1") not in service._embedding_cache, "最旧的 text-1 应被淘汰"
    assert len(service._embedding_cache) == 5
