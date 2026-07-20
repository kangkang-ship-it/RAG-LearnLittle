"""
笔记模板业务逻辑服务

提供笔记模板的 CRUD 和排序功能。
"""

from typing import List, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger_handler import logger
from app.core.failed_response import BusinessError, ErrorCode
from app.models.note_template import NoteTemplate
from app.schemas.template import NoteTemplateCreate, NoteTemplateUpdate


class NoteTemplateService:
    """
    笔记模板服务
    
    管理用户自定义笔记模板的增删改查和排序。
    """
    
    async def create_template(
        self, db: AsyncSession, user_id: str, data: NoteTemplateCreate
    ) -> NoteTemplate:
        """
        创建笔记模板
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            data: 模板创建数据
            
        Returns:
            创建的模板对象
        """
        template = NoteTemplate(
            user_id=user_id,
            name=data.name,
            content_structure=data.content_structure,
            category=data.category,
            sort_order=data.sort_order,
        )
        db.add(template)
        await db.flush()
        
        logger.info(f"模板创建: template_id={template.id}, name={template.name}")
        return template
    
    async def list_templates(
        self, db: AsyncSession, user_id: str
    ) -> List[NoteTemplate]:
        """
        获取用户的模板列表（按 sort_order 排序）
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            
        Returns:
            模板列表
        """
        result = await db.execute(
            select(NoteTemplate)
            .where(NoteTemplate.user_id == user_id)
            .order_by(NoteTemplate.sort_order.asc(), NoteTemplate.created_at.desc())
        )
        return list(result.scalars().all())
    
    async def get_template(
        self, db: AsyncSession, template_id: int, user_id: str
    ) -> NoteTemplate:
        """
        获取单个模板
        
        Args:
            db: 数据库会话
            template_id: 模板 ID
            user_id: 用户 ID
            
        Returns:
            模板对象
        """
        result = await db.execute(
            select(NoteTemplate).where(
                and_(NoteTemplate.id == template_id, NoteTemplate.user_id == user_id)
            )
        )
        template = result.scalar_one_or_none()
        
        if not template:
            raise BusinessError(code=404, message="模板不存在", http_status=404)
        
        return template
    
    async def update_template(
        self, db: AsyncSession, template_id: int, user_id: str, data: NoteTemplateUpdate
    ) -> NoteTemplate:
        """
        更新模板
        
        Args:
            db: 数据库会话
            template_id: 模板 ID
            user_id: 用户 ID
            data: 更新数据
            
        Returns:
            更新后的模板对象
        """
        template = await self.get_template(db, template_id, user_id)
        
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(template, field, value)
        
        await db.flush()
        logger.info(f"模板更新: template_id={template_id}")
        return template
    
    async def delete_template(
        self, db: AsyncSession, template_id: int, user_id: str
    ) -> None:
        """
        删除模板
        
        Args:
            db: 数据库会话
            template_id: 模板 ID
            user_id: 用户 ID
        """
        template = await self.get_template(db, template_id, user_id)
        await db.delete(template)
        await db.flush()
        
        logger.info(f"模板删除: template_id={template_id}")

