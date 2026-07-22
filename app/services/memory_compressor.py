"""
对话记忆压缩模块

在 token 预算约束下，对全量历史执行：
1. 滑动窗口截断：保留最近 N 轮原文
2. 里程碑摘要拼接：将已有摘要注入为 SystemMessage
3. 增量摘要生成：对超出窗口的旧消息调用 LLM 压缩

核心类：
- MemoryCompressor: 构建压缩后的消息上下文
- check_and_summarize: 异步检查并触发摘要生成
"""

from typing import List, Tuple, Optional

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage

from app.core.logger_handler import logger
from app.services.token_budget import TokenBudget, TokenCounter


# ========== 摘要生成 Prompt ==========

SUMMARY_PROMPT = """你是一个对话摘要助手。请阅读以下信息，生成一段简洁的结构化摘要。

## 已有的历史摘要
{existing_summary}

## 新增的对话片段（需要融合到摘要中）
{new_messages}

## 要求
1. 融合已有摘要和新对话，生成新的完整摘要
2. 重点保留以下类型的信息：
   - **关键决策**：用户做了什么技术/业务决策
   - **用户偏好**：用户表达过的喜好、习惯、要求
   - **未完成任务**：对话中提到但尚未完成的事项
   - **重要事实**：用户提供的关键信息
   - **上下文延续**：可能需要跨轮次引用的信息
3. 摘要长度控制在 500 字以内
4. 使用中文
5. 仅输出摘要文本，不要加任何前缀或解释"""


# ========== MemoryCompressor ==========

class MemoryCompressor:
    """
    对话记忆压缩器
    
    在 token 预算约束下，对全量历史执行：
    1. 滑动窗口截断：保留最近 N 轮原文
    2. 摘要拼接：将已有摘要注入为 SystemMessage
    """
    
    def __init__(self, budget: TokenBudget, counter: TokenCounter = None):
        self.budget = budget
        self.counter = counter or TokenCounter()
    
    def build_context(
        self,
        all_messages: list,
        existing_summary: str = "",
        token_quota: int = None,
    ) -> Tuple[List[BaseMessage], int]:
        """
        构建压缩后的消息上下文
        
        策略：
        1. 先计算摘要占用的 token
        2. 从最新消息向前遍历，逐条累计 token
        3. 超出配额时停止
        
        Args:
            all_messages: 全量消息列表 [{"role": "user/assistant", "content": "..."}]
            existing_summary: 已有的里程碑摘要文本
            token_quota: 历史消息可用 token 配额（None 则使用 budget 默认值）
            
        Returns:
            (消息列表, 已用 token 数)
        """
        quota = token_quota or self.budget.available_for_history
        messages: list[BaseMessage] = []
        used_tokens = 0
        
        # Step 1: 注入已有摘要（如果有）
        if existing_summary:
            summary_text = self._truncate_summary(existing_summary)
            summary_tokens = self.counter.count(summary_text)
            if summary_tokens <= self.budget.summary_max:
                messages.append(SystemMessage(
                    content=f"[历史对话摘要]\n{summary_text}"
                ))
                used_tokens += summary_tokens
                quota -= summary_tokens
        
        # Step 2: 滑动窗口填充（从最新向最旧）
        window_messages: list[BaseMessage] = []
        window_tokens = 0
        
        # 反转消息列表，从最新开始处理
        for msg in reversed(all_messages):
            content = msg.get("content", "") if isinstance(msg, dict) else ""
            msg_tokens = self.counter.count(content)
            
            # 检查是否超出配额
            if window_tokens + msg_tokens > quota and window_tokens > 0:
                break
            
            # 转换角色
            role = msg.get("role", "") if isinstance(msg, dict) else ""
            if role == "user":
                window_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                window_messages.append(AIMessage(content=content))
            else:
                continue  # 跳过未知角色
            
            window_tokens += msg_tokens
        
        # 反转回正序（时间升序）
        window_messages.reverse()
        messages.extend(window_messages)
        used_tokens += window_tokens
        
        logger.debug(
            f"记忆压缩完成: quota={token_quota}, used={used_tokens}, "
            f"window_msgs={len(window_messages)}, has_summary={bool(existing_summary)}"
        )
        return messages, used_tokens
    
    def _truncate_summary(self, summary: str) -> str:
        """确保摘要文本不超出 token 上限"""
        tokens = self.counter.count(summary)
        if tokens <= self.budget.summary_max:
            return summary
        
        # 按字符比例截断（粗略估算）
        ratio = self.budget.summary_max / max(1, tokens)
        max_chars = int(len(summary) * ratio)
        truncated = summary[:max_chars]
        
        # 在句号后截断（保留完整性）
        last_period = max(truncated.rfind("。"), truncated.rfind("."), truncated.rfind("\n"))
        if last_period > len(truncated) // 2:
            truncated = truncated[:last_period + 1]
        
        return truncated


# ========== 增量摘要生成 ==========

