"""
聊天业务代理服务层

封装 RAG 查询和会话管理的业务逻辑，
作为 Router 层和底层 Service/RAG 之间的桥梁。
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger_handler import logger
from app.db.database import async_session_factory
from app.models.chat import ChatSession, ChatMessage
from app.services.database_session_manager import DatabaseSessionManager


class ChatService:
    """
    聊天业务代理层
    
    职责：
    - 协调会话管理和消息持久化
    - 集成 RAG 查询结果
    - 处理会话标题自动生成逻辑
    """
    
    def __init__(self, session_manager: Optional[DatabaseSessionManager] = None):
        """
        初始化聊天服务
        
        Args:
            session_manager: 会话管理器实例
        """
        self.session_manager = session_manager or DatabaseSessionManager()
    
    async def get_or_create_session(
        self, db: AsyncSession, user_id: str, session_id: Optional[str] = None
    ) -> str:
        """
        获取或创建聊天会话
        
        如果 session_id 为空，自动创建新会话。
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            session_id: 现有会话 ID（可选）
            
        Returns:
            会话 ID
        """
        if session_id:
            # 验证现有会话
            session = await self.session_manager.get_session(db, session_id, user_id)
            return session.id
        else:
            # 创建新会话
            session = await self.session_manager.create_session(db, user_id)
            return session.id

    async def save_message_with_commit(
        self, session_id: str, user_id: str, role: str, content: str,
        idempotency_key: Optional[str] = None
    ) -> None:
        """
        使用独立 session 保存消息并 commit（用于异步后台任务）
        
        不依赖请求级 db session，使用 async_session_factory() 创建独立会话，
        确保消息持久化到 MySQL + Redis 缓存。
        
        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            role: 消息角色
            content: 消息内容
            idempotency_key: 幂等键
        """
        try:
            async with async_session_factory() as db:
                await self.session_manager.add_message(
                    db, session_id, user_id, role, content, idempotency_key
                )
                await db.commit()
                logger.info(f"消息保存成功: session={session_id[:12]}, role={role}, len={len(content)}")
        except Exception as e:
            logger.error(f"保存消息失败: session_id={session_id}, role={role}, error={type(e).__name__}: {e}", exc_info=True)

    async def generate_and_update_title(
        self, session_id: str, user_message: str, chat_model=None
    ) -> None:
        """
        根据用户消息自动生成/更新会话标题
        
        策略：
        - 新会话（默认标题"新对话"）：直接用 LLM 生成标题
        - 已有标题的会话：检查消息数，前 3 轮内允许更新
        
        Args:
            session_id: 会话 ID
            user_message: 用户最新消息内容
            chat_model: LLM 模型实例
        """
        try:
            async with async_session_factory() as db:
                # 获取会话
                result = await db.execute(
                    select(ChatSession).where(ChatSession.id == session_id)
                )
                session = result.scalar_one_or_none()
                if not session:
                    return
                
                # 统计当前会话消息数
                msg_count_result = await db.execute(
                    select(ChatMessage).where(ChatMessage.session_id == session_id)
                )
                msg_count = len(msg_count_result.scalars().all())
                
                # 标题已是自定义的（非默认），不再自动更新
                if session.title != "新对话" and msg_count > 4:
                    return
                
                # 使用 LLM 生成标题
                if chat_model:
                    title = await self._generate_title_with_llm(user_message, chat_model)
                else:
                    # 降级：取用户消息前 20 字符作为标题
                    title = user_message[:20].strip()
                
                if title:
                    session.title = title
                    await db.commit()
                    logger.info(f"会话标题已更新: session_id={session_id}, title={title}")
        
        except Exception as e:
            logger.warning(f"更新会话标题失败: session_id={session_id}, error={e}")

    async def _generate_title_with_llm(self, user_message: str, chat_model) -> str:
        """
        使用 LLM 根据对话内容生成会话标题
        
        使用 astream 收集结果（ChatOllama 无 ainvoke 方法）。
        
        Args:
            user_message: 用户消息
            chat_model: LLM 模型实例
            
        Returns:
            生成的标题文本
        """
        try:
            from app.utils.prompt_loader import format_prompt
            from langchain_core.messages import HumanMessage
            prompt = format_prompt("session_title", conversation=user_message)
            
            # 使用 astream 收集完整响应（兼容 ChatOllama）
            title = ""
            async for chunk in chat_model.astream([HumanMessage(content=prompt)]):
                if hasattr(chunk, 'content') and chunk.content:
                    title += chunk.content
            
            title = title.strip().strip('"').strip("'")[:20]
            return title if title else user_message[:20]
        except Exception as e:
            logger.warning(f"LLM 生成标题失败: {e}")
            return user_message[:20].strip()
