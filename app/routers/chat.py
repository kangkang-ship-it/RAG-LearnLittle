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
            await db.commit()
        
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
    
    # ===== RAG 检索：在生成回答前查询知识库 + 笔记库 =====
    rag_context = ""
    rag_sources = []
    
    try:
        # 等待 VectorStore 初始化完成（stage2）
        await asyncio.wait_for(init_manager.stage2_complete.wait(), timeout=5)
        
        from app.rag.vector_store import VectorStoreService
        from app.rag.rag_service import RagService
        
        vector_store = VectorStoreService()
        reranker = getattr(init_manager, 'reorder_service', None)
        rag_service = RagService(
            vector_store=vector_store,
            chat_model=chat_model,
            rerank_model=reranker,
        )
        
        # 执行 RAG 查询管线
        rag_result = await rag_service.query(
            query_text=data.message,  # 用户最新消息作为查询
            user_id=user_id,
            top_k=3,  # 默认返回 3 个相关文档
            use_hyde=False,  # 首次不启用 HyDE，减少延迟
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
    
    # 构建 system_prompt（注入 RAG 上下文）
    from datetime import datetime
    from app.utils.prompt_loader import load_prompt
    from app.utils.config import get_agent_config
    
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
        """生成 SSE 流式响应（带 RAG 上下文 + Token预算压缩 + 超时保护）"""
        try:
            # 发送思考事件
            if rag_context:
                yield f"data: {json.dumps({'type': 'thinking', 'stage': 'rag', 'content': f'已从知识库检索到 {len(rag_sources)} 个相关文档'})}\n\n"
            yield f"data: {json.dumps({'type': 'thinking', 'stage': 'processing', 'content': '正在思考...'})}\n\n"
            
            # ===== 对话记忆压缩管线 =====
            from langchain_core.messages import HumanMessage, AIMessage
            from app.services.token_budget import TokenBudget, TokenCounter
            from app.services.memory_compressor import MemoryCompressor, check_and_summarize
            from app.utils.config import get_token_budget_config, get_memory_compression_config
            
            compressed_messages = []
            try:
                # Step 1: 创建 Token 预算管理器
                tb_config = get_token_budget_config()
                budget = TokenBudget(
                    model_context_size=tb_config.get("model_context_size", 32768),
                    system_prompt=tb_config.get("system_prompt", 500),
                    rag_context_max=tb_config.get("rag_context_max", 2000),
                    summary_max=tb_config.get("summary_max", 800),
                    agent_scratchpad_reserve=tb_config.get("agent_scratchpad_reserve", 4000),
                    current_input_estimate=tb_config.get("current_input_estimate", 300),
                    safety_margin=tb_config.get("safety_margin", 1000),
                )
                
                # Step 2: 动态分配 token 配额（考虑 RAG 实际消耗）
                history_quota = budget.allocate(rag_context)
                
                # Step 3: 加载全量历史 + 已有摘要
                mc_config = get_memory_compression_config()
                
                async with async_session_factory() as db:
                    all_msgs = await session_manager.get_all_messages(db, session_id)
                    summary_obj = await session_manager.get_summary(db, session_id)
                
                all_messages = [
                    {"role": m.role, "content": m.content}
                    for m in all_msgs
                ]
                existing_summary = summary_obj.summary_text if summary_obj else ""
                
                # 排除当前消息（已保存为 DB 最后一条），仅将历史消息作为 chat_history
                # 当前消息通过 Agent 的 input 参数传入，避免重复
                prev_messages = all_messages[:-1] if all_messages else []
                
                # Step 4: 执行压缩（滑动窗口 + 摘要拼接）
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
                
                # Step 5: 异步触发里程碑摘要检查（非阻塞）
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
                # 回退：简单截断（保留最近 N 轮）
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
            
            # ===== 通过 Agent 生成回答（新 API：messages 格式）=====
            from app.agent.agent import AgentFactory
            from app.agent.agent_tools import create_agent_tools
            
            agent_config = get_agent_config()
            tools = create_agent_tools(
                user_id=user_id,
                db_session_factory=async_session_factory,
            )
            agent, max_iter = AgentFactory.create_agent(
                chat_model=chat_model,
                tools=tools,
                system_prompt=system_prompt,
                max_iterations=agent_config.get("max_iterations", 5),
            )
            
            # 构建 Agent 输入：compressed_messages + 当前消息（新 API 使用 messages 列表）
            agent_input = {
                "messages": [*compressed_messages, HumanMessage(content=data.message)]
            }
            
            accumulated = ""
            try:
                async with asyncio.timeout(LLM_STREAM_TIMEOUT):
                    async for event in agent.astream_events(
                        agent_input,
                        config={"recursion_limit": max_iter},
                        version="v2",
                    ):
                        # astream_events 逐 token 输出 LLM 流式事件
                        if event["event"] == "on_chat_model_stream":
                            chunk = event["data"].get("chunk")
                            if chunk and hasattr(chunk, "content") and chunk.content:
                                accumulated += chunk.content
                                yield f"data: {json.dumps({'type': 'response', 'content': chunk.content})}\n\n"
            except asyncio.TimeoutError:
                logger.warning(f"Agent 响应超时: session_id={session_id}")
                yield f"data: {json.dumps({'type': 'error', 'content': f'AI 响应超时（{LLM_STREAM_TIMEOUT}秒），请重试'})}\n\n"
                return
            
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
        
        vector_store = VectorStoreService()
        chat_model = init_manager.chat_model
        reranker = getattr(init_manager, 'reorder_service', None)
        
        rag_service = RagService(
            vector_store=vector_store,
            chat_model=chat_model,
            rerank_model=reranker,
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
