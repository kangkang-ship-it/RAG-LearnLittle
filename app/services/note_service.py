"""
笔记核心业务服务

实现笔记的完整生命周期管理：
- CRUD 操作 + ChromaDB 向量双写
- 异步自动标签生成（LLM）
- 语义搜索（ChromaDB 向量检索 → MySQL 回填）
- 关联推荐（双源检索）
- AI 内联补全 / 写作辅助
- 批量操作
- Markdown 导出
"""

import asyncio
import uuid

from typing import List, Optional, Tuple

from sqlalchemy import select, update, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger_handler import logger
from app.core.failed_response import BusinessError, ErrorCode
from app.models.note import Note
from app.models.review import ReviewRecord
from app.schemas.note import NoteCreate, NoteUpdate


# 笔记标准分类（与前端 front/src/constants/noteCategories.ts 保持一致）
STANDARD_NOTE_CATEGORIES = ("工作", "学习", "生活", "技术")
# 兜底分类：分类非空且不属于标准分类时归入"其他"
OTHER_CATEGORY = "其他"


class NoteService:
    """
    笔记服务类
    
    核心设计：
    - 向量双写：笔记创建/更新时先写 MySQL → 异步写入 ChromaDB
    - 异步自动标签：保存后立即返回，后台调用 LLM 生成标签和分类
    - 语义搜索：ChromaDB 检索 → 提取 note_id → MySQL 回填完整数据
    """
    
    def __init__(self, vector_store=None, chat_model=None):
        """
        初始化笔记服务
        
        Args:
            vector_store: 向量存储服务实例（ChromaDB）
            chat_model: LLM Chat 模型实例（用于自动标签生成）
        """
        self.vector_store = vector_store
        self.chat_model = chat_model
    
    async def create_note(
        self, db: AsyncSession, user_id: str, note_data: NoteCreate
    ) -> Note:
        """
        创建笔记
        
        流程：
        1. 写入 MySQL
        2. 异步写入 ChromaDB（向量双写）
        3. 后台异步生成标签和创建回顾记录
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            note_data: 笔记创建数据
            
        Returns:
            创建的笔记对象
        """
        note = Note(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=note_data.title,
            content=note_data.content,
            tags=note_data.tags or [],
            category=note_data.category,
            is_pinned=note_data.is_pinned,
        )
        
        db.add(note)
        await db.flush()
        
        # 刷新对象以加载数据库生成的字段（created_at, updated_at 等 server_default 值）
        await db.refresh(note)
        
        # 异步写入 ChromaDB（失败不影响主流程）
        if self.vector_store:
            asyncio.create_task(self._sync_to_vector(note))
            logger.info(f"ChromaDB 异步写入任务已创建: note_id={note.id}")
        
        # 后台异步生成标签和创建回顾记录（不传入 db，因为请求 session 会在响应返回后关闭）
        asyncio.create_task(self._auto_tag_and_review(note))
        
        logger.info(f"笔记创建成功: note_id={note.id}, user_id={user_id}")
        return note
    
    async def get_note(self, db: AsyncSession, note_id: str, user_id: str) -> Note:
        """
        获取单个笔记（带权限校验）
        
        Args:
            db: 数据库会话
            note_id: 笔记 ID
            user_id: 当前用户 ID
            
        Returns:
            笔记对象
            
        Raises:
            BusinessError: 笔记不存在或无权访问
        """
        result = await db.execute(
            select(Note).where(
                and_(Note.id == note_id, Note.user_id == user_id, Note.deleted_at.is_(None))
            )
        )
        note = result.scalar_one_or_none()
        
        if not note:
            raise BusinessError(code=ErrorCode.NOTE_NOT_FOUND, http_status=404)
        
        return note
    
    async def list_notes(
        self, db: AsyncSession, user_id: str,
        page: int = 1, page_size: int = 20,
        category: Optional[str] = None
    ) -> Tuple[List[Note], int]:
        """
        分页获取笔记列表
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            page: 页码
            page_size: 每页数量
            category: 按分类过滤（可选）
            
        Returns:
            (笔记列表, 总数)
        """
        # 构建查询
        query = select(Note).where(
            and_(Note.user_id == user_id, Note.deleted_at.is_(None))
        )
        count_query = select(func.count()).select_from(Note).where(
            and_(Note.user_id == user_id, Note.deleted_at.is_(None))
        )
        
        if category:
            if category == OTHER_CATEGORY:
                # "其他"兜底分类：分类非空且不属于标准分类（含历史任意分类值）。
                # not_in 对 NULL 不匹配 → 排除"未分类"；列表中加入空串 → 排除空分类旧数据
                excluded = STANDARD_NOTE_CATEGORIES + ("",)
                query = query.where(Note.category.not_in(excluded))
                count_query = count_query.where(Note.category.not_in(excluded))
            else:
                query = query.where(Note.category == category)
                count_query = count_query.where(Note.category == category)
        
        # 排序：置顶优先，然后按更新时间倒序
        query = query.order_by(Note.is_pinned.desc(), Note.updated_at.desc())
        
        # 分页
        query = query.offset((page - 1) * page_size).limit(page_size)
        
        result = await db.execute(query)
        total_result = await db.execute(count_query)
        
        notes = list(result.scalars().all())
        total = total_result.scalar()
        
        return notes, total
    
    async def update_note(
        self, db: AsyncSession, note_id: str, user_id: str, note_data: NoteUpdate
    ) -> Note:
        """
        更新笔记
        
        更新后同步更新 ChromaDB 向量。
        
        Args:
            db: 数据库会话
            note_id: 笔记 ID
            user_id: 用户 ID
            note_data: 更新数据
            
        Returns:
            更新后的笔记对象
        """
        note = await self.get_note(db, note_id, user_id)
        
        # 更新字段
        update_data = note_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(note, field, value)
        
        note.updated_at = func.now()
        await db.flush()
        # 回读数据库生成的 updated_at（func.now() 是 SQL 表达式，flush 后属性待回读；
        # 不 refresh 的话，后续响应序列化时在 greenlet 外触发 SELECT → MissingGreenlet）
        await db.refresh(note)

        # 同步更新 ChromaDB 向量
        if self.vector_store:
            logger.info(f"创建异步写入任务: note_id={note.id}")
            asyncio.create_task(self._sync_to_vector(note))
        
        logger.info(f"笔记更新: note_id={note_id}")
        return note
    
    async def delete_note(self, db: AsyncSession, note_id: str, user_id: str) -> None:
        """
        软删除笔记（设置 deleted_at）

        使用直接 SQL UPDATE 而非 ORM 对象修改，确保变更可靠持久化。
        同时从 ChromaDB 中删除对应向量。

        Args:
            db: 数据库会话
            note_id: 笔记 ID
            user_id: 用户 ID
        """
        # 先验证笔记存在（权限校验 + 确保未删除）
        note = await self.get_note(db, note_id, user_id)

        # 直接 SQL UPDATE —— 绕过 ORM flush 的对象状态跟踪，
        # 确保 UPDATE 语句一定被发送到数据库连接
        result = await db.execute(
            update(Note)
            .where(and_(Note.id == note_id, Note.user_id == user_id))
            .values(deleted_at=func.now())   # 设置 deleted_at 为当前时间戳 使用数据库服务时间与其他事件字段保持一致
        )

        if result.rowcount == 0:
            raise BusinessError(code=ErrorCode.NOTE_NOT_FOUND, http_status=404)

        # 从 ChromaDB 删除向量
        if self.vector_store:
            try:
                await self.vector_store.delete_note_vectors(note_id)
                logger.info(f"ChromaDB 向量删除成功: note_id={note_id}")
            except Exception as e:
                logger.error(f"ChromaDB 向量删除失败: note_id={note_id}, error={e}")

        logger.info(f"笔记软删除: note_id={note_id}")

    # ========== 回收站 ==========

    async def list_deleted_notes(
        self, db: AsyncSession, user_id: str, page: int = 1, page_size: int = 20
    ) -> Tuple[List[Note], int]:
        """
        分页获取回收站笔记列表（deleted_at IS NOT NULL，按删除时间倒序）

        Args:
            db: 数据库会话
            user_id: 用户 ID
            page: 页码
            page_size: 每页数量

        Returns:
            (回收站笔记列表, 总数)
        """
        query = select(Note).where(
            and_(Note.user_id == user_id, Note.deleted_at.isnot(None))
        ).order_by(Note.deleted_at.desc())
        count_query = select(func.count()).select_from(Note).where(
            and_(Note.user_id == user_id, Note.deleted_at.isnot(None))
        )

        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await db.execute(query)
        total_result = await db.execute(count_query)

        notes = list(result.scalars().all())
        total = total_result.scalar()

        return notes, total

    async def restore_note(self, db: AsyncSession, note_id: str, user_id: str) -> Note:
        """
        从回收站恢复笔记（清除 deleted_at + 重建 ChromaDB 向量）

        流程：
        1. 查询笔记（验证 user_id 归属 + deleted_at IS NOT NULL）
        2. UPDATE deleted_at = NULL
        3. 重建 ChromaDB 向量 —— 写入格式必须与 _sync_to_vector 完全一致
           （ids=f"note_{note.id}"、metadata 含 user_id/note_id/title/category），
           否则 delete_note_vectors / search_notes 无法正确定位
        4. 若向量重建失败：记录 error 日志，不阻塞恢复（向量可由后续任务补建）

        Args:
            db: 数据库会话
            note_id: 笔记 ID
            user_id: 用户 ID

        Returns:
            恢复后的笔记对象

        Raises:
            BusinessError: 笔记不存在、无权访问或不在回收站中
        """
        # 1. 查询笔记（验证归属 + 确保在回收站中）
        result = await db.execute(
            select(Note).where(
                and_(Note.id == note_id, Note.user_id == user_id, Note.deleted_at.isnot(None))
            )
        )
        note = result.scalar_one_or_none()
        if not note:
            raise BusinessError(code=ErrorCode.NOTE_NOT_FOUND, http_status=404)

        # 2. 清除 deleted_at
        note.deleted_at = None
        note.updated_at = func.now()
        await db.flush()
        # 回读数据库生成的 updated_at（func.now() 为 SQL 表达式，见 update_note 注释）
        await db.refresh(note)

        # 3. 重建 ChromaDB 向量（与 _sync_to_vector 完全一致）
        if self.vector_store:
            try:
                await self.vector_store.upsert_document(
                    documents=[note.content or note.title],
                    metadatas=[{
                        "user_id": note.user_id,
                        "note_id": note.id,
                        "title": note.title,
                        "category": note.category or "",
                    }],
                    ids=[f"note_{note.id}"],
                    collection="notes",
                )
                logger.info(f"回收站笔记恢复，向量重建完成: note_id={note.id}")
            except Exception as e:
                # 向量重建失败不阻塞恢复（笔记已恢复，向量可由定时修复任务补建）
                logger.error(f"恢复笔记向量重建失败: note_id={note.id}, error={e}")

        logger.info(f"笔记恢复: note_id={note_id}")
        return note

    async def permanent_delete(self, db: AsyncSession, note_id: str, user_id: str) -> None:
        """
        彻底删除笔记（物理删除 MySQL 记录 + 删除 ChromaDB 向量）

        ⚠️ 级联影响：Note.review_records 关系定义了 cascade="all, delete-orphan"
        （app/models/note.py），物理删除 Note 时 SQLAlchemy 会级联删除该笔记的
        所有 ReviewRecord（回顾记录），且不可恢复。前端确认弹窗需明确提示。

        Args:
            db: 数据库会话
            note_id: 笔记 ID
            user_id: 用户 ID

        Raises:
            BusinessError: 笔记不存在、无权访问或不在回收站中
        """
        # 1. 验证笔记属于当前用户 且已删除（回收站内）
        result = await db.execute(
            select(Note).where(
                and_(Note.id == note_id, Note.user_id == user_id, Note.deleted_at.isnot(None))
            )
        )
        note = result.scalar_one_or_none()
        if not note:
            raise BusinessError(code=ErrorCode.NOTE_NOT_FOUND, http_status=404)

        # 2. 删除 ChromaDB 向量（若存在）
        if self.vector_store:
            try:
                await self.vector_store.delete_note_vectors(note_id)
            except Exception as e:
                logger.error(f"彻底删除时向量删除失败: note_id={note_id}, error={e}")

        # 3. 物理删除（ORM 级联删除 review_records）
        await db.delete(note)
        await db.flush()

        logger.info(f"笔记彻底删除: note_id={note_id}")

    async def cleanup_expired_notes(self, db: AsyncSession, days: int = 14) -> int:
        """
        清理过期笔记（deleted_at 超过 days 天）→ 返回删除数量

        定时任务调用；同时清理 ChromaDB 向量，并级联删除 review_records。

        Args:
            db: 数据库会话
            days: 过期阈值天数（默认 14 天）

        Returns:
            本次物理删除的笔记数量
        """
        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(days=days)

        result = await db.execute(
            select(Note).where(
                and_(Note.deleted_at.isnot(None), Note.deleted_at < cutoff)
            )
        )
        expired = list(result.scalars().all())
        if not expired:
            return 0

        # 删除 ChromaDB 向量
        if self.vector_store:
            for note in expired:
                try:
                    await self.vector_store.delete_note_vectors(note.id)
                except Exception as e:
                    logger.warning(f"清理过期向量失败: note_id={note.id}, error={e}")

        # 物理删除（ORM 级联删除 review_records）
        for note in expired:
            await db.delete(note)
        await db.flush()

        logger.info(f"清理过期笔记完成: 删除 {len(expired)} 条（超过 {days} 天）")
        return len(expired)

    async def pin_note(self, db: AsyncSession, note_id: str, user_id: str) -> Note:
        """
        置顶笔记

        Args:
            db: 数据库会话
            note_id: 笔记 ID
            user_id: 用户 ID

        Returns:
            更新后的笔记对象
        """
        note = await self.get_note(db, note_id, user_id)
        note.is_pinned = True
        note.updated_at = func.now()
        await db.flush()
        await db.refresh(note)  # 回读 updated_at（func.now() 为 SQL 表达式，见 update_note 注释）
        logger.info(f"笔记置顶: note_id={note_id}")
        return note

    async def unpin_note(self, db: AsyncSession, note_id: str, user_id: str) -> Note:
        """
        取消置顶笔记

        Args:
            db: 数据库会话
            note_id: 笔记 ID
            user_id: 用户 ID

        Returns:
            更新后的笔记对象
        """
        note = await self.get_note(db, note_id, user_id)
        note.is_pinned = False
        note.updated_at = func.now()
        await db.flush()
        await db.refresh(note)  # 回读 updated_at（func.now() 为 SQL 表达式，见 update_note 注释）
        logger.info(f"笔记取消置顶: note_id={note_id}")
        return note

    async def move_note(
        self, db: AsyncSession, note_id: str, user_id: str, category: str
    ) -> Note:
        """
        移动笔记到目标分类

        Args:
            db: 数据库会话
            note_id: 笔记 ID
            user_id: 用户 ID
            category: 目标分类（必填，已在 schema 层校验）

        Returns:
            更新后的笔记对象
        """
        note = await self.get_note(db, note_id, user_id)
        note.category = category
        note.updated_at = func.now()
        await db.flush()
        await db.refresh(note)  # 回读 updated_at（func.now() 为 SQL 表达式，见 update_note 注释）
        logger.info(f"笔记移动分类: note_id={note_id}, category={category}")
        return note

    async def semantic_search(
        self, db: AsyncSession, user_id: str, query: str, top_k: int = 5
    ) -> List[Tuple[Note, float]]:
        """
        语义搜索笔记
        
        流程：
        1. ChromaDB 向量检索（按 user_id 过滤）
        2. 提取 note_id 列表
        3. MySQL 批量查询完整笔记数据
        4. 按相似度分数排序返回
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            query: 搜索关键词
            top_k: 返回结果数量
            
        Returns:
            [(Note, score), ...] 按相似度降序排列
        """
        if not self.vector_store:
            return []
        
        # ChromaDB 检索
        results = await self.vector_store.search_notes(
            query=query, user_id=user_id, top_k=top_k
        )
        
        if not results:
            return []
        
        # 提取 note_id 和分数
        note_ids = [r["note_id"] for r in results]
        score_map = {r["note_id"]: r["score"] for r in results}
        
        # MySQL 批量查询
        result = await db.execute(
            select(Note).where(
                and_(
                    Note.id.in_(note_ids),
                    Note.user_id == user_id,
                    Note.deleted_at.is_(None)
                )
            )
        )
        
        notes = result.scalars().all()
        
        # 按相似度排序
        sorted_results = [
            (note, score_map.get(note.id, 0.0))
            for note in notes
        ]
        sorted_results.sort(key=lambda x: x[1], reverse=True)
        
        return sorted_results
    
    async def _sync_to_vector(self, note: Note) -> None:
        """
        异步同步笔记到 ChromaDB 向量库（notes_collection）

        失败时记录日志，不影响主流程。
        注意：ChromaDB 元数据仅支持标量值，tags 列表不入元数据；
        检索端 search_notes 依赖 metadata 中的 user_id（隔离）和 note_id（关联）。

        Args:
            note: 笔记对象
        """
        try:
            await self.vector_store.upsert_document(
                documents=[note.content or note.title],
                metadatas=[{
                    "user_id": note.user_id,
                    "note_id": note.id,
                    "title": note.title,
                    "category": note.category or "",
                }],
                ids=[f"note_{note.id}"],
                collection="notes",
            )
            logger.debug(f"笔记向量同步完成: note_id={note.id}")
        except Exception as e:
            logger.error(f"向量同步失败: note_id={note.id}, error={e}")
    
    async def _auto_tag_and_review(self, note: Note) -> None:
        """
        后台异步任务：自动标签生成 + 创建回顾记录
        
        使用独立的数据库会话，避免依赖已关闭的请求 session。
        
        Args:
            note: 笔记对象
        """
        try:
            # TODO: 调用 LLM 生成标签和分类
            # 创建回顾记录（艾宾浩斯遗忘曲线）
            from app.db.database import async_session_factory
            
            async with async_session_factory() as new_session:
                review = ReviewRecord(
                    note_id=note.id,
                    user_id=note.user_id,
                    review_count=0,
                    interval_days=1,
                    next_review_at=func.now(),  # 立即可回顾
                )
                new_session.add(review)
                await new_session.commit()
                
            logger.info(f"自动标签和回顾记录创建完成: note_id={note.id}")
            
        except Exception as e:
            logger.error(f"自动标签任务失败: note_id={note.id}, error={e}")

