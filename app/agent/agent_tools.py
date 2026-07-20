"""
Agent 工具集

定义 Agent 可使用的 8 个自定义工具：
1. what_time_is_now - 获取当前时间
2. get_user_info_tools - 从 JWT 解析用户信息
3. search_notes_tool - 语义搜索笔记
4. get_note_stats_tool - 笔记分类统计
5. get_today_reviews_tool - 获取今日待回顾笔记
6. mark_reviewed_tool - 标记回顾完成
7. create_note_tool - 创建新笔记
8. get_related_notes_tool - 获取关联推荐
"""

from datetime import datetime
from typing import Optional

from langchain_core.tools import tool


def create_agent_tools(user_id: str, note_service=None, review_service=None, db_session_factory=None):
    """
    创建 Agent 工具集工厂函数
    
    每次调用创建新的工具实例，绑定当前用户上下文。
    使用 ContextVar 传递 user_id 确保异步安全。
    
    Args:
        user_id: 当前用户 ID
        note_service: 笔记服务实例
        review_service: 回顾服务实例
        db_session_factory: 数据库会话工厂
        
    Returns:
        工具列表
    """
    
    @tool
    def what_time_is_now() -> str:
        """获取当前日期和时间，返回格式为 YYYY-MM-DD HH:MM:SS"""
        now = datetime.now()
        return now.strftime("%Y-%m-%d %H:%M:%S")
    
    @tool
    def get_user_info_tools() -> str:
        """获取当前登录用户的基本信息"""
        return f"当前用户 ID: {user_id}"
    
    @tool
    def search_notes_tool(query: str, top_k: int = 5) -> str:
        """
        语义搜索用户的笔记
        
        Args:
            query: 搜索关键词
            top_k: 返回结果数量，默认 5
        """
        import asyncio
        
        async def _search():
            if not db_session_factory or not note_service:
                return "笔记服务未初始化"
            
            async with db_session_factory() as db:
                results = await note_service.semantic_search(db, user_id, query, top_k)
                
                if not results:
                    return "未找到相关笔记"
                
                output = []
                for note, score in results:
                    output.append(f"[{score:.2f}] {note.title}\n{note.content[:200]}...")
                
                return "\n\n---\n\n".join(output)
        
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_search())
        finally:
            loop.close()
    
    @tool
    def get_note_stats_tool() -> str:
        """获取笔记分类统计信息（各分类的笔记数量）"""
        import asyncio
        
        async def _stats():
            if not db_session_factory:
                return "数据库未初始化"
            
            from sqlalchemy import select, func
            from app.models.note import Note
            
            async with db_session_factory() as db:
                result = await db.execute(
                    select(Note.category, func.count())
                    .where(Note.user_id == user_id, Note.deleted_at.is_(None))
                    .group_by(Note.category)
                )
                stats = result.all()
                
                if not stats:
                    return "暂无笔记"
                
                lines = [f"- {cat or '未分类'}: {count} 篇" for cat, count in stats]
                return "笔记分类统计:\n" + "\n".join(lines)
        
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_stats())
        finally:
            loop.close()
    
    @tool
    def get_today_reviews_tool() -> str:
        """获取今日待回顾的笔记列表"""
        import asyncio
        
        async def _reviews():
            if not db_session_factory or not review_service:
                return "服务未初始化"
            
            async with db_session_factory() as db:
                reviews = await review_service.get_today_reviews(db, user_id)
                
                if not reviews:
                    return "今日没有待回顾的笔记"
                
                lines = []
                for r in reviews:
                    lines.append(f"- [{r['note_title']}] (第{r['review_count']+1}次回顾)")
                
                return f"今日待回顾 ({len(reviews)} 篇):\n" + "\n".join(lines)
        
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_reviews())
        finally:
            loop.close()
    
    @tool
    def mark_reviewed_tool(review_id: int) -> str:
        """
        标记一条回顾记录为已完成
        
        Args:
            review_id: 回顾记录 ID
        """
        import asyncio
        
        async def _mark():
            if not db_session_factory or not review_service:
                return "服务未初始化"
            
            async with db_session_factory() as db:
                review = await review_service.mark_reviewed(db, review_id, user_id)
                await db.commit()
                return f"回顾完成！下次回顾时间: {review.next_review_at.strftime('%Y-%m-%d')}"
        
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_mark())
        finally:
            loop.close()
    
    @tool
    def create_note_tool(title: str, content: str, tags: str = "", category: str = "") -> str:
        """
        创建一条新笔记
        
        Args:
            title: 笔记标题
            content: 笔记内容（支持 Markdown）
            tags: 标签，逗号分隔（如 "Python,FastAPI"）
            category: 分类名称
        """
        import asyncio
        
        async def _create():
            if not db_session_factory or not note_service:
                return "服务未初始化"
            
            from app.schemas.note import NoteCreate
            
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
            
            async with db_session_factory() as db:
                note = await note_service.create_note(
                    db, user_id,
                    NoteCreate(title=title, content=content, tags=tag_list, category=category)
                )
                await db.commit()
                return f"笔记创建成功！ID: {note.id}, 标题: {note.title}"
        
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_create())
        finally:
            loop.close()
    
    @tool
    def get_related_notes_tool(note_title: str, top_k: int = 3) -> str:
        """
        获取与指定标题相关的笔记推荐
        
        Args:
            note_title: 参考笔记标题
            top_k: 返回数量，默认 3
        """
        import asyncio
        
        async def _related():
            if not db_session_factory or not note_service:
                return "服务未初始化"
            
            async with db_session_factory() as db:
                results = await note_service.semantic_search(db, user_id, note_title, top_k)
                
                if not results:
                    return "未找到相关笔记"
                
                output = []
                for note, score in results:
                    output.append(f"[{score:.2f}] {note.title}")
                
                return "相关笔记:\n" + "\n".join(output)
        
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_related())
        finally:
            loop.close()
    
    # 返回工具列表
    return [
        what_time_is_now,
        get_user_info_tools,
        search_notes_tool,
        get_note_stats_tool,
        get_today_reviews_tool,
        mark_reviewed_tool,
        create_note_tool,
        get_related_notes_tool,
    ]
