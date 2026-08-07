"""
PPT 下载路由（设计方案 §6.2）

GET /api/v1/ppt/{file_id} —— JWT 鉴权 + 归属校验 + FileResponse 下载。

安全要点：
- file_id 必须匹配 ^[0-9a-f]{32}$（防路径穿越）
- 按 {user_id} 目录隔离 + sidecar 归属校验（越权/不存在 → 404）
- 不走公开静态目录（/static/avatars 是公开的，PPT 含用户笔记内容）
"""
import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.services.ppt_service import PPT_FILE_ROOT
from app.utils.auth_utils import get_current_user_id

router = APIRouter()

# file_id = uuid4().hex（32 位小写十六进制）
_FILE_ID_RE = re.compile(r"^[0-9a-f]{32}$")

PPT_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


@router.get("/ppt/{file_id}", summary="下载生成的 PPT 文件")
async def download_ppt(
    file_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    下载 PPT 文件（JWT 鉴权 + 归属校验）

    Args:
        file_id: 生成文件 ID（uuid4().hex）
        user_id: 当前用户 ID（参数级 Depends，仅一次 JWT 解码，见 §6.2）

    Returns:
        FileResponse（.pptx，文件名取自 sidecar 的 title）
    """
    # ① file_id 格式校验，防路径穿越
    if not _FILE_ID_RE.match(file_id):
        raise HTTPException(status_code=400, detail="无效的文件 ID")

    # ② 归属校验：{user_id}/{file_id}.json + .pptx 必须同时存在
    user_dir = Path(PPT_FILE_ROOT) / user_id
    sidecar = user_dir / f"{file_id}.json"
    pptx_path = user_dir / f"{file_id}.pptx"
    if not sidecar.exists() or not pptx_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    title = meta.get("title") or "讲解PPT"
    # ③ FileResponse 下载（文件名 sanitize：去除路径分隔符等危险字符）
    safe_title = re.sub(r"[\\/:*?\"<>|]", "_", title)[:80] or "讲解PPT"
    return FileResponse(
        pptx_path,
        filename=f"{safe_title}.pptx",
        media_type=PPT_MEDIA_TYPE,
    )
