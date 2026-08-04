/**
 * 消息气泡附件渲染
 *
 * 图片：缩略图网格（点击开灯箱大图）
 * 视频：内嵌播放器（<video> 自动带 Range 请求，支持拖动进度条）
 *
 * 鉴权：<img>/<video> 无法携带 Header，统一使用 ?token= 预览 URL（getAttachmentUrl）
 * 健壮性：加载失败（404/403/网络错误/token 过期/文件被清理）时显示占位，不显示破图
 */

import { useState } from 'react';
import { X, ImageOff, VideoOff } from 'lucide-react';
import type { AttachmentMeta } from '../../types/api';
import { getAttachmentUrl } from '../../api/chat';

interface AttachmentViewerProps {
  attachments: AttachmentMeta[];
}

/** 加载失败的图片占位 */
function ImagePlaceholder({ name }: { name: string }) {
  return (
    <div className="w-24 h-24 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-card)] flex flex-col items-center justify-center gap-1">
      <ImageOff size={20} className="text-[var(--color-text-tertiary)]" />
      <span className="text-[10px] text-[var(--color-text-tertiary)] px-1 truncate max-w-full">
        图片已失效
      </span>
      <span className="text-[10px] text-[var(--color-text-tertiary)] px-1 truncate max-w-full" title={name}>
        {name}
      </span>
    </div>
  );
}

/** 加载失败的视频占位 */
function VideoPlaceholder({ name }: { name: string }) {
  return (
    <div className="w-full max-w-sm h-24 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-card)] flex items-center justify-center gap-2">
      <VideoOff size={18} className="text-[var(--color-text-tertiary)]" />
      <span className="text-xs text-[var(--color-text-tertiary)]">
        视频加载失败（{name}）
      </span>
    </div>
  );
}

export default function AttachmentViewer({ attachments }: AttachmentViewerProps) {
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  // 加载失败的附件（file_id → 占位）
  const [failed, setFailed] = useState<Record<string, boolean>>({});

  const markFailed = (fileId: string) =>
    setFailed((prev) => (prev[fileId] ? prev : { ...prev, [fileId]: true }));

  const images = attachments.filter((a) => a.file_type === 'image');
  const videos = attachments.filter((a) => a.file_type === 'video');

  return (
    <div className="flex flex-wrap gap-2 mt-2">
      {/* 图片缩略图 */}
      {images.map((att) =>
        failed[att.file_id] ? (
          <ImagePlaceholder key={att.file_id} name={att.original_name} />
        ) : (
          <button
            key={att.file_id}
            onClick={() => setLightboxUrl(getAttachmentUrl(att.file_id))}
            className="w-24 h-24 rounded-[var(--radius-md)] overflow-hidden border border-[var(--color-border)] hover:opacity-90 transition-opacity"
            title={att.original_name}
          >
            <img
              src={getAttachmentUrl(att.file_id)}
              alt={att.original_name}
              className="w-full h-full object-cover"
              loading="lazy"
              onError={() => markFailed(att.file_id)}
            />
          </button>
        )
      )}

      {/* 视频播放器 */}
      {videos.map((att) =>
        failed[att.file_id] ? (
          <VideoPlaceholder key={att.file_id} name={att.original_name} />
        ) : (
          <div key={att.file_id} className="w-full max-w-sm">
            <video
              src={getAttachmentUrl(att.file_id)}
              controls
              preload="metadata"
              className="w-full rounded-[var(--radius-md)] border border-[var(--color-border)] bg-black"
              title={att.original_name}
              onError={() => markFailed(att.file_id)}
            />
            <p className="text-xs text-[var(--color-text-tertiary)] mt-1 truncate">
              ▶ {att.original_name}
            </p>
          </div>
        )
      )}

      {/* 灯箱 */}
      {lightboxUrl && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-6 cursor-zoom-out"
          onClick={() => setLightboxUrl(null)}
        >
          <button
            className="absolute top-4 right-4 w-9 h-9 rounded-full bg-white/10 text-white flex items-center justify-center hover:bg-white/20 transition-colors"
            onClick={() => setLightboxUrl(null)}
            title="关闭"
          >
            <X size={20} />
          </button>
          <img
            src={lightboxUrl}
            alt="大图预览"
            className="max-w-full max-h-full object-contain rounded-[var(--radius-md)]"
            onClick={(e) => e.stopPropagation()}
            onError={() => setLightboxUrl(null)}
          />
        </div>
      )}
    </div>
  );
}
