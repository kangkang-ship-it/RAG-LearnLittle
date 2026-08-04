"""
用量统计响应模型（P2-2 成本账单）
"""

from pydantic import BaseModel


class StageUsage(BaseModel):
    """按阶段聚合的调用统计"""
    stage: str | None = None
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ModelUsage(BaseModel):
    """按模型聚合的调用统计与费用"""
    model: str | None = None
    calls: int = 0
    cost_cny: float = 0.0


class UsageSummaryResponse(BaseModel):
    """用量/费用汇总响应"""
    days: int
    total_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_cost_cny: float
    avg_latency_ms: float
    by_stage: list[StageUsage]
    by_model: list[ModelUsage]
