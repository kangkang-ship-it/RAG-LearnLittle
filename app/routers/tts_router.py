"""
TTS 音频下载路由（外部 API 工具接入文档 §4.3/§5.2）

GET /api/v1/tts/{file_id} —— JWT 鉴权 + 归属校验 + FileResponse 下载。

安全要点（与 ppt_router 完全一致）：
- file_id 必须匹配 ^[0-9a-f]{32}$（防路径穿越）
- 按 {user_id} 目录隔离（越权/不存在 → 404）
- 不走公开静态目录（音频含笔记朗读内容，参照 PPT 的安全模型）
"""
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.utils.auth_utils import get_current_user_id

router = APIRouter()

# TTS 音频根目录（环境变量可覆盖，参照 PPT_FILE_ROOT 模式）
TTS_FILE_ROOT = os.getenv("TTS_FILE_ROOT", os.path.join("data", "tts"))

# file_id = uuid4().hex（32 位小写十六进制）
_FILE_ID_RE = re.compile(r"^[0-9a-f]{32}$")

TTS_MEDIA_TYPE = "audio/mpeg"


@router.get("/tts/{file_id}", summary="下载 TTS 生成的音频文件")
async def download_tts(
    file_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    下载 TTS 音频文件（JWT 鉴权 + 归属校验）

    Args:
        file_id: 生成文件 ID（uuid4().hex）
        user_id: 当前用户 ID（参数级 Depends，仅一次 JWT 解码，见 ppt_router §6.2）

    Returns:
        FileResponse（.mp3）
    """
    # ① file_id 格式校验，防路径穿越
    if not _FILE_ID_RE.match(file_id):
        raise HTTPException(status_code=400, detail="无效的文件 ID")

    # ② 归属校验：{user_id}/{file_id}.mp3 必须存在
    audio_path = Path(TTS_FILE_ROOT) / user_id / f"{file_id}.mp3"
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    # ③ FileResponse 下载
    return FileResponse(
        audio_path,
        filename=f"{file_id}.mp3",
        media_type=TTS_MEDIA_TYPE,
    )
