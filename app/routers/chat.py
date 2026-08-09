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
from app.core.task_runner import spawn_background_task
from app.core.failed_response import BusinessError, ErrorCode
from app.core.model_trace import set_trace_context, clear_trace_context, new_request_id
from app.db.database import get_db, async_session_factory
from app.schemas.chat import (
    QueryRequest, RAGRequest, ChatSessionListResponse,
    MessageListResponse, SessionTitleUpdate, UploadResponse,
)
from app.utils.auth_utils import get_current_user_id
from app.utils.time_utils import to_utc_iso
from app.utils.file_handler import read_upload_limited
from app.ai_service.chat_route import ChatRouteContext
from app.ai_service.chat_graph import stream_chat_graph
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
# 进程内兜底计数（Redis 不可用时降级；多进程部署以 Redis 计数为准，审查 M11）
_sse_active_counts: dict[str, int] = {}


async def _acquire_sse_slot(user_id: str) -> bool:
    """
    获取 SSE 连接槽位（Redis 计数优先，多进程部署天然生效）

    返回 True=获得槽位。Redis 不可用时降级进程内计数（保证聊天可用）。
    """
    from app.db.redis_client import get_redis

    try:
        redis = get_redis()
        key = f"sse_conn:{user_id}"
        count = await redis.incr(key)
        if count == 1:
            # TTL 兜底：连接异常释放时自动清理（120s > SSE 正常生命周期）
            await redis.expire(key, 120)
        if count > SSE_MAX_CONNECTIONS_PER_USER:
            await redis.decr(key)  # 回退计数
            logger.warning(f"SSE 连接数超限（Redis）: user={user_id[:8]}, count={count}")
            return False
        return True
    except Exception as e:
        # Redis 故障降级：进程内计数
        logger.warning(f"SSE Redis 计数不可用，降级进程内: {e}")

    if _sse_active_counts.get(user_id, 0) >= SSE_MAX_CONNECTIONS_PER_USER:
        logger.warning(f"SSE 连接数超限（进程内）: user={user_id[:8]}")
        return False
    _sse_active_counts[user_id] = _sse_active_counts.get(user_id, 0) + 1
    return True


