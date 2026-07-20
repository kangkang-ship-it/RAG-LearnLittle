"""
知识库路由

端点：
- POST /knowledge/upload - 上传知识库文档（SSE 流式进度推送）
- GET /knowledge/documents - 文档列表
- GET /knowledge/documents/{doc_id} - 文档详情
- DELETE /knowledge/documents/{doc_id} - 删除文档

上传接口使用 SSE（Server-Sent Events）实时推送文档处理进度，
事件格式：
- {event_type: "processing", filename, progress, stage}
- {event_type: "completed", filename, progress, document_id}
- {event_type: "finish"}
- {event_type: "error", message}
"""

import asyncio
import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger_handler import logger
from app.core.success_response import success_response
from app.core.failed_response import BusinessError, ErrorCode
from app.core.rate_limit import rate_limit
from app.db.database import get_db
from app.models.knowledge import KnowledgeDocument
from app.schemas.knowledge import KnowledgeDocumentResponse, KnowledgeDocumentListResponse
from app.utils.auth_utils import get_current_user_id
from app.utils.file_handler import validate_upload_file, calculate_md5_bytes, get_safe_filename, ensure_dir

router = APIRouter()

# 上传目录
UPLOAD_DIR = "data/uploads"


def _make_sse_event(data: dict) -> str:
    """
    构造一条 SSE 事件消息

    格式为 "data: {json}\n\n"，前端通过 ReadableStream 逐行解析。

    Args:
        data: 要推送的事件数据字典

    Returns:
        SSE 格式字符串
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _process_document_with_progress(
    content: bytes,
    filename: str,
    file_size: int,
    file_type: str,
    md5: str,
    user_id: str,
):
    """
    文档处理管线（带 SSE 进度推送）

    分四个阶段处理上传的文档，每个阶段通过 yield 推送 SSE 事件：
    1. 文件保存（0~20%）
    2. 文档解析（20~50%）
    3. 文本切片（50~75%）
    4. 向量化入库（75~100%）

    Args:
        content: 文件原始字节内容
        filename: 安全文件名
        file_size: 文件大小
        file_type: MIME 类型
        md5: 文件 MD5
        user_id: 用户 ID

    Yields:
        SSE 事件字符串
    """
    safe_name = get_safe_filename(filename)
    file_id = str(uuid.uuid4())[:8]
    stored_name = f"{file_id}_{safe_name}"

    # ===== 阶段 1: 保存文件（0% → 20%） =====
    yield _make_sse_event({
        "event_type": "processing",
        "filename": safe_name,
        "progress": 0,
        "stage": "saving",
        "message": "正在保存文件...",
    })

    upload_path = Path(UPLOAD_DIR) / user_id
    ensure_dir(str(upload_path))
    file_path = upload_path / stored_name

    with open(file_path, "wb") as f:
        f.write(content)

    await asyncio.sleep(0.1)  # 让前端能看到进度变化

    yield _make_sse_event({
        "event_type": "processing",
        "filename": safe_name,
        "progress": 20,
        "stage": "saved",
        "message": "文件保存完成",
    })

    # ===== 阶段 2: 文档解析（20% → 50%） =====
    yield _make_sse_event({
        "event_type": "processing",
        "filename": safe_name,
        "progress": 30,
        "stage": "parsing",
        "message": "正在解析文档内容...",
    })

    # 提取文本内容（支持 TXT / Markdown / PDF）
    text_content = ""
    try:
        if file_type in ("text/plain", "text/markdown") or safe_name.endswith((".txt", ".md")):
            text_content = content.decode("utf-8", errors="replace")
        elif safe_name.endswith(".pdf"):
            # PDF 文本提取（使用 PyMuPDF）
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(stream=content, filetype="pdf")
                text_parts = []
                for page in doc:
                    page_text = page.get_text()
                    if page_text:
                        text_parts.append(page_text)
                doc.close()
                text_content = "\n\n".join(text_parts)
                logger.info(f"PDF 解析成功: {len(text_parts)} 页, 提取 {len(text_content)} 字符")
            except ImportError:
                logger.warning("PyMuPDF 未安装，PDF 解析降级为纯文本提取")
                text_content = content.decode("utf-8", errors="replace")
            except Exception as pdf_err:
                logger.warning(f"PDF 解析失败: {pdf_err}，降级为纯文本提取")
                text_content = content.decode("utf-8", errors="replace")
        else:
            text_content = content.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"文档解析失败，使用原始内容: {e}")
        text_content = content.decode("utf-8", errors="replace")

    await asyncio.sleep(0.3)

    yield _make_sse_event({
        "event_type": "processing",
        "filename": safe_name,
        "progress": 50,
        "stage": "parsed",
        "message": "文档解析完成",
    })

    # ===== 阶段 3: 文本切片（50% → 75%） =====
    yield _make_sse_event({
        "event_type": "processing",
        "filename": safe_name,
        "progress": 60,
        "stage": "splitting",
        "message": "正在文本切片...",
    })

    # 调用 TextSplitter 进行切片
    chunks = []
    if text_content.strip():
        from app.rag.text_spliter import TextSplitter
        splitter = TextSplitter()
        chunks = await splitter.async_split_text(text_content)
    chunk_count = len(chunks)

    yield _make_sse_event({
        "event_type": "processing",
        "filename": safe_name,
        "progress": 75,
        "stage": "splitted",
        "message": f"文本切片完成，共 {chunk_count} 个片段",
    })

    # ===== 阶段 4: 向量化入库（75% → 100%） =====
    yield _make_sse_event({
        "event_type": "processing",
        "filename": safe_name,
        "progress": 85,
        "stage": "vectorizing",
        "message": "正在向量化...",
    })

    # 写入数据库（使用独立的 session，因为请求 session 在 SSE 流式响应时已关闭）
    from app.db.database import async_session_factory
    async with async_session_factory() as new_db:
        doc = KnowledgeDocument(
            user_id=user_id,
            filename=safe_name,
            file_path=str(file_path),
            file_size=file_size,
            file_type=file_type,
            md5_hash=md5,
            chunk_count=chunk_count,
        )
        new_db.add(doc)
        await new_db.commit()
        await new_db.refresh(doc)

        # 调用 VectorStore 写入 ChromaDB
        if chunks:
            try:
                from app.rag.vector_store import VectorStoreService
                vector_store = VectorStoreService()
                
                chunk_ids = [f"{doc.id}_{i}" for i in range(chunk_count)]
                metadatas = [
                    {
                        "user_id": user_id,
                        "document_id": str(doc.id),
                        "filename": safe_name,
                        "chunk_index": i,
                    }
                    for i in range(chunk_count)
                ]
                
                await vector_store.upsert_document(
                    documents=chunks,
                    metadatas=metadatas,
                    ids=chunk_ids,
                    collection="rag",
                )
                logger.info(f"向量写入成功: doc_id={doc.id}, chunks={chunk_count}")
            except Exception as ve:
                logger.error(f"向量写入失败: doc_id={doc.id}, error={ve}")

    yield _make_sse_event({
        "event_type": "processing",
        "filename": safe_name,
        "progress": 100,
        "stage": "vectorized",
        "message": "向量化入库完成",
    })

    # ===== 完成事件 =====
    yield _make_sse_event({
        "event_type": "completed",
        "filename": safe_name,
        "progress": 100,
        "document_id": doc.id,
        "message": "文档处理完成",
    })

    logger.info(f"知识库文档处理完成: doc_id={doc.id}, filename={safe_name}, chunks={chunk_count}")


@router.post("/knowledge/upload", summary="上传知识库文档（SSE 进度推送）", dependencies=[Depends(rate_limit(endpoint_limit=20))])
async def upload_document(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    上传知识库文档（SSE 流式进度推送）

    支持 PDF / Markdown / TXT，单文件上限 50MB。
    自动 MD5 查重，已存在则跳过。
    处理过程通过 SSE 实时推送进度事件。
    """
    max_size = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))

    # 读取文件内容
    content = await file.read()
    file_size = len(content)

    # 校验文件
    ext = validate_upload_file(file.filename, file_size, max_size)

    # 计算 MD5
    md5 = calculate_md5_bytes(content)

    # MD5 查重
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.md5_hash == md5,
            KnowledgeDocument.user_id == user_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        # 文档已存在，直接返回完成事件
        async def skip_generator():
            yield _make_sse_event({
                "event_type": "completed",
                "filename": get_safe_filename(file.filename),
                "progress": 100,
                "document_id": existing.id,
                "message": "文档已存在，已跳过上传",
            })
            yield _make_sse_event({"event_type": "finish"})

        return StreamingResponse(
            skip_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # 创建 SSE 流式响应
    async def event_generator():
        """SSE 事件生成器，包装文档处理管线"""
        try:
            async for event in _process_document_with_progress(
                content=content,
                filename=file.filename,
                file_size=file_size,
                file_type=file.content_type or "application/octet-stream",
                md5=md5,
                user_id=user_id,
            ):
                yield event

            # 发送结束标记
            yield _make_sse_event({"event_type": "finish"})

        except Exception as e:
            logger.error(f"文档处理失败: {e}")
            yield _make_sse_event({
                "event_type": "error",
                "message": f"文档处理失败: {str(e)}",
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/knowledge/documents", summary="文档列表")
async def list_documents(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的知识库文档列表"""
    result = await db.execute(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.user_id == user_id)
        .order_by(KnowledgeDocument.created_at.desc())
    )
    docs = list(result.scalars().all())
    
    return success_response(data=KnowledgeDocumentListResponse(
        documents=[KnowledgeDocumentResponse.model_validate(d).model_dump() for d in docs],
        total=len(docs),
    ).model_dump())


@router.get("/knowledge/documents/{doc_id}", summary="文档详情")
async def get_document(
    doc_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取文档详细信息"""
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == doc_id,
            KnowledgeDocument.user_id == user_id,
        )
    )
    doc = result.scalar_one_or_none()
    
    if not doc:
        raise BusinessError(code=ErrorCode.DOCUMENT_NOT_FOUND, http_status=404)
    
    return success_response(data=KnowledgeDocumentResponse.model_validate(doc).model_dump())


@router.delete("/knowledge/documents/{doc_id}", summary="删除文档")
async def delete_document(
    doc_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """删除文档（同时删除 ChromaDB 向量和本地文件）"""
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == doc_id,
            KnowledgeDocument.user_id == user_id,
        )
    )
    doc = result.scalar_one_or_none()
    
    if not doc:
        raise BusinessError(code=ErrorCode.DOCUMENT_NOT_FOUND, http_status=404)
    
    # 删除本地文件
    try:
        Path(doc.file_path).unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"删除文件失败: {e}")
    
    # 删除 ChromaDB 向量
    try:
        from app.rag.vector_store import VectorStoreService
        vector_store = VectorStoreService()
        await vector_store.delete_document_vectors(str(doc.id))
    except Exception as e:
        logger.warning(f"删除 ChromaDB 向量失败: {e}")
    
    await db.delete(doc)
    await db.flush()
    
    return success_response(message="文档已删除")