async def generate_incremental_summary(
    chat_model,
    session_id: str,
    existing_summary: str,
    new_messages: list,
    last_msg_id: int,
) -> str:
    """
    生成增量摘要并持久化
    
    流程：
    1. 用 LLM 融合已有摘要 + 新消息块
    2. 写入 / 更新 chat_summaries 表
    3. 返回新摘要文本
    
    Args:
        chat_model: LLM 模型实例
        session_id: 会话 ID
        existing_summary: 已有的摘要文本
        new_messages: 新被压缩的消息块 [{"role": ..., "content": ...}]
        last_msg_id: 新摘要覆盖到的最后一条消息 ID
        
    Returns:
        新摘要文本
    """
    # 格式化新消息
    formatted = []
    for msg in new_messages:
        role_label = "用户" if msg.get("role") == "user" else "助手"
        content = msg.get("content", "")[:300]  # 每条截断到 300 字
        formatted.append(f"[{role_label}]: {content}")
    
    # 构建 prompt
    prompt = SUMMARY_PROMPT.format(
        existing_summary=existing_summary or "（暂无历史摘要）",
        new_messages="\n\n".join(formatted),
    )
    
    # 调用 LLM 生成摘要
    try:
        from langchain_core.messages import HumanMessage as HMsg
        response = await chat_model.ainvoke([HMsg(content=prompt)])
        new_summary = response.content.strip() if hasattr(response, "content") else str(response).strip()
    except Exception as e:
        logger.warning(f"LLM 摘要生成失败: {e}")
        return existing_summary  # 失败时保留旧摘要
    
    # 持久化到数据库
    try:
        from app.db.database import async_session_factory
        from app.services.database_session_manager import DatabaseSessionManager
        
        mgr = DatabaseSessionManager()
        async with async_session_factory() as db:
            await mgr.update_summary(db, session_id, new_summary, last_msg_id)
            await db.commit()
    except Exception as e:
        logger.warning(f"摘要持久化失败: {e}")
    
    return new_summary


# ========== 摘要检查触发 ==========

async def check_and_summarize(
    chat_model,
    session_id: str,
    threshold: int = 40,
    min_interval: int = 20,
) -> None:
    """
    检查是否需要生成摘要，如需要则异步执行
    
    判断条件：
    1. 消息总数 > threshold
    2. 距上次摘要后新增消息数 > min_interval
    3. 摘要未被冻结
    
    Args:
        chat_model: LLM 模型实例
        session_id: 会话 ID
        threshold: 触发摘要的消息数阈值
        min_interval: 两次摘要之间的最小间隔（消息数）
    """
    try:
        from app.db.database import async_session_factory
        from app.services.database_session_manager import DatabaseSessionManager
        from app.models.chat import ChatSession, ChatMessage
        from sqlalchemy import select, func
        
        mgr = DatabaseSessionManager()
        
        async with async_session_factory() as db:
            # 检查会话是否存在
            result = await db.execute(
                select(ChatSession).where(ChatSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            if not session:
                return
            
            # 检查摘要冻结标志
            meta = session.metadata_ or {}
            if meta.get("summary_frozen"):
                return
            
            # 获取消息总数
            count_result = await db.execute(
                select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)
            )
            msg_count = count_result.scalar() or 0
            
            if msg_count < threshold:
                return
            
            # 获取已有摘要
            existing_summary = await mgr.get_summary(db, session_id)
            existing_text = existing_summary.summary_text if existing_summary else ""
            last_summarized_id = existing_summary.last_message_id if existing_summary else 0
            
            # 检查是否有足够的新消息
            new_msg_count = msg_count - last_summarized_id
            if new_msg_count < min_interval:
                return
            
            # 加载需要被压缩的消息
            keep_recent = 20  # 保留最近 20 条不压缩
            from sqlalchemy import and_
            
            compress_result = await db.execute(
                select(ChatMessage)
                .where(
                    and_(
                        ChatMessage.session_id == session_id,
                        ChatMessage.id > last_summarized_id,
                    )
                )
                .order_by(ChatMessage.id.asc())
            )
            compress_messages = list(compress_result.scalars().all())
            
            # 保留最近的消息不压缩
            if len(compress_messages) <= keep_recent:
                return
            compress_messages = compress_messages[:-keep_recent]
            
            # 格式化消息
            new_msgs = [
                {"role": m.role, "content": m.content}
                for m in compress_messages
            ]
            
            # 生成增量摘要
            await generate_incremental_summary(
                chat_model=chat_model,
                session_id=session_id,
                existing_summary=existing_text,
                new_messages=new_msgs,
                last_msg_id=compress_messages[-1].id,
            )
            
            logger.info(
                f"里程碑摘要更新完成: session={session_id[:12]}, "
                f"压缩消息数={len(compress_messages)}, "
                f"截止消息ID={compress_messages[-1].id}"
            )
    
    except Exception as e:
        logger.warning(f"摘要检查/生成失败（不影响主流程）: {e}")
