"""
用量统计服务（P2-2 成本账单）

- seed_model_pricing: 启动时把 config/pricing.yaml 的价格种子进 model_pricing 表（upsert）
- get_usage_summary: 按用户/会话聚合调用次数、token、估算费用、平均延迟
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger_handler import logger
from app.models.model_trace import ModelTrace, ModelPricing
from app.utils.config import get_pricing_config


async def seed_model_pricing() -> None:
    """
    把 config/pricing.yaml 的模型定价写入 model_pricing 表（upsert）

    在应用启动时调用；失败仅告警，费用计算退化为 0（不影响业务链路）。
    """
    # 延迟导入，避免启动阶段循环依赖
    from app.db.database import async_session_factory

    pricing = get_pricing_config().get("models", {})
    if not pricing:
        logger.warning("config/pricing.yaml 无模型定价配置，费用计算将全部为 0")
        return

    try:
        async with async_session_factory() as db:
            for model, p in pricing.items():
                result = await db.execute(
                    select(ModelPricing).where(ModelPricing.model == model)
                )
                row = result.scalar_one_or_none()
                values = {
                    "input_price_per_1k": float(p.get("input_price_per_1k", 0)),
                    "output_price_per_1k": float(p.get("output_price_per_1k", 0)),
                    "currency": p.get("currency", "CNY"),
                }
                if row:
                    row.input_price_per_1k = values["input_price_per_1k"]
                    row.output_price_per_1k = values["output_price_per_1k"]
                    row.currency = values["currency"]
                else:
                    db.add(ModelPricing(model=model, **values))
            await db.commit()
        logger.info(f"模型定价种子完成: {len(pricing)} 个模型")
    except Exception as e:
        logger.warning(f"模型定价种子失败（费用计算将为 0）: {e}")


async def get_usage_summary(
    db: AsyncSession,
    user_id: str,
    session_id: Optional[str] = None,
    days: int = 30,
) -> dict:
    """
    聚合当前用户的模型调用用量与费用

    Args:
        db: 数据库会话
        user_id: 用户 ID（归属过滤）
        session_id: 可选，按会话过滤
        days: 统计天数（默认 30）

    Returns:
        {
            days, total_calls, total_prompt_tokens, total_completion_tokens,
            total_tokens, total_cost_cny, avg_latency_ms,
            by_stage: [{stage, calls, prompt_tokens, completion_tokens}],
            by_model: [{model, calls, cost_cny}],
        }
    """
    cutoff = datetime.now() - timedelta(days=days)
    conds = [ModelTrace.user_id == user_id, ModelTrace.created_at >= cutoff]
    if session_id:
        conds.append(ModelTrace.session_id == session_id)

    # 1. 总量（count / sum / avg）
    total_row = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(ModelTrace.prompt_tokens), 0),
                func.coalesce(func.sum(ModelTrace.completion_tokens), 0),
                func.coalesce(func.avg(ModelTrace.latency_ms), 0),
            ).where(*conds)
        )
    ).one()
    total_calls = int(total_row[0] or 0)
    total_prompt = int(total_row[1] or 0)
    total_completion = int(total_row[2] or 0)
    avg_latency_ms = round(float(total_row[3] or 0), 1)

    # 2. 按阶段分组
    stage_rows = (
        await db.execute(
            select(
                ModelTrace.stage,
                func.count(),
                func.coalesce(func.sum(ModelTrace.prompt_tokens), 0),
                func.coalesce(func.sum(ModelTrace.completion_tokens), 0),
            )
            .where(*conds)
            .group_by(ModelTrace.stage)
        )
    ).all()
    by_stage = [
        {
            "stage": stage,
            "calls": int(calls),
            "prompt_tokens": int(prompt_tok),
            "completion_tokens": int(comp_tok),
        }
        for stage, calls, prompt_tok, comp_tok in stage_rows
    ]

    # 3. 按模型分组（费用计算）
    model_rows = (
        await db.execute(
            select(
                ModelTrace.model,
                func.count(),
                func.coalesce(func.sum(ModelTrace.prompt_tokens), 0),
                func.coalesce(func.sum(ModelTrace.completion_tokens), 0),
            )
            .where(*conds)
            .group_by(ModelTrace.model)
        )
    ).all()

    # 4. 加载价格表，逐模型计算费用
    prices = {
        p.model: p
        for p in (await db.execute(select(ModelPricing))).scalars().all()
    }
    total_cost = 0.0
    by_model = []
    for model, calls, prompt_tok, comp_tok in model_rows:
        p = prices.get(model)
        if p:
            # SUM 返回 Decimal，需转 float 再与价格相乘
            cost = (
                float(prompt_tok) / 1000 * p.input_price_per_1k
                + float(comp_tok) / 1000 * p.output_price_per_1k
            )
        else:
            cost = 0.0  # 未配置价格（如 "unknown"），不计费
        total_cost += cost
        by_model.append({
            "model": model,
            "calls": int(calls),
            "cost_cny": round(cost, 4),
        })

    return {
        "days": days,
        "total_calls": total_calls,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
        "total_cost_cny": round(total_cost, 4),
        "avg_latency_ms": avg_latency_ms,
        "by_stage": by_stage,
        "by_model": by_model,
    }