async def _release_sse_slot(user_id: str) -> None:
    """释放 SSE 连接槽位（与 _acquire_sse_slot 对称；Redis 计数由 TTL 兜底清理）"""
    from app.db.redis_client import get_redis

    try:
        await get_redis().decr(f"sse_conn:{user_id}")
        return
    except Exception as e:
        logger.debug(f"SSE Redis 计数释放失败（TTL 自动清理兜底）: {e}")
    _sse_active_counts[user_id] = max(0, _sse_active_counts.get(user_id, 1) - 1)


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
        # 对外统一文案（审查 M15：内部异常细节仅入日志，不直出客户端）
        async def err_stream():
            yield f"data: {json.dumps({'type': 'error', 'content': '会话创建失败，请稍后重试'})}\n\n"
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
    
    # SSE 并发连接数检查（在昂贵操作之前拦截；Redis 计数，多进程部署天然生效）
    if not await _acquire_sse_slot(user_id):
        async def limit_stream():
            yield f"data: {json.dumps({'type': 'error', 'content': '并发连接数已达上限（最多 %d 个），请关闭多余标签页后重试' % SSE_MAX_CONNECTIONS_PER_USER})}\n\n"
        return StreamingResponse(limit_stream(), media_type="text/event-stream")
    
    # 标题生成模型（D 项：用轻量模型 flash，避免与主 Agent 抢 qwen3.7-max 并发导致
    # DashScope 连接不稳定；flash 不可用时降级主模型）。
    # 标题生成本身推迟到主 Agent 完成后执行（见 generate_stream 的 done 事件之后）
    title_model = getattr(init_manager, "classifier_model", None) or chat_model
    
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
            spawn_background_task(
                check_and_summarize(
                    chat_model=chat_model,
                    session_id=session_id,
                    threshold=threshold,
                    min_interval=min_interval,
                ),
                name="chat_summary_check",
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

    # ===== 解析用户选择的 PPT 模板（v1.4，设计方案 §6.5）=====
    # 与 <referenced_notes> 同段解析，注入 system_prompt 让 LLM 把 template_id
    # 填入 generate_ppt_tool（工具内强校验归属，双保险）
    ppt_template_text = ""
    _pt_match = _re.search(r'<ppt_template>\s*(.*?)\s*</ppt_template>', data.message, _re.DOTALL)
    if _pt_match:
        pt_block = _pt_match.group(1).strip()
        pt_lines = [l.strip() for l in pt_block.split('\n') if l.strip().startswith('- ID:')]
        if pt_lines:
            ppt_template_text = (
                "\n\n## 用户当前选择的 PPT 模板（生成讲解 PPT 时使用）：\n"
                + "\n".join(pt_lines)
                + "\n提示：当用户要求生成讲解 PPT 时，将上述模板 ID 填入 generate_ppt_tool 的 template_id 参数。"
            )
            logger.info(f"解析到 PPT 模板选择: {len(pt_lines)} 个")
    
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

    # 注入 PPT 模板选择到 system_prompt（v1.4，§6.5）
    if ppt_template_text:
        system_prompt += ppt_template_text
    
    # ===== SSE 流式响应生成器 =====
    async def generate_stream():
        """生成 SSE 流式响应（RAG + 记忆压缩已并行完成，直接生成）"""
        # SSE 连接计数由 _acquire_sse_slot 在请求进入时完成（Redis 优先）
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
            
            # ===== 执行对话编排图（P2-1 第二步：LangGraph StateGraph）=====
            # 查询分类 / 路由决策 / ReAct | Plan 执行全部在图内完成；
            # 事件流经总线产出，SSE 契约与改造前一致
            ctx = ChatRouteContext(
                agent_model=agent_model,
                plan_model=getattr(init_manager, "plan_model", None),
                classifier_model=getattr(init_manager, "classifier_model", None),
                user_id=user_id,
                user_message=data.message,
                system_prompt=system_prompt,
                compressed_messages=compressed_messages,
                db_session_factory=async_session_factory,
                note_service=note_service,
                review_service=review_service,
                email_service=init_manager.email_service,
                ppt_service=getattr(init_manager, "ppt_service", None),
                attachment_content=attachment_content,
                attachment_names=attachment_names or None,
                # 分层超时（审查 B）：单次 LLM 调用超时由模型 request_timeout 控制（120s，
                # factory.py）；此处为整轮 Agent 执行总预算。深度思考模式下单次 thinking
                # 调用可达 50-90s，整轮预算按模式放宽（与 plan_timeout 的 *2 策略对齐）
                react_timeout=LLM_STREAM_TIMEOUT * 2 if data.enable_thinking else LLM_STREAM_TIMEOUT,
                plan_timeout=LLM_STREAM_TIMEOUT * 2,
            )

            # 执行 + 事件转发（error 后不发 done、不保存回复，与改造前一致）
            accumulated = ""
            errored = False
            ppt_file_info = None   # tool_file 事件（持久化到消息附件，历史回放恢复下载卡片）
            async for event in stream_chat_graph(ctx):
                if event.get("type") == "response":
                    accumulated += event.get("content", "")
                elif event.get("type") == "error":
                    errored = True
                elif event.get("type") == "tool_file":
                    # 补全 AttachmentMeta 必填字段（file_type/original_name），
                    # 否则历史接口 MessageListResponse 校验 500（v1.6 修复）
                    if event.get("name") == "text_to_speech":
                        # TTS 语音：audio_url 随消息持久化，历史回放恢复播放/下载卡片
                        ppt_file_info = {
                            "file_id": event.get("file_id"),
                            "file_type": "tts",
                            "original_name": "语音朗读",
                            "download_url": event.get("audio_url"),
                            "duration_estimate": event.get("duration_estimate"),
                        }
                    else:
                        ppt_file_info = {
                            "file_id": event.get("file_id"),
                            "file_type": "ppt",
                            "original_name": event.get("title") or "讲解PPT",
                            "download_url": event.get("download_url"),
                            "title": event.get("title"),
                            "slide_count": event.get("slide_count"),
                        }
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            if errored:
                # 与现状一致：error 事件后不发送 done、不保存回复
                return

            # 异步保存 AI 回复到数据库 + Redis（非阻塞，不延迟 done 事件）
            # 回复保存成功后回填附件 message_id（绑定消息，禁止单独删除）
            if accumulated:
                async def _save_reply_and_bind():
                    await chat_service.save_message_with_commit(
                        session_id, user_id, "assistant", accumulated,
                        # PPT 下载信息随消息持久化（复用 attachments_json，切换页面后下载卡片仍可恢复）
                        attachments_json=[ppt_file_info] if ppt_file_info else None,
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

                spawn_background_task(_save_reply_and_bind(), name="chat_save_reply")
            
            # 发送完成事件（包含 RAG 来源信息）
            done_data = {'type': 'done', 'session_id': session_id}
            if rag_sources:
                done_data['sources'] = [
                    {'content': s.get('content', '')[:100], 'source': s.get('source', '')}
                    for s in rag_sources[:3]
                ]
            yield f"data: {json.dumps(done_data)}\n\n"

            # 主 Agent 完成后再生成标题（D 项：与主流程错峰执行，消除并发挤
            # DashScope 连接导致的 Connection error；轻量模型调用快，
            # 标题更新延迟几秒对用户无感。error 路径不触发——失败时标题无意义）
            spawn_background_task(
                chat_service.generate_and_update_title(
                    session_id, data.message, title_model,
                    attachment_names=attachment_names or None,
                ),
                name="chat_title_generate",
            )

        except Exception as e:
            logger.error(f"AI 对话流生成失败: {type(e).__name__}: {e}", exc_info=True)
            # 对外统一文案（审查 M15：内部异常细节仅入日志，不直出客户端）
            yield f"data: {json.dumps({'type': 'error', 'content': '生成失败，请稍后重试'})}\n\n"
        finally:
            # SSE 连接计数释放（生成器结束时释放，无论正常完成还是异常）
            await _release_sse_slot(user_id)
            logger.debug(f"SSE 连接 -1: user={user_id[:8]}")
    
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
        logger.error(f"RAG 查询失败: {type(e).__name__}: {e}", exc_info=True)
        # 审查 M3/M15：不再把错误吞进 200 成功响应；对外统一文案走全局异常处理器
        raise BusinessError(
            code=ErrorCode.LLM_CALL_FAILED,
            message="RAG 查询失败，请稍后重试",
        )


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
    # 分块限流读取（上限取图片/视频两者最大 50MB，防内存 DoS；
    # 具体类型限制由 chat_attachment_service 按 magic bytes 校验）
    content = await read_upload_limited(file, max_size_mb=50)
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
            "created_at": to_utc_iso(getattr(s, 'created_at', None)),
            "updated_at": to_utc_iso(getattr(s, 'updated_at', None)),
        }
    
    return success_response(data={"sessions": [_to_dict(s) for s in sessions]})


@router.delete("/chat/sessions/{session_id}", summary="删除会话")
async def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    删除指定会话及其所有消息

    级联清理会话文件（图片/视频附件 + PPT/TTS 工具产出文件）：
    先清附件（路由层职责，DatabaseSessionManager.delete_session 保持纯 DB 职责），
    再删会话/消息（ORM cascade），最后统一 commit。
    """
    async with async_session_factory() as db:
        # ① 用户上传的图片/视频附件（chat_attachments 表 + 文件）
        await chat_attachment_service.cleanup_by_session(db, session_id, user_id)
        # ② 工具产出文件（PPT/TTS，仅经消息 attachments_json 引用，不落表）
        await chat_attachment_service.cleanup_session_tool_files(db, session_id, user_id)
        # ③ 删除会话/消息（ORM cascade）
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

    # 兼容 tool_file 旧格式附件（缺 file_type/original_name），
    # 防止历史消息校验失败（v1.6 修复：读取时清洗，不依赖存量数据已被修复）
    for msg in messages:
        if msg.attachments_json:
            msg.attachments_json = [
                chat_service.normalize_attachment(a) for a in msg.attachments_json
            ]

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
