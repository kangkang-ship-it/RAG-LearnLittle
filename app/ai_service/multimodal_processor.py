"""
多模态附件处理器

把聊天附件（图片/视频）转换成送模型的 OpenAI 兼容 content blocks：
- 图片：Pillow 压缩（缩放长边 + JPEG 质量控制）→ base64 内联
- 视频：imageio-ffmpeg 抽帧（默认方案，兼容所有视觉模型）→ 每帧压缩为 JPEG → base64 内联

设计要点：
- 所有 CPU 密集操作（Pillow 压缩 / ffmpeg 抽帧）由调用方通过 asyncio.to_thread 执行
- 压缩结果按 file_id 内存缓存（后续追问复用，避免重复压缩）；内存缓存不占磁盘配额，
  与设计文档"缩略图落盘缓存计入配额"的差异：v1 用进程内缓存（上限 200 条），
  附件删除时缓存条目由 LRU 自然淘汰
- 视频默认抽帧；视频原生输入（video_url）由模型支持情况决定，v1 统一走抽帧
"""

import asyncio
import io
import os
import re
import shutil
import subprocess
import tempfile
from typing import List, Optional, Tuple

from app.core.logger_handler import logger
from app.models.chat import ChatAttachment

# 压缩后图片的缓存（file_id → base64 JPEG 数据）
_processed_cache: dict = {}
_CACHE_MAX_ENTRIES = 200


def _cache_get(key: str) -> Optional[str]:
    return _processed_cache.get(key)


def _cache_put(key: str, value: str) -> None:
    if len(_processed_cache) >= _CACHE_MAX_ENTRIES:
        # 简单 LRU：清掉最早的 1/4
        for k in list(_processed_cache.keys())[: _CACHE_MAX_ENTRIES // 4]:
            _processed_cache.pop(k, None)
    _processed_cache[key] = value


# ============================================================
# 图片处理
# ============================================================

def compress_image_to_jpeg(content: bytes) -> bytes:
    """
    图片压缩为 JPEG（送模型前处理）

    规则（设计 §6.2）：
    1. 格式归一：png/jpg/webp 保留原格式读取；gif 取首帧转 jpg；HEIC 等不支持直接抛错
    2. 尺寸上限：长边 > CHAT_IMAGE_MAX_LONG_EDGE（默认 1568px）按比例缩放
    3. 压缩：JPEG 质量 CHAT_IMAGE_QUALITY（默认 85），目标 ≤ 1.5MB（超出继续降质）

    Args:
        content: 原始图片字节

    Returns:
        压缩后的 JPEG 字节

    Raises:
        ValueError: 图片无法解析
    """
    from PIL import Image

    max_long_edge = int(os.getenv("CHAT_IMAGE_MAX_LONG_EDGE", "1568"))
    quality = int(os.getenv("CHAT_IMAGE_QUALITY", "85"))

    try:
        with Image.open(io.BytesIO(content)) as img:
            # 修正 EXIF 方向（手机照片可能旋转）
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            # 统一转 RGB（RGBA/P/CMYK → RGB，避免 JPEG 不支持的模式）
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.split()[-1])
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # 长边缩放
            long_edge = max(img.width, img.height)
            if long_edge > max_long_edge:
                ratio = max_long_edge / long_edge
                new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
                img = img.resize(new_size, Image.LANCZOS)

            # 压缩：质量 85 起步，超出 1.5MB 目标则逐级降质
            target = 1.5 * 1024 * 1024
            for q in (quality, 70, 50):
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=q, optimize=True)
                data = buf.getvalue()
                if len(data) <= target or q == 50:
                    return data
    except Exception as e:
        raise ValueError(f"图片解析失败: {e}")

    raise ValueError("图片压缩失败")


def process_image_to_base64(file_path: str, cache_key: str) -> str:
    """
    读取图片文件 → 压缩 → base64（带进程内缓存）

    Args:
        file_path: 图片文件路径
        cache_key: 缓存键（建议用 file_id）

    Returns:
        data URI 兼容的 base64 JPEG 数据（不含 data: 前缀）
    """
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    import base64
    with open(file_path, "rb") as f:
        raw = f.read()

    try:
        jpeg = compress_image_to_jpeg(raw)
    except ValueError as e:
        logger.warning(f"图片压缩失败（{file_path}），改用原图: {e}")
        jpeg = raw

    b64 = base64.b64encode(jpeg).decode("ascii")
    _cache_put(cache_key, b64)
    return b64


# ============================================================
# 视频抽帧（imageio-ffmpeg）
# ============================================================

def _get_ffmpeg_exe() -> str:
    """
    获取 ffmpeg 可执行文件路径（imageio-ffmpeg 捆绑二进制）

    Returns:
        ffmpeg 路径

    Raises:
        RuntimeError: ffmpeg 不可用
    """
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise RuntimeError(f"imageio-ffmpeg 不可用，无法抽帧: {e}")


