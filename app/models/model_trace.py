"""
模型调用 Trace 与定价数据模型（P2-2 成本账单）

对应 MySQL 表:
- model_traces: 每次 LLM 调用的结构化记录（事件数据来自 app/core/model_trace.py）
- model_pricing: 模型单价（元/1K tokens），启动时从 config/pricing.yaml 种子

model_traces 为高写入量日志表：
- 仅允许插入和按条件查询，无更新/删除操作
- 索引覆盖查询路径：按用户/会话 + 时间范围聚合
"""

from datetime import datetime

from sqlalchemy import (
    String, Text, DateTime, Integer, BigInteger, Float, Boolean, func, Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ModelTrace(Base):
    """
    单次 LLM 调用记录

    由 model_trace 回调在模型层统一写入（event=model_trace 的 JSON 行），
    经 DbSink 队列批量落库。字段与日志行字段一一对应。
    """
    __tablename__ = "model_traces"

    # 主键：自增 ID
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # 请求 ID（12 位 hex；后台任务可能为空）
    request_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    # 归属用户 / 会话（后台任务可能为空）
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # 调用阶段：classify / agent / plan_execute / title / summary
    stage: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # 模型名（可能为 "unknown"，见 model_trace._extract_model 兼容性风险）
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Token 用量（流式调用为 null，已知限制）
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 延迟（毫秒）/ 成败 / 错误信息
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 创建时间（服务端默认，聚合查询依据）
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # 按用户/时间聚合（usage summary 主路径）
        Index("idx_traces_user_created", "user_id", "created_at"),
        # 按会话/时间聚合
        Index("idx_traces_session_created", "session_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ModelTrace(id={self.id}, stage={self.stage}, model={self.model})>"


class ModelPricing(Base):
    """
    模型单价（元/1K tokens）

    启动时从 config/pricing.yaml 种子（upsert），费用计算按此表。
    """
    __tablename__ = "model_pricing"

    # 主键：自增 ID
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 模型名（与 ModelTrace.model 对应，唯一）
    model: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    # 每千 token 单价（元）
    input_price_per_1k: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    output_price_per_1k: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # 币种（默认 CNY）
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="CNY")

    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ModelPricing(model={self.model}, in={self.input_price_per_1k}, out={self.output_price_per_1k})>"
