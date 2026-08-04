"""
聊天路由

端点：
- POST /chat/query - Agent 流式对话
- POST /chat/rag - RAG 查询
- GET /chat/sessions - 会话列表
- DELETE /chat/sessions/{session_id} - 删除会话
- GET /chat/{session_id}/messages - 消息历史（游标分页）
- PUT /chat/{session_id}/title - 修改会话标题
"""

import asyncio
import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, Query, UploadFile, File, Header
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger_handler import logger
from app.core.success_response import success_response
from app.core.rate_limit import rate_limit
from app.core.failed_response import BusinessError, ErrorCode
from app.core.model_trace import set_trace_context, clear_trace_context, set_trace_stage, new_request_id
from app.db.database import get_db, async_session_factory
from app.schemas.chat import (
    QueryRequest, RAGRequest, ChatSessionListResponse,
    MessageListResponse, SessionTitleUpdate, UploadResponse,
)
from app.utils.auth_utils import get_current_user_id
from app.services.chat_service import ChatService
from app.services.database_session_manager import DatabaseSessionManager
from app.services.chat_attachment_service import ChatAttachmentService

router = APIRouter()

# 服务实例
chat_service = ChatService()
session_manager = DatabaseSessionManager()
chat_attachment_service = ChatAttachmentService()

# LLM 流式响应超时时间（秒）
LLM_STREAM_TIMEOUT = int(os.getenv("LLM_STREAM_TIMEOUT", "60"))

# SSE 单用户最大并发连接数
# 防止恶意用户通过大量 SSE 连接耗尽服务器资源
SSE_MAX_CONNECTIONS_PER_USER = 3
_sse_active_counts: dict[str, int] = {}


class _AttachmentOnlyClassification:
    """仅附件消息的分类结果（无文本可分类，直接走 ReAct 多模态路径）"""
    complexity = "simple"
    source = "attachment"
    reason = "仅附件消息，无文本可分类"


def _estimate_attachment_tokens(attachments) -> int:
    """
    估算当前消息附件的 token 消耗（用于历史配额扣减，优先保证当前消息）

    图片按分辨率估算；视频按抽帧数 × 2000 估算。
    """
    from app.services.token_budget import TokenCounter

    total = 0
    video_frames = int(os.getenv("VIDEO_FRAME_COUNT", "8"))
    for att in attachments:
        if att.file_type == "image":
            total += TokenCounter.count_image(att.width, att.height)
        elif att.file_type == "video":
            total += video_frames * 2000
    return total


