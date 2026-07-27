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

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger_handler import logger
from app.core.success_response import success_response
from app.core.rate_limit import rate_limit
from app.db.database import get_db, async_session_factory
from app.schemas.chat import (
    QueryRequest, RAGRequest, ChatSessionListResponse,
    MessageListResponse, SessionTitleUpdate,
)
from app.utils.auth_utils import get_current_user_id
from app.services.chat_service import ChatService
from app.services.database_session_manager import DatabaseSessionManager

router = APIRouter()

# 服务实例
chat_service = ChatService()
session_manager = DatabaseSessionManager()

# LLM 流式响应超时时间（秒）
LLM_STREAM_TIMEOUT = int(os.getenv("LLM_STREAM_TIMEOUT", "60"))


@router.post("/chat/query", summary="Agent 流式对话")
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
    
    try:
        # 使用独立 session 获取或创建会话（不依赖请求级 db）
        async with async_session_factory() as db:
            session_id = await chat_service.get_or_create_session(db, user_id, data.session_id)  # 获取Session_id,如果已经存在就返回，否则创建一个新的session
            await db.commit()  # 提交事务，确保会话创建成功
        
        # 保存用户消息（使用独立 session + commit，确保持久化）
        await chat_service.save_message_with_commit(
            session_id, user_id, "user", data.message, data.idempotency_key
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
    
    chat_model = init_manager.chat_model
    
    if not chat_model:
        # 模型未初始化，返回错误 SSE
        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'content': 'AI 模型未初始化'})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")
    
    # 后台触发自动更新会话标题（非阻塞，chat_model 已就绪）
    asyncio.create_task(
        chat_service.generate_and_update_title(session_id, data.message, chat_model)
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
                {"role": m.role, "content": m.content}
                for m in all_msgs
            ]
            existing_summary = summary_obj.summary_text if summary_obj else ""
            prev_messages = all_messages[:-1] if all_messages else []
            
            # 先用估算值创建 budget（RAG 上下文长度未知时用默认值）
            budget = TokenBudget(
                model_context_size=tb_config.get("model_context_size", 32768),
                system_prompt=tb_config.get("system_prompt", 500),
                rag_context_max=tb_config.get("rag_context_max", 2000),
                summary_max=tb_config.get("summary_max", 800),
                agent_scratchpad_reserve=tb_config.get("agent_scratchpad_reserve", 4000),
                current_input_estimate=tb_config.get("current_input_estimate", 300),
                safety_margin=tb_config.get("safety_margin", 1000),
            )
            # 用 RAG 最大配额估算（实际 RAG 结果未就绪时用上限值）
            history_quota = budget.allocate("" * tb_config.get("rag_context_max", 2000))
            
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
                        compressed_messages.append(HumanMessage(content=content))
                    elif role == "assistant":
                        compressed_messages.append(AIMessage(content=content))
            except Exception:
                pass
    
    # 并行执行 RAG + 记忆压缩
    await asyncio.gather(_run_rag(), _run_memory_compression())
    
    # 构建 system_prompt（注入 RAG 上下文）
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
    
    # ===== SSE 流式响应生成器 =====
    async def generate_stream():
        """生成 SSE 流式响应（RAG + 记忆压缩已并行完成，直接生成）"""
        try:
            # 发送思考事件
            if rag_context:
                yield f"data: {json.dumps({'type': 'thinking', 'stage': 'rag', 'content': f'已从知识库检索到 {len(rag_sources)} 个相关文档'})}\n\n"
            yield f"data: {json.dumps({'type': 'thinking', 'stage': 'processing', 'content': '正在思考...'})}\n\n"
            
            # ===== 查询复杂度分类 + 混合路由 =====
            from app.ai_service.query_classifier import QueryClassifier
            
            classifier = QueryClassifier(llm_model=getattr(init_manager, 'classifier_model', None))
            classification = await classifier.classify(data.message)  # 分类结果包含 complexity, source, reason，判断复杂度
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
                from app.ai_service.agent_runner import execute_agent
                
                async for event in execute_agent(
                    chat_model=chat_model,
                    user_id=user_id,
                    user_message=data.message,
                    system_prompt=system_prompt,
                    compressed_messages=compressed_messages,
                    db_session_factory=async_session_factory,
                    note_service=note_service,
                    review_service=review_service,
                    timeout=LLM_STREAM_TIMEOUT,
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
                plan_model = getattr(init_manager, 'plan_model', None)  # 获取用于制定计划的模型
                
                if plan_model is None:
                    # Plan 模型不可用，降级为 ReAct
                    logger.warning("Plan 模型不可用，复杂查询降级为 ReAct")
                    from app.ai_service.agent_runner import execute_agent
                    
                    async for event in execute_agent(
                        chat_model=chat_model,
                        user_id=user_id,
                        user_message=data.message,
                        system_prompt=system_prompt,
                        compressed_messages=compressed_messages,
                        db_session_factory=async_session_factory,
                        note_service=note_service,
                        review_service=review_service,
                        timeout=LLM_STREAM_TIMEOUT,
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
                        chat_model=chat_model,
                        plan_model=plan_model,
                        user_id=user_id,
                        user_message=data.message,
                        system_prompt=system_prompt,
                        compressed_messages=compressed_messages,
                        db_session_factory=async_session_factory,
                        note_service=note_service,
                        review_service=review_service,
                        timeout=LLM_STREAM_TIMEOUT * 2,
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
                                chat_model=chat_model,
                                user_id=user_id,
                                user_message=data.message,
                                system_prompt=system_prompt,
                                compressed_messages=compressed_messages,
                                db_session_factory=async_session_factory,
                                note_service=note_service,
                                review_service=review_service,
                                timeout=LLM_STREAM_TIMEOUT,
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
            if accumulated:
                asyncio.create_task(
                    chat_service.save_message_with_commit(
                        session_id, user_id, "assistant", accumulated
                    )
                )
            
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
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲  #TODO  这为什么要禁用Nginx缓冲
        }
    )


@router.post("/chat/rag", summary="RAG 查询")
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
    """删除指定会话及其所有消息"""
    async with async_session_factory() as db:
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
