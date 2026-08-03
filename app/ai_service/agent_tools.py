"""
Agent 工具集

定义 Agent 可使用的 11 个异步工具：
1. what_time_is_now - 获取当前时间
2. get_user_info_tools - 获取当前用户基本信息（用户名、邮箱、ID）
3. search_notes_tool - 语义搜索笔记（返回 200 字符摘要）
4. get_note_content_tool - 获取单篇笔记完整内容（邮件发送/导出用）
5. get_note_stats_tool - 笔记分类统计
6. get_today_reviews_tool - 获取今日待回顾笔记
7. mark_reviewed_tool - 标记回顾完成
8. create_note_tool - 创建新笔记
9. update_note_tool - 更新已有笔记
10. get_related_notes_tool - 获取关联推荐
11. send_email - 发送邮件（笔记转 Markdown/PDF 附件发送到用户邮箱）
"""

import re
from datetime import datetime
from typing import Optional, List

from langchain_core.tools import tool

from app.core.logger_handler import logger


def create_agent_tools(
    user_id: str,
    note_service=None,
    review_service=None,
    db_session_factory=None,
    email_service=None,
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
        email_service: 邮件发送服务实例（send_email 工具使用）
        groups: 要加载的工具组名称列表（如 ["base", "note_read"]）。
                None 表示加载全部工具。

    Returns:
        工具列表
    """

    # 用户信息延迟缓存：首次调用 get_user_info_tools 时查询数据库，
    # 后续调用命中缓存。始终初始化，避免 db_session_factory 为 None 时 nonlocal 引用报错
    _user_cache = {"fetched": False, "user": None}

    @tool
    async def what_time_is_now() -> str:
        """获取当前日期和时间，返回格式为 YYYY-MM-DD HH:MM:SS"""
        now = datetime.now()
        return now.strftime("%Y-%m-%d %H:%M:%S")

    @tool
    async def get_user_info_tools() -> str:
        """获取当前登录用户的基本信息（用户名、邮箱、用户ID）"""
        nonlocal _user_cache
        if not _user_cache["fetched"]:
            if db_session_factory:
                from sqlalchemy import select
                from app.models.user import User

                async with db_session_factory() as db:
                    result = await db.execute(select(User).where(User.uuid == user_id))
                    _user_cache["user"] = result.scalar_one_or_none()
            _user_cache["fetched"] = True

        user = _user_cache["user"]
        if user:
            email_info = user.email if user.email else "未设置邮箱"
            return f"用户名: {user.username}\n邮箱: {email_info}\n用户ID: {user_id}"
        return f"当前用户 ID: {user_id}（用户信息获取失败）"

    @tool
    async def search_notes_tool(query: str, top_k: int = 5) -> str:
        """
        语义搜索用户的笔记

        注意：返回的笔记内容仅为摘要（前 200 字符）。若需要单篇笔记的完整内容
        （如导出、发送邮件），请先搜索获取 note_id，再调用 get_note_content_tool。

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
    async def get_note_content_tool(note_id: str) -> str:
        """
        获取单篇笔记的完整内容（Markdown，含标题、分类/标签元信息和全部正文）。

        发送邮件、导出等需要完整内容的场景，必须先用 search_notes_tool 搜索
        目标笔记获取 note_id，再调用本工具获取完整内容。
        注意：search_notes_tool 只返回 200 字符摘要，不得直接用作邮件正文。

        Args:
            note_id: 笔记 ID（可通过 search_notes_tool 搜索获取）
        """
        if not db_session_factory or not note_service:
            return "服务未初始化"

        # 完整内容上限（超出部分截断并明确提示，保护上下文窗口）
        MAX_CONTENT_CHARS = 50000

        async with db_session_factory() as db:
            try:
                note = await note_service.get_note(db, note_id, user_id)
            except Exception as e:
                return f"未找到笔记: {str(e)}"

        content = note.content or ""
        truncated = len(content) > MAX_CONTENT_CHARS
        if truncated:
            content = content[:MAX_CONTENT_CHARS]

        tags_str = ",".join(note.tags or []) or "无"
        updated_str = note.updated_at.strftime("%Y-%m-%d") if note.updated_at else "未知"
        header = (
            f"# {note.title}\n\n"
            f"> 分类：{note.category or '未分类'} | 标签：{tags_str} | 更新日期：{updated_str}\n\n"
            f"---\n\n"
        )
        result_str = header + content
        if truncated:
            result_str += f"\n\n[提示：笔记内容超过 {MAX_CONTENT_CHARS} 字符，已截断]"
        return result_str

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

    @tool
    async def send_email(to: str, subject: str, body: str, format: str = "md") -> str:
        """
        发送邮件。这是唯一能真正把邮件发送出去的工具：当用户要求将笔记发送到邮箱时，必须调用本工具完成发送，
        不得仅用文字回复代替。支持以 Markdown 或 PDF 附件形式发送。

        调用前请先通过 get_user_info_tools 获取用户邮箱；
        若用户未绑定邮箱，请先询问用户要发送到的目标邮箱地址。

        Args:
            to: 收件人邮箱地址（必须与用户确认过）
            subject: 邮件主题（如 "笔记导出：{笔记标题}"）
            body: 邮件正文（Markdown 格式，建议包含笔记标题、分类/标签元信息和完整内容）
            format: 附件格式："md"（Markdown 附件，默认）/ "pdf"（PDF 附件）/ "text"（仅正文，无附件）
        """
        if not email_service:
            return "邮件服务未初始化，请联系管理员"
        try:
            attachments = None
            if format == "pdf":
                try:
                    pdf_bytes = email_service.render_markdown_pdf(subject, body)
                    attachments = [{
                        "filename": f"{re.sub(r'[\\\\/:*?\"<>|]', '_', subject)}.pdf",
                        "data": pdf_bytes,
                        "mime": "application/pdf",
                    }]
                except Exception as e:
                    # PDF 生成失败 → 降级为 Markdown 附件
                    logger.error(f"PDF 生成失败，降级为 MD 附件: {e}")
                    format = "md"
            if format == "md":
                attachments = attachments or [{
                    "filename": f"{re.sub(r'[\\\\/:*?\"<>|]', '_', subject)}.md",
                    "data": body.encode("utf-8"),
                    "mime": "text/markdown",
                }]

            await email_service.send_email(to, subject, body, attachments=attachments)
            fmt_label = {"md": "Markdown", "pdf": "PDF", "text": "文本"}.get(format, "Markdown")
            return f"笔记已成功以{fmt_label}形式发送至 {to}"
        except Exception as e:
            # 捕获所有异常返回友好提示，防止 SMTP 异常冒泡导致 Agent 循环中断
            logger.error(f"邮件发送失败: to={to}, error={e}")
            return f"邮件发送失败：{e}。请检查邮箱地址是否正确，或稍后重试。"

    # 全部工具注册表（名称 → 工具对象）
    all_tools = {
        "what_time_is_now": what_time_is_now,
        "get_user_info_tools": get_user_info_tools,
        "search_notes_tool": search_notes_tool,
        "get_note_content_tool": get_note_content_tool,
        "get_note_stats_tool": get_note_stats_tool,
        "get_today_reviews_tool": get_today_reviews_tool,
        "mark_reviewed_tool": mark_reviewed_tool,
        "create_note_tool": create_note_tool,
        "update_note_tool": update_note_tool,
        "get_related_notes_tool": get_related_notes_tool,
        "send_email": send_email,
    }

    # 按需加载：根据 groups 过滤工具   TODO: 未来可以增加工具组的动态注册机制，允许用户自定义工具组
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
