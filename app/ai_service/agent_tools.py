"""
Agent 工具集

定义 Agent 可使用的 9 个异步工具：
1. what_time_is_now - 获取当前时间
2. get_user_info_tools - 从 JWT 解析用户信息
3. search_notes_tool - 语义搜索笔记
4. get_note_stats_tool - 笔记分类统计
5. get_today_reviews_tool - 获取今日待回顾笔记
6. mark_reviewed_tool - 标记回顾完成
7. create_note_tool - 创建新笔记
8. update_note_tool - 更新已有笔记
9. get_related_notes_tool - 获取关联推荐
"""

from datetime import datetime
from typing import Optional, List

from langchain_core.tools import tool

from app.core.logger_handler import logger


def create_agent_tools(
    user_id: str,
    note_service=None,
    review_service=None,
    db_session_factory=None,
    groups: Optional[List[str]] = None,
):
    """
    创建 Agent 工具集工厂函数

    每次调用创建新的工具实例，绑定当前用户上下文。
    支持按需加载：通过 groups 参数指定要加载的工具组，
    未指定时返回全部工具（向后兼容）。

    Args:
        user_id: 当前用户 ID
        note_service: 笔记服务实例
        review_service: 回顾服务实例
        db_session_factory: 数据库会话工厂
        groups: 要加载的工具组名称列表（如 ["base", "note_read"]）。
                None 表示加载全部工具。

    Returns:
        工具列表
    """

    @tool
    async def what_time_is_now() -> str:
        """获取当前日期和时间，返回格式为 YYYY-MM-DD HH:MM:SS"""
        now = datetime.now()
        return now.strftime("%Y-%m-%d %H:%M:%S")

    @tool
    async def get_user_info_tools() -> str:
        """获取当前登录用户的基本信息"""
        return f"当前用户 ID: {user_id}"

    @tool
    async def search_notes_tool(query: str, top_k: int = 5) -> str:
        """
        语义搜索用户的笔记

        Args:
            query: 搜索关键词
            top_k: 返回结果数量，默认 5
        """
        if not db_session_factory or not note_service:
            return "笔记服务未初始化"

        async with db_session_factory() as db:
            results = await note_service.semantic_search(db, user_id, query, top_k)

            if not results:
                return "未找到相关笔记"

            output = []
            for note, score in results:
                output.append(f"[{score:.2f}] ID:{note.id} | {note.title}\n{note.content[:200]}...")

            return "\n\n---\n\n".join(output)

    @tool
    async def get_note_stats_tool() -> str:
        """获取笔记分类统计信息（各分类的笔记数量）"""
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

    @tool
    async def get_today_reviews_tool() -> str:
        """获取今日待回顾的笔记列表"""
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

    @tool
    async def mark_reviewed_tool(review_id: int) -> str:
        """
        标记一条回顾记录为已完成

        Args:
            review_id: 回顾记录 ID
        """
        if not db_session_factory or not review_service:
            return "服务未初始化"

        async with db_session_factory() as db:
            review = await review_service.mark_reviewed(db, review_id, user_id)
            await db.commit()
            return f"回顾完成！下次回顾时间: {review.next_review_at.strftime('%Y-%m-%d')}"

    @tool
    async def create_note_tool(title: str, content: str, tags: str = "", category: str = "") -> str:
        """
        创建一条新笔记

        Args:
            title: 笔记标题
            content: 笔记内容（支持 Markdown）
            tags: 标签，逗号分隔（如 "Python,FastAPI"）
            category: 分类名称
        """
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

    @tool
    async def update_note_tool(note_id: str, title: str = None, content: str = None, tags: str = None, category: str = None) -> str:
        """
        更新一条已有笔记的内容、标题、标签或分类。
        只需传入要修改的字段，未传入的字段保持不变。
        使用前请先通过 search_notes_tool 搜索目标笔记获取其 ID。

        Args:
            note_id: 笔记 ID（必填，可通过 search_notes_tool 搜索获取）
            title: 新标题（可选，不传则保持原标题不变）
            content: 新内容（可选，支持 Markdown，不传则保持原内容不变。注意：这是完整替换，如需追加内容请先读取原内容再拼接）
            tags: 新标签（可选，逗号分隔如 "Python,FastAPI"，不传则保持原标签不变）
            category: 新分类名称（可选，不传则保持原分类不变）
        """
        if not db_session_factory or not note_service:
            return "服务未初始化"

        from app.schemas.note import NoteUpdate

        update_data = {}
        if title is not None:
            update_data["title"] = title
        if content is not None:
            update_data["content"] = content
        if tags is not None:
            update_data["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        if category is not None:
            update_data["category"] = category

        if not update_data:
            return "未提供任何要更新的字段"

        async with db_session_factory() as db:
            try:
                note = await note_service.update_note(
                    db, note_id, user_id, NoteUpdate(**update_data)
                )
                await db.commit()
                return f"笔记更新成功！ID: {note.id}, 标题: {note.title}"
            except Exception as e:
                return f"笔记更新失败: {str(e)}"

    @tool
    async def get_related_notes_tool(note_title: str, top_k: int = 3) -> str:
        """
        获取与指定标题相关的笔记推荐

        Args:
            note_title: 参考笔记标题
            top_k: 返回数量，默认 3
        """
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

     # TODO: 未来可以增加一个 send_email 工具，允许 LLM 直接发送邮件通知用户
    async def send_email(to: str, subject: str, body: str) -> str:
        """
        发送邮件
        当用户明确需要发送邮件功能时LLM可以调用这个工具来发送邮件

        Args:
            to: 收件人邮箱
            subject: 邮件主题
            body: 邮件正文
        """
        # 这里可以集成实际的邮件发送服务，如 SMTP、SendGrid 等
        # 目前仅返回模拟结果
        return f"邮件已发送至 {to}，主题: {subject}"

    # 全部工具注册表（名称 → 工具对象）
    all_tools = {
        "what_time_is_now": what_time_is_now,
        "get_user_info_tools": get_user_info_tools,
        "search_notes_tool": search_notes_tool,
        "get_note_stats_tool": get_note_stats_tool,
        "get_today_reviews_tool": get_today_reviews_tool,
        "mark_reviewed_tool": mark_reviewed_tool,
        "create_note_tool": create_note_tool,
        "update_note_tool": update_note_tool,
        "get_related_notes_tool": get_related_notes_tool,
    }

    # 按需加载：根据 groups 过滤工具
    if groups is None:
        # 未指定 groups → 返回全部（向后兼容）
        return list(all_tools.values())

    # 从配置加载工具组定义
    from app.utils.config import get_tool_groups_config
    tool_groups = get_tool_groups_config()

    selected_names = set()
    for group_name in groups:
        group_tools = tool_groups.get(group_name, [])
        if not group_tools:
            logger.warning(f"工具组 '{group_name}' 未在 agent.yaml 中定义，跳过")
            continue
        selected_names.update(group_tools)

    # 保持注册顺序返回
    result = [all_tools[name] for name in all_tools if name in selected_names]

    # 安全保底：至少包含 base 组工具
    if not result:
        logger.warning("按需加载结果为空，回退到全量工具")
        return list(all_tools.values())

    logger.debug(f"工具按需加载: groups={groups}, 选中 {len(result)}/{len(all_tools)} 个工具")
    return result
