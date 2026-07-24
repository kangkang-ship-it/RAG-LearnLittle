"""
间隔重复回顾服务

基于艾宾浩斯遗忘曲线算法实现间隔重复回顾：
- 回顾间隔：1 / 2 / 4 / 7 / 15 / 30 天
- 今日待回顾查询
- 标记回顾完成（更新下次回顾时间）
- 生成回顾问题（LLM）
"""

from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger_handler import logger
from app.models.review import ReviewRecord
from app.models.note import Note

# 艾宾浩斯遗忘曲线间隔（天）
EBBINGHAUS_INTERVALS = [1, 2, 4, 7, 15, 30]


class ReviewService:
    """
    间隔重复回顾服务
    
    实现艾宾浩斯遗忘曲线的间隔重复算法。
    每次回顾后根据当前间隔索引递增到下一个间隔。
    """
    
    async def get_today_reviews(
        self, db: AsyncSession, user_id: str
    ) -> List[dict]:
        """
        获取今日待回顾的笔记
        
        查询 next_review_at <= 当前时间 的回顾记录，
        关联查询笔记内容，返回完整信息。
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            
        Returns:
            待回顾笔记列表（包含笔记内容和回顾信息）
        """
        now = datetime.utcnow()
        
        result = await db.execute(
            select(ReviewRecord, Note)
            .join(Note, ReviewRecord.note_id == Note.id)
            .where(
                and_(
                    ReviewRecord.user_id == user_id,
                    ReviewRecord.next_review_at <= now,
                    Note.deleted_at.is_(None),
                )
            )
            .order_by(ReviewRecord.next_review_at.asc())
        )
        
        reviews = result.all()
        
        return [
            {
                "review_id": review.id,
                "note_id": review.note_id,
                "note_title": note.title,
                "note_content": note.content,
                "review_count": review.review_count,
                "interval_days": review.interval_days,
                "next_review_at": review.next_review_at.isoformat(),
            }
            for review, note in reviews
        ]
    
    async def mark_reviewed(
        self, db: AsyncSession, review_id: int, user_id: str, quality: int = 3
    ) -> ReviewRecord:
        """
        标记回顾完成，更新下次回顾时间
        
        根据艾宾浩斯曲线递增间隔：
        - 当前间隔索引 + 1 → 新的间隔天数
        - 如果已到最大间隔，保持最后一个间隔
        
        Args:
            db: 数据库会话
            review_id: 回顾记录 ID
            user_id: 用户 ID
            quality: 回顾质量评分（0-5，预留 SM-2 算法）
            
        Returns:
            更新后的回顾记录
        """
        # 查询回顾记录
        result = await db.execute(
            select(ReviewRecord).where(
                and_(ReviewRecord.id == review_id, ReviewRecord.user_id == user_id)
            )
        )
        review = result.scalar_one_or_none()
        
        if not review:
            from app.core.failed_response import BusinessError, ErrorCode
            raise BusinessError(code=ErrorCode.NOTE_NOT_FOUND, message="回顾记录不存在", http_status=404)
        
        # 更新回顾信息
        review.review_count += 1
        review.quality = quality
        review.reviewed_at = datetime.utcnow()
        
        # 计算下次回顾时间（艾宾浩斯间隔递增）
        current_index = EBBINGHAUS_INTERVALS.index(review.interval_days) if review.interval_days in EBBINGHAUS_INTERVALS else -1
        next_index = min(current_index + 1, len(EBBINGHAUS_INTERVALS) - 1)
        review.interval_days = EBBINGHAUS_INTERVALS[next_index]
        
        review.next_review_at = datetime.utcnow() + timedelta(days=review.interval_days)
        
        await db.flush()
        
        logger.info(
            f"回顾完成: review_id={review_id}, "
            f"interval={review.interval_days}天, "
            f"next_review={review.next_review_at}"
        )
        
        return review
    
    async def get_review_stats(self, db: AsyncSession, user_id: str) -> dict:
        """
        获取用户的回顾统计信息
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            
        Returns:
            统计信息字典（今日待回顾数、总回顾次数、今日已完成、连续天数）
        """
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 今日待回顾数
        pending_result = await db.execute(
            select(func.count()).select_from(ReviewRecord).where(
                and_(
                    ReviewRecord.user_id == user_id,
                    ReviewRecord.next_review_at <= now,
                )
            )
        )
        pending_count = pending_result.scalar()
        
        # 总回顾次数
        total_result = await db.execute(
            select(func.sum(ReviewRecord.review_count)).where(
                ReviewRecord.user_id == user_id
            )
        )
        total_reviews = total_result.scalar() or 0
        
        # 今日已完成数（reviewed_at 在今天之后的记录数）
        completed_result = await db.execute(
            select(func.count()).select_from(ReviewRecord).where(
                and_(
                    ReviewRecord.user_id == user_id,
                    ReviewRecord.reviewed_at >= today_start,
                )
            )
        )
        completed_today = completed_result.scalar() or 0
        
        # 连续天数：从今天往前数，每天有 reviewed_at 记录则累加
        streak_days = 0
        check_date = today_start
        while True:
            day_end = check_date + timedelta(days=1)
            streak_result = await db.execute(
                select(func.count()).select_from(ReviewRecord).where(
                    and_(
                        ReviewRecord.user_id == user_id,
                        ReviewRecord.reviewed_at >= check_date,
                        ReviewRecord.reviewed_at < day_end,
                    )
                )
            )
            if (streak_result.scalar() or 0) > 0:
                streak_days += 1
                check_date -= timedelta(days=1)
            else:
                break
        
        return {
            "pending_today": pending_count,
            "total_reviews": total_reviews,
            "completed_today": completed_today,
            "streak_days": streak_days,
        }