def _get_video_duration(ffmpeg: str, video_path: str) -> Optional[float]:
    """
    解析视频时长（秒，从 ffmpeg -i 的 stderr 输出）

    Args:
        ffmpeg: ffmpeg 可执行文件路径
        video_path: 视频文件路径

    Returns:
        时长秒数，解析失败返回 None
    """
    try:
        result = subprocess.run(
            [ffmpeg, "-i", video_path],
            capture_output=True, text=True, timeout=30,
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception as e:
        logger.warning(f"视频时长解析失败: {e}")
    return None


def extract_video_frames(
    video_path: str, frame_count: Optional[int] = None
) -> List[bytes]:
    """
    视频抽帧（均匀采样，默认 8 帧）

    用 ffmpeg fps 滤镜均匀抽取 N 帧（含首帧），每帧输出为 JPEG。
    短视频帧数不足时返回实际帧数（≥1）。

    Args:
        video_path: 视频文件路径
        frame_count: 抽帧数量（默认取 CHAT_VIDEO_FRAME_COUNT 环境变量，默认 8）

    Returns:
        JPEG 帧字节列表（按时间正序）

    Raises:
        RuntimeError: ffmpeg 不可用或抽帧失败
    """
    ffmpeg = _get_ffmpeg_exe()
    count = frame_count or int(os.getenv("VIDEO_FRAME_COUNT", "8"))

    tmpdir = tempfile.mkdtemp(prefix="chat_frames_")
    try:
        out_pattern = os.path.join(tmpdir, "frame_%02d.jpg")

        # 抽帧间隔（秒）：总时长 / 目标帧数，至少 0.01s 避免除零
        duration = _get_video_duration(ffmpeg, video_path)
        interval = max(duration / count if duration and duration > 0 else 1.0, 0.01)

        cmd = [
            ffmpeg, "-y", "-i", video_path,
            "-vf", f"fps={1 / interval:.6f}",
            "-frames:v", str(count),
            "-q:v", "3",           # JPEG 质量（2-5 区间，3 为高质量）
            out_pattern,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 抽帧失败: {result.stderr[-300:]}")

        frame_files = sorted(
            os.path.join(tmpdir, f) for f in os.listdir(tmpdir)
            if f.startswith("frame_") and f.endswith(".jpg")
        )
        if not frame_files:
            raise RuntimeError("ffmpeg 抽帧无输出（视频可能损坏或无法解码）")

        frames = []
        for f in frame_files[:count]:
            with open(f, "rb") as fh:
                frames.append(fh.read())

        logger.info(f"视频抽帧完成: {video_path}, frames={len(frames)}/{count}")
        return frames
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffmpeg 抽帧超时（120s）")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def process_video_frames_to_base64(file_path: str, cache_key: str) -> List[str]:
    """
    视频抽帧 → 压缩 → base64（带进程内缓存）

    Args:
        file_path: 视频文件路径
        cache_key: 缓存键（建议用 file_id）

    Returns:
        base64 JPEG 帧数据列表（不含 data: 前缀）
    """
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    frames = extract_video_frames(file_path)
    import base64
    b64_frames = []
    for frame in frames:
        try:
            jpeg = compress_image_to_jpeg(frame)
        except ValueError:
            jpeg = frame
        b64_frames.append(base64.b64encode(jpeg).decode("ascii"))

    _cache_put(cache_key, b64_frames)
    return b64_frames


# ============================================================
# content blocks 组装
# ============================================================

def build_attachment_blocks(
    attachments: List[ChatAttachment],
    video_mode: str = "frames",
) -> List[dict]:
    """
    把附件组装为 OpenAI 兼容 content blocks（不含 text 块，text 由调用方前置）

    图片 → {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
    视频 → 抽帧后每帧一个 image_url 块（默认模式；原生 video_url v1 不启用）

    Args:
        attachments: 附件列表（已校验归属）
        video_mode: 视频模式（frames=抽帧；native 保留接口位，v1 统一 frames）

    Returns:
        content blocks 列表

    Raises:
        RuntimeError: 视频抽帧失败（视觉模型不可用）
    """
    blocks: List[dict] = []
    for att in attachments:
        abs_path = os.path.join(os.getcwd(), att.stored_path)
        if att.file_type == "image":
            try:
                b64 = process_image_to_base64(abs_path, att.file_id)
                blocks.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                })
            except Exception as e:
                logger.warning(f"图片处理失败，跳过: file_id={att.file_id[:8]}, err={e}")
        elif att.file_type == "video":
            try:
                frames = process_video_frames_to_base64(abs_path, att.file_id)
                for fr in frames:
                    blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{fr}"},
                    })
            except Exception as e:
                logger.warning(f"视频抽帧失败，跳过: file_id={att.file_id[:8]}, err={e}")
    return blocks


def build_multimodal_content(
    user_message: str, blocks: List[dict]
) -> List[dict]:
    """
    组装完整的多模态 content（text 块 + 附件块）

    Args:
        user_message: 用户文本消息
        blocks: 附件 content blocks

    Returns:
        完整 content 列表
    """
    content: List[dict] = [{"type": "text", "text": user_message or "请分析我发送的附件"}]
    content.extend(blocks)
    return content


async def build_attachment_blocks_async(
    attachments: List[ChatAttachment], video_mode: str = "frames"
) -> List[dict]:
    """
    build_attachment_blocks 的异步包装（CPU 密集操作放入线程池，不阻塞事件循环）

    Args:
        attachments: 附件列表
        video_mode: 视频模式

    Returns:
        content blocks 列表
    """
    return await asyncio.to_thread(build_attachment_blocks, attachments, video_mode)