@router.post("/chat/query", summary="Agent 流式对话", dependencies=[Depends(rate_limit(endpoint_limit=10))])
async def chat_query(
    data: QueryRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Agent 流式对话接口
    
    支持 SSE 流式输出，包含思考过程推送。
    如果 session_id 为空，自动创建新会话。
    
    注意：不使用请求级 db session（Depends(get_db)），
    因为 StreamingResponse 返回后请求上下文会关闭 db，
    导致后续异步任务中 db.execute() 报 NoneType 错误。
    所有数据库操作均使用独立 session。
    """
    from main import init_manager
    from app.db.database import async_session_factory
    
    # ===== 附件处理（加载归属校验 + 绑定会话 + 随消息保存元数据）=====
    attachments = []
    attachment_meta_json = None
    attachment_names = []
    user_msg_id = None

    try:
        # 使用独立 session 获取或创建会话（不依赖请求级 db）
        async with async_session_factory() as db:
            session_id = await chat_service.get_or_create_session(db, user_id, data.session_id)  # 获取Session_id,如果已经存在就返回，否则创建一个新的session
            # 设置模型调用 trace 上下文（P0）：请求 ID + 用户 + 会话，供 factory 层回调读取
            set_trace_context(new_request_id(), user_id=user_id, session_id=session_id, stage="chat")
            # 附件归属校验（不属于当前用户的 ID 直接忽略）+ 绑定会话（脱离孤儿状态）
            if data.attachment_ids:
                attachments = await chat_attachment_service.get_owned_list(
                    db, user_id, data.attachment_ids
                )
                if attachments:
                    await chat_attachment_service.bind_session(
                        db, user_id, [a.file_id for a in attachments], session_id
                    )
            await db.commit()  # 提交事务，确保会话创建成功

        # 附件元数据（冗余存储到 chat_messages.attachments_json，供历史回显）
        if attachments:
            attachment_meta_json = [
                {
                    "file_id": a.file_id,
                    "file_type": a.file_type,
                    "original_name": a.original_name,
                    "file_size": a.file_size,
                    "mime_type": a.mime_type,
                    "width": a.width,
                    "height": a.height,
                    "duration_sec": a.duration_sec,
                }
                for a in attachments
            ]
            attachment_names = [a.original_name for a in attachments]

        # 用户消息内容兜底（空文本 + 附件 → 占位内容，避免空串入库）
        user_content = data.message
        if not user_content.strip() and attachment_meta_json:
            user_content = "[视频]" if any(a.file_type == "video" for a in attachments) else "[图片]"

        # 保存用户消息（使用独立 session + commit，确保持久化）
        user_msg_id = await chat_service.save_message_with_commit(
            session_id, user_id, "user", user_content,
            data.idempotency_key,
            attachments_json=attachment_meta_json,
        )
    except Exception as e:
        logger.error(f"会话/消息初始化失败: {type(e).__name__}: {e}", exc_info=True)
        async def err_stream():
            yield f"data: {json.dumps({'type': 'error', 'content': f'会话创建失败: {str(e)}'})}\n\n"
        return StreamingResponse(err_stream(), media_type="text/event-stream")
    
    # 获取 AI 模型（等待后台初始化完成）
    if not init_manager.stage1_complete.is_set():
        logger.info("等待 AI 模型初始化完成...")
        try:
            await asyncio.wait_for(init_manager.stage1_complete.wait(), timeout=30)
        except asyncio.TimeoutError:
            async def timeout_stream():
                yield f"data: {json.dumps({'type': 'error', 'content': 'AI 模型初始化超时，请稍后重试'})}\n\n"
            return StreamingResponse(timeout_stream(), media_type="text/event-stream")
    
    # 模型选择（两个实例分工）：
    # - chat_model：文本任务模型（会话标题 / RAG / 记忆摘要），始终用主模型，不受附件影响
    # - agent_model：执行 Agent 链路的模型——
    #     附件（图片/视频）请求 → 视觉模型（设计 §6.1：VISION_MODEL 与聊天主模型分离）
    #     纯文本 + 深度思考   → 思考模型实例
    #     默认              → 主模型
    # ⚠️ 附件 + 深度思考：深度思考对附件场景自动失效（视觉模型不支持思考，
    #    且 qwen3.8-max thinking + 多模态实测首 token 延迟 >60s 必超时）
    chat_model = init_manager.chat_model
    if attachments:
        vision_model = getattr(init_manager, "vision_model", None)
        if vision_model:
            agent_model = vision_model
            logger.info(f"附件请求使用视觉模型: {getattr(vision_model, 'model_name', 'vision_model')} (user={user_id[:8]})")
        else:
            agent_model = chat_model
            logger.warning(f"视觉模型不可用，附件理解降级主模型: user={user_id[:8]}")
    elif data.enable_thinking and getattr(init_manager, "chat_model_thinking", None):
        agent_model = init_manager.chat_model_thinking
        logger.debug(f"深度思考模式已开启: user={user_id[:8]}")
    else:
        agent_model = chat_model

    if not chat_model or not agent_model:
        # 模型未初始化，返回错误 SSE
        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'content': 'AI 模型未初始化'})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")
    
    # SSE 并发连接数检查（在昂贵操作之前拦截）
    if _sse_active_counts.get(user_id, 0) >= SSE_MAX_CONNECTIONS_PER_USER:
        logger.warning(f"SSE 连接数超限: user_id={user_id}, count={_sse_active_counts[user_id]}")
        async def limit_stream():
            yield f"data: {json.dumps({'type': 'error', 'content': '并发连接数已达上限（最多 %d 个），请关闭多余标签页后重试' % SSE_MAX_CONNECTIONS_PER_USER})}\n\n"
        return StreamingResponse(limit_stream(), media_type="text/event-stream")
    
    # 后台触发自动更新会话标题（非阻塞，chat_model 已就绪；仅发附件时用附件名兜底）
    asyncio.create_task(
        chat_service.generate_and_update_title(
            session_id, data.message, chat_model,
            attachment_names=attachment_names or None,
        )
    )
    
    # ===== 并行执行 RAG 检索 + 记忆压缩（两者无数据依赖）=====
    from datetime import datetime
    from app.utils.prompt_loader import load_prompt
    from app.utils.config import get_agent_config, get_rag_config
    from langchain_core.messages import HumanMessage, AIMessage
    from app.services.token_budget import TokenBudget
    from app.services.memory_compressor import MemoryCompressor, check_and_summarize
    from app.utils.config import get_token_budget_config, get_memory_compression_config
    
    rag_context = ""
    rag_sources = []
    compressed_messages = []
    
    async def _run_rag():
        """RAG 检索协程（含路由判断：与知识库无关的查询跳过 RAG）"""
        nonlocal rag_context, rag_sources
        if not data.message.strip():
            return  # 仅附件消息：无查询文本，跳过 RAG
        try:
            await asyncio.wait_for(init_manager.stage2_complete.wait(), timeout=5)
            
            from app.rag.vector_store import VectorStoreService
            
            vector_store = VectorStoreService()
            
            # 路由判断：先检查查询与知识库的相关性
            route_threshold = float(os.getenv("RAG_ROUTE_THRESHOLD", "0.5"))
            try:
                route_distance = await vector_store.compute_route_score(data.message)
                if route_distance > route_threshold:
                    logger.debug(f"路由判断跳过 RAG: distance={route_distance:.3f} > threshold={route_threshold}")
                    return  # 与知识库无关，跳过 RAG
            except Exception as e:
                logger.debug(f"路由判断失败，继续执行 RAG: {e}")
            
            # 复用 init_manager 中的 RagService 实例，避免每次请求重建
            rag_service = getattr(init_manager, 'rag_service', None)
            if rag_service is None:
                from app.rag.rag_service import RagService
                reranker = getattr(init_manager, 'reorder_service', None)
                rag_config = get_rag_config()
                rag_service = RagService(
                    vector_store=vector_store,
                    chat_model=chat_model,
                    rerank_model=reranker,
                    enable_summarize=rag_config.get("enable_summarize", False),
                )
            
            rag_result = await rag_service.query(
                query_text=data.message,
                user_id=user_id,
                top_k=3,
                use_hyde=False,
            )
            rag_context = rag_result.get("context", "")
            rag_sources = rag_result.get("sources", [])
            
            if rag_context:
                logger.info(f"RAG 检索成功: {len(rag_sources)} 个来源, context 长度={len(rag_context)}")
            else:
                logger.debug("RAG 检索无结果")
        except asyncio.TimeoutError:
            logger.debug("RAG 服务未就绪，跳过知识库检索")
        except Exception as e:
            logger.warning(f"RAG 查询失败，跳过: {e}")
    
    async def _run_memory_compression():
        """记忆压缩协程"""
        nonlocal compressed_messages
        try:
            tb_config = get_token_budget_config()
            mc_config = get_memory_compression_config()
            
            # 并行执行两次 DB 查询（使用独立 session）
            async def _get_messages():
                async with async_session_factory() as db:
                    return await session_manager.get_all_messages(db, session_id)
            
            async def _get_summary():
                async with async_session_factory() as db:
                    return await session_manager.get_summary(db, session_id)
            
            all_msgs, summary_obj = await asyncio.gather(
                _get_messages(), _get_summary()
            )
            
            all_messages = [
                {
                    "role": m.role,
                    "content": m.content,
                    "attachments": m.attachments_json or [],
                }
                for m in all_msgs
            ]
            existing_summary = summary_obj.summary_text if summary_obj else ""
            prev_messages = all_messages[:-1] if all_messages else []

            # 预加载历史附件图片 base64（最近 2 条用户消息，支持"上一张图里…"追问）
            await _preload_history_images(prev_messages)

            # 先用估算值创建 budget（RAG 上下文长度未知时用默认值）
            budget = TokenBudget(
                model_context_size=tb_config.get("model_context_size", 32768),
                system_prompt=tb_config.get("system_prompt", 500),
                rag_context_max=tb_config.get("rag_context_max", 2000),
                summary_max=tb_config.get("summary_max", 800),
                agent_scratchpad_reserve=tb_config.get("agent_scratchpad_reserve", 4000),
                current_input_estimate=tb_config.get("current_input_estimate", 300),
                safety_margin=tb_config.get("safety_margin", 1000),
                image_tokens_per_msg=tb_config.get("image_tokens_per_msg", 3000),
                max_history_images=tb_config.get("max_history_images", 4),
            )
            # 用 RAG 最大配额估算（实际 RAG 结果未就绪时用上限值）
            history_quota = budget.allocate("" * tb_config.get("rag_context_max", 2000))
            # 当前消息附件 token 从历史配额中扣减（优先保证当前消息）
            history_quota = max(500, history_quota - _estimate_attachment_tokens(attachments))

            compressor = MemoryCompressor(budget)
            compressed_messages, history_tokens = compressor.build_context(
                all_messages=prev_messages,
                existing_summary=existing_summary,
                token_quota=history_quota,
            )
            
            logger.info(
                f"记忆压缩完成: session={session_id[:12]}, "
                f"total_msgs={len(prev_messages)}, window_msgs={len(compressed_messages)}, "
                f"history_tokens={history_tokens}, quota={history_quota}, "
                f"has_summary={bool(existing_summary)}"
            )
            
            # 异步触发里程碑摘要检查（非阻塞）
            threshold = mc_config.get("summarize_threshold", 40)
            min_interval = mc_config.get("min_summary_interval", 20)
            asyncio.create_task(
                check_and_summarize(
                    chat_model=chat_model,
                    session_id=session_id,
                    threshold=threshold,
                    min_interval=min_interval,
                )
            )
        except Exception as e:
            logger.warning(f"记忆压缩管线失败，回退到简单截断: {e}")
            max_rounds = get_agent_config().get("max_history_rounds", 20)
            try:
                recent = await chat_service.session_manager.get_recent_messages(
                    session_id, limit=max_rounds * 2
                )
                for msg in recent:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if role == "user":
                        # 附件以文本占位（降级路径不做图片预编码，保证 Agent 感知附件存在）
                        atts = msg.get("attachments_json") or []
                        if atts:
                            names = [
                                a.get("original_name", "附件")
                                for a in atts if isinstance(a, dict)
                            ]
                            content = f"{content}\n[附件: {', '.join(names[:3])}]"
                        compressed_messages.append(HumanMessage(content=content))
                    elif role == "assistant":
                        compressed_messages.append(AIMessage(content=content))
            except Exception:
                pass
    
    async def _preload_history_images(msgs: list) -> None:
        """
        预加载历史消息附件图片的 base64（多模态回放用）

        最多处理最近 max_user_msgs 条带图片附件的用户消息，每条最多 max_history_images 张；
        图片压缩走线程池（CPU 密集），结果按 file_id 缓存（与当前消息处理共享缓存）。
        attachments_json 不含存储路径，需查 chat_attachments 权威表。
        """
        from app.ai_service.multimodal_processor import process_image_to_base64

        max_user_msgs = 2
        max_images = int(os.getenv("CHAT_MAX_IMAGES_PER_MSG", "6"))
        processed = 0
        for msg in reversed(msgs):
            if processed >= max_user_msgs:
                break
            atts = msg.get("attachments") or []
            images = [
                a for a in atts
                if isinstance(a, dict) and a.get("file_type") == "image"
            ]
            if not images:
                continue
            processed += 1
            images = images[-max_images:]
            file_ids = [a["file_id"] for a in images]
            try:
                async with async_session_factory() as db:
                    rows = await chat_attachment_service.get_owned_list(db, user_id, file_ids)
            except Exception as e:
                logger.debug(f"历史附件路径查询失败: {e}")
                continue
            path_map = {r.file_id: r.stored_path for r in rows}
            b64s = []
            for img in images:
                rel_path = path_map.get(img["file_id"])
                if not rel_path:
                    continue
                abs_path = os.path.join(os.getcwd(), rel_path)
                if not os.path.isfile(abs_path):
                    continue
                try:
                    b64 = await asyncio.to_thread(
                        process_image_to_base64, abs_path, img["file_id"]
                    )
                    b64s.append(b64)
                except Exception as e:
                    logger.debug(f"历史图片预编码失败: file_id={img['file_id'][:8]}, err={e}")
            msg["image_b64s"] = b64s
            logger.debug(f"历史附件图片预编码: {len(b64s)} 张 (message attachments={len(images)})")

    # 并行执行 RAG + 记忆压缩
    await asyncio.gather(_run_rag(), _run_memory_compression())
    
    # ===== 解析用户引用的笔记（从消息中提取结构化引用块）=====
    import re as _re
    referenced_notes_text = ""
    _ref_match = _re.search(r'<referenced_notes>\s*(.*?)\s*</referenced_notes>', data.message, _re.DOTALL)
    if _ref_match:
        ref_block = _ref_match.group(1).strip()
        # 解析每行："- ID: xxx | 标题: yyy"
        ref_lines = [l.strip() for l in ref_block.split('\n') if l.strip().startswith('- ID:')]
        if ref_lines:
            referenced_notes_text = (
                "\n\n## 用户当前引用的笔记（可直接使用 ID 操作）：\n"
                + "\n".join(ref_lines)
                + "\n提示：当用户要求修改/更新/编辑这些笔记时，直接使用上述 ID 调用 update_note_tool，无需再次搜索。"
            )
            logger.info(f"解析到引用笔记: {len(ref_lines)} 篇")
    
    # 构建 system_prompt（注入 RAG 上下文 + 引用笔记 ID）
    try:
        system_prompt = load_prompt("main")
        system_prompt = system_prompt.replace("{current_time}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        system_prompt = "你是一个智能笔记助手，帮助用户管理知识、检索信息和回答问题。"
    
    if rag_context:
        system_prompt += (
            "\n\n以下是从知识库和笔记中检索到的相关内容，请在回答时优先参考：\n"
            "<reference>\n"
            f"{rag_context}\n"
            "</reference>"
        )
    
    # 注入引用笔记 ID 到 system_prompt（让 Agent 知道可以直接操作的笔记）
    if referenced_notes_text:
        system_prompt += referenced_notes_text
    
    # ===== SSE 流式响应生成器 =====
    async def generate_stream():
        """生成 SSE 流式响应（RAG + 记忆压缩已并行完成，直接生成）"""
        # SSE 连接计数 +1（在生成器内部，确保只有实际流式传输时才占用连接槽）
        _sse_active_counts[user_id] = _sse_active_counts.get(user_id, 0) + 1
        logger.debug(f"SSE 连接 +1: user={user_id[:8]}, active={_sse_active_counts[user_id]}")
        try:
            # 发送思考事件
            if rag_context:
                yield f"data: {json.dumps({'type': 'thinking', 'stage': 'rag', 'content': f'已从知识库检索到 {len(rag_sources)} 个相关文档'})}\n\n"
            yield f"data: {json.dumps({'type': 'thinking', 'stage': 'processing', 'content': '正在思考...'})}\n\n"

            # ===== 附件多模态内容组装（图片压缩 / 视频抽帧，CPU 密集 → 线程池）=====
            attachment_content = []
            if attachments:
                from app.ai_service.multimodal_processor import build_attachment_blocks_async
                if data.enable_thinking:
                    yield f"data: {json.dumps({'type': 'thinking', 'stage': 'attachment', 'content': '深度思考对附件场景自动关闭（视觉模型理解附件）'})}\n\n"
                if getattr(init_manager, "vision_model", None) is None:
                    yield f"data: {json.dumps({'type': 'thinking', 'stage': 'attachment', 'content': '视觉模型未就绪，当前只能基于文字回复'})}\n\n"
                if any(a.file_type == "video" for a in attachments):
                    yield f"data: {json.dumps({'type': 'thinking', 'stage': 'attachment', 'content': '正在解析视频（抽帧）...'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'thinking', 'stage': 'attachment', 'content': '正在处理附件...'})}\n\n"
                try:
                    attachment_content = await build_attachment_blocks_async(attachments)
                except Exception as e:
                    logger.warning(f"附件多模态处理失败: {e}", exc_info=True)
                    attachment_content = []
                if attachment_content:
                    yield f"data: {json.dumps({'type': 'thinking', 'stage': 'attachment', 'content': f'附件解析完成（{len(attachment_content)} 张图像）'})}\n\n"

            # ===== 查询复杂度分类 + 混合路由 =====
            from app.ai_service.query_classifier import QueryClassifier

            if data.message.strip():
                set_trace_stage("classify")  # 模型 trace 阶段标记（P0）
                classifier = QueryClassifier(llm_model=getattr(init_manager, 'classifier_model', None))
                classification = await classifier.classify(data.message)  # 分类结果包含 complexity, source, reason，判断复杂度
            else:
                # 仅附件消息：无文本可分类，直接走 ReAct 多模态路径
                classification = _AttachmentOnlyClassification()
                logger.info("仅附件消息，跳过复杂度分类，直接走 ReAct 多模态路径")
            logger.info(
                f"查询分类: complexity={classification.complexity}, "
                f"source={classification.source}, reason={classification.reason}"
            )
            
            # 获取笔记服务和回顾服务（等待阶段 2 完成，最多等待 5 秒）
            note_service = None
            review_service = None
            try:
                await asyncio.wait_for(init_manager.stage2_complete.wait(), timeout=5)
                note_service = init_manager.note_service
                if note_service:
                    from app.services.review_service import ReviewService
                    review_service = ReviewService()
                    logger.debug(f"Agent 工具服务注入成功: note_service={type(note_service).__name__}, review_service=ReviewService")
                else:
                    logger.warning("note_service 为 None，笔记相关工具将不可用")
            except asyncio.TimeoutError:
                logger.warning("等待 NoteService 初始化超时(5s)，笔记相关工具不可用")
            except Exception as e:
                logger.warning(f"获取 Agent 工具服务失败: {e}")
            
            accumulated = ""
            
            if classification.complexity == "simple":
                # ===== 简单问题：走现有 ReAct Agent（逻辑完全不变）=====
                set_trace_stage("agent")  # 模型 trace 阶段标记（P0）
                from app.ai_service.agent_runner import execute_agent

                async for event in execute_agent(
                    chat_model=agent_model,
                    user_id=user_id,
                    user_message=data.message,
                    system_prompt=system_prompt,
                    compressed_messages=compressed_messages,
                    db_session_factory=async_session_factory,
                    note_service=note_service,
                    review_service=review_service,
                    email_service=init_manager.email_service,
                    timeout=LLM_STREAM_TIMEOUT,
                    attachment_content=attachment_content,
                ):
                    event_type = event.get("type", "")
                    
                    if event_type == "response":
                        accumulated += event.get("content", "")
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    elif event_type == "error":
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                        return
                    elif event_type == "stream_done":
                        break
            else:
                # ===== 复杂问题：走 Plan-and-Execute Agent =====
                set_trace_stage("plan_execute")  # 模型 trace 阶段标记（P0）
                plan_model = getattr(init_manager, 'plan_model', None)  # 获取用于制定计划的模型
                
                if plan_model is None:
                    # Plan 模型不可用，降级为 ReAct
                    logger.warning("Plan 模型不可用，复杂查询降级为 ReAct")
                    from app.ai_service.agent_runner import execute_agent
                    
                    async for event in execute_agent(
                        chat_model=agent_model,
                        user_id=user_id,
                        user_message=data.message,
                        system_prompt=system_prompt,
                        compressed_messages=compressed_messages,
                        db_session_factory=async_session_factory,
                        note_service=note_service,
                        review_service=review_service,
                        timeout=LLM_STREAM_TIMEOUT,
                        attachment_content=attachment_content,
                    ):
                        event_type = event.get("type", "")
                        if event_type == "response":
                            accumulated += event.get("content", "")
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                        elif event_type == "error":
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                            return
                        elif event_type == "stream_done":
                            break
                else:   # Plan 模型可用，执行 Plan-and-Execute
                    from app.ai_service.plan_execute_agent import execute_plan_agent

                    async for event in execute_plan_agent(
                        chat_model=agent_model,
                        plan_model=plan_model,
                        user_id=user_id,
                        user_message=data.message,
                        system_prompt=system_prompt,
                        compressed_messages=compressed_messages,
                        db_session_factory=async_session_factory,
                        note_service=note_service,
                        review_service=review_service,
                        email_service=init_manager.email_service,
                        timeout=LLM_STREAM_TIMEOUT * 2,
                        attachment_content=attachment_content,
                        attachment_names=attachment_names or None,
                    ):
                        event_type = event.get("type", "")
                        
                        if event_type == "response":
                            accumulated += event.get("content", "")
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                        elif event_type == "error":
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                            return
                        elif event_type == "plan_fallback":
                            # Plan 失败，降级为 ReAct
                            logger.info(f"Plan 降级: {event.get('reason', '')}")
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                            from app.ai_service.agent_runner import execute_agent
                            
                            async for fallback_event in execute_agent(
                                chat_model=agent_model,
                                user_id=user_id,
                                user_message=data.message,
                                system_prompt=system_prompt,
                                compressed_messages=compressed_messages,
                                db_session_factory=async_session_factory,
                                note_service=note_service,
                                review_service=review_service,
                                timeout=LLM_STREAM_TIMEOUT,
                                attachment_content=attachment_content,
                            ):
                                ft = fallback_event.get("type", "")
                                if ft == "response":
                                    accumulated += fallback_event.get("content", "")
                                    yield f"data: {json.dumps(fallback_event, ensure_ascii=False)}\n\n"
                                elif ft == "error":
                                    yield f"data: {json.dumps(fallback_event, ensure_ascii=False)}\n\n"
                                    return
                                elif ft == "stream_done":
                                    break
                            break
                        elif event_type in (
                            "plan_start", "plan_step", "plan_step_start",
                            "plan_step_end", "plan_synthesize", "plan_complete",
                        ):
                            # 推送 Plan 事件给前端
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                        elif event_type in ("tool_start", "tool_end"):
                            # 透传工具调用状态（让前端知道正在执行工具）
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            
            # 异步保存 AI 回复到数据库 + Redis（非阻塞，不延迟 done 事件）
            # 回复保存成功后回填附件 message_id（绑定消息，禁止单独删除）
            if accumulated:
                async def _save_reply_and_bind():
                    await chat_service.save_message_with_commit(
                        session_id, user_id, "assistant", accumulated
                    )
                    if user_msg_id and attachments:
                        try:
                            async with async_session_factory() as db:
                                await chat_attachment_service.bind_message(
                                    db, user_id,
                                    [a.file_id for a in attachments],
                                    session_id, user_msg_id,
                                )
                                await db.commit()
                        except Exception as e:
                            logger.warning(f"附件绑定消息失败: {e}")

                asyncio.create_task(_save_reply_and_bind())
            
            # 发送完成事件（包含 RAG 来源信息）
            done_data = {'type': 'done', 'session_id': session_id}
            if rag_sources:
                done_data['sources'] = [
                    {'content': s.get('content', '')[:100], 'source': s.get('source', '')}
                    for s in rag_sources[:3]
                ]
            yield f"data: {json.dumps(done_data)}\n\n"
            
        except Exception as e:
            logger.error(f"AI 对话流生成失败: {type(e).__name__}: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': f'生成失败: {str(e)}'})}\n\n"
        finally:
            # SSE 连接计数 -1（生成器结束时释放，无论正常完成还是异常）
            _sse_active_counts[user_id] = max(0, _sse_active_counts.get(user_id, 1) - 1)
            logger.debug(f"SSE 连接 -1: user={user_id[:8]}, active={_sse_active_counts.get(user_id, 0)}")
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲  #TODO  这为什么要禁用Nginx缓冲
        }
    )


@router.post("/chat/rag", summary="RAG 查询", dependencies=[Depends(rate_limit(endpoint_limit=10))])
async def rag_query(
    data: RAGRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    RAG 知识库查询接口
    
    执行完整的 RAG 管线：HyDE → 双源检索 → 重排序 → 总结。
    """
    from main import init_manager
    
    # 等待 VectorStore 初始化完成
    if not init_manager.stage2_complete.is_set():
        try:
            await asyncio.wait_for(init_manager.stage2_complete.wait(), timeout=10)
        except asyncio.TimeoutError:
            return success_response(data={
                "answer": "知识库服务尚未就绪，请稍后重试",
                "sources": [],
            })
    
    try:
        from app.rag.vector_store import VectorStoreService
        from app.rag.rag_service import RagService
        from app.utils.config import get_rag_config
        
        vector_store = VectorStoreService()
        chat_model = init_manager.chat_model
        reranker = getattr(init_manager, 'reorder_service', None)
        rag_config = get_rag_config()
        
        rag_service = RagService(
            vector_store=vector_store,
            chat_model=chat_model,
            rerank_model=reranker,
            enable_summarize=rag_config.get("enable_summarize", False),
        )
        
        result = await rag_service.query(
            query_text=data.query,
            user_id=user_id,
            top_k=data.top_k,
            use_hyde=data.use_hyde,
        )
        
        return success_response(data={
            "answer": result.get("context", ""),
            "sources": result.get("sources", []),
        })
    except Exception as e:
        logger.error(f"RAG 查询失败: {e}", exc_info=True)
        return success_response(data={
            "answer": f"RAG 查询失败: {str(e)}",
            "sources": [],
        })


# ============================================================
# 聊天附件端点（图片/视频）
# ============================================================

@router.post("/chat/files", summary="上传聊天附件（图片/视频）", dependencies=[Depends(rate_limit(endpoint_limit=10))])
async def upload_chat_file(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    """
    上传图片/视频附件

    校验：扩展名白名单 + magic bytes 双重校验、大小限制（图片 10MB / 视频 50MB）、
    用户配额（USER_STORAGE_QUOTA_MB）。
    上传后附件为孤儿状态（未绑定会话），24h 内未随消息发送会被定时清理。
    """
    content = await file.read()
    async with async_session_factory() as db:
        attachment = await chat_attachment_service.save_upload(
            db, user_id, file.filename or "", content
        )
        # server_default 的 created_at 需显式刷新加载，且在 session 内取值
        # （commit 后 session 关闭，延迟属性访问会抛 DetachedInstanceError）
        await db.refresh(attachment)
        resp_data = UploadResponse(
            file_id=attachment.file_id,
            file_type=attachment.file_type,
            mime_type=attachment.mime_type,
            original_name=attachment.original_name,
            file_size=attachment.file_size,
            width=attachment.width,
            height=attachment.height,
            duration_sec=attachment.duration_sec,
            created_at=attachment.created_at,
        ).model_dump()
        await db.commit()

    return success_response(data=resp_data)


@router.get("/chat/files/{file_id}", summary="预览/下载聊天附件")
async def get_chat_file(
    file_id: str,
    authorization: Optional[str] = Header(None),
    token: str = Query(None, description="可选 JWT：<img>/<video> 标签无法携带 Header 时以 query 参数鉴权"),
):
    """
    附件预览/下载（JWT 鉴权 + 归属校验）

    文件不存在或不属于当前用户时统一返回 404（防枚举探测）。
    Starlette FileResponse 原生支持 HTTP Range（视频拖动进度条）。

    鉴权方式：
    1. 常规：Authorization: Bearer <JWT>（fetch 等场景）
    2. 回显兜底：?token=<JWT>（<img>/<video> 标签无法携带 Header）
       token 为短时效 access token（默认 30 分钟），仅用于当次回显，风险可控。
    """
    from app.utils.auth_utils import decode_token
    from app.core.failed_response import BusinessError as _BE
    from app.core.failed_response import ErrorCode as _EC

    # 解析 token：优先 Header，其次 query 参数
    token_str = None
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token_str = parts[1]
    if not token_str:
        token_str = token
    if not token_str:
        raise _BE(code=_EC.TOKEN_INVALID, message="缺少认证信息", http_status=401)

    payload = decode_token(token_str)
    if payload.get("type") != "access":
        raise _BE(code=_EC.TOKEN_INVALID, message="Token 类型错误", http_status=401)
    user_id = payload.get("sub", "")
    if not user_id:
        raise _BE(code=_EC.TOKEN_INVALID, message="Token 缺少用户标识", http_status=401)

    async with async_session_factory() as db:
        attachment = await chat_attachment_service.get_owned(db, user_id, file_id)

    file_path = os.path.join(os.getcwd(), attachment.stored_path)
    if not os.path.isfile(file_path):
        raise BusinessError(code=ErrorCode.ATTACHMENT_NOT_FOUND, http_status=404)

    return FileResponse(
        file_path,
        media_type=attachment.mime_type,
        filename=attachment.original_name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.delete("/chat/files/{file_id}", summary="删除未绑定附件")
async def delete_chat_file(
    file_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    删除附件（仅允许未绑定消息的附件）

    已随消息发送的附件不可单独删除（随会话删除级联清理）。
    """
    async with async_session_factory() as db:
        await chat_attachment_service.delete_unbound(db, user_id, file_id)
        await db.commit()
    return success_response(message="附件已删除")


@router.get("/chat/sessions", summary="获取会话列表")
async def list_sessions(
    user_id: str = Depends(get_current_user_id),
):
    """获取当前用户的所有聊天会话"""
    async with async_session_factory() as db:
        sessions = await session_manager.list_sessions(db, user_id)
    
    # 兼容 ORM 对象和 Redis 缓存返回的 dict
    def _to_dict(s):
        if isinstance(s, dict):
            return {
                "id": s.get("id"),
                "title": s.get("title"),
                "created_at": s.get("created_at"),
                "updated_at": s.get("updated_at"),
            }
        return {
            "id": s.id,
            "title": s.title,
            "created_at": s.created_at.isoformat() if hasattr(s, 'created_at') and s.created_at else None,
            "updated_at": s.updated_at.isoformat() if hasattr(s, 'updated_at') and s.updated_at else None,
        }
    
    return success_response(data={"sessions": [_to_dict(s) for s in sessions]})


@router.delete("/chat/sessions/{session_id}", summary="删除会话")
async def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    删除指定会话及其所有消息

    级联清理会话附件（文件 + chat_attachments 行）：
    先清附件（路由层职责，DatabaseSessionManager.delete_session 保持纯 DB 职责），
    再删会话/消息（ORM cascade），最后统一 commit。
    """
    async with async_session_factory() as db:
        await chat_attachment_service.cleanup_by_session(db, session_id, user_id)
        await session_manager.delete_session(db, session_id, user_id)
        await db.commit()
    return success_response(message="会话已删除")


@router.get("/chat/{session_id}/messages", summary="获取消息历史")
async def get_messages(
    session_id: str,
    cursor: str = Query(None, description="分页游标（上一页最早消息的 created_at）"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    user_id: str = Depends(get_current_user_id),
):
    """
    获取消息历史（游标分页）
    
    使用 created_at 作为游标，避免 LIMIT/OFFSET 翻页不一致问题。
    """
    async with async_session_factory() as db:
        messages, has_more = await session_manager.get_messages(
            db, session_id, user_id, cursor=cursor, limit=limit
        )
    
    next_cursor = None
    if has_more and messages:
        next_cursor = messages[0].created_at.isoformat()
    
    return success_response(data=MessageListResponse(
        messages=messages,
        has_more=has_more,
        next_cursor=next_cursor,
    ).model_dump())


@router.put("/chat/{session_id}/title", summary="修改会话标题")
async def update_session_title(
    session_id: str,
    data: SessionTitleUpdate,
    user_id: str = Depends(get_current_user_id),
):
    """手动修改会话标题"""
    async with async_session_factory() as db:
        session = await session_manager.get_session(db, session_id, user_id)
        session.title = data.title
        await db.commit()
    
    return success_response(message="标题已更新")
