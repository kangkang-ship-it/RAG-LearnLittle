/**
 * 附件预览条（输入框上方）
 *
 * 展示待发送的附件：图片缩略图 / 视频卡片 + 上传进度 + 删除按钮。
 * 状态机：uploading（进度条）→ done（可发送）→ error（可删除重选）
 */

import { X, Play, Image as ImageIcon, Loader2 } from 'lucide-react';

/** 待发送附件（本地状态） */
export interface PendingAttachment {
  /** 本地唯一 ID（Date.now() + 序号） */
  localId: string;
  file: File;
  fileType: 'image' | 'video';
  name: string;
  /** 本地预览 URL（objectURL：图片缩略图 / 视频封面） */
  previewUrl: string;
  status: 'uploading' | 'done' | 'error';
  /** 上传进度 0-100 */
  progress: number;
  /** 上传成功后的 file_id */
  fileId?: string;
  width?: number;
  height?: number;
}

interface AttachmentBarProps {
  items: PendingAttachment[];
  onRemove: (localId: string) => void;
}

export default function AttachmentBar({ items, onRemove }: AttachmentBarProps) {
  if (items.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 mt-2">
      {items.map((att) => (
        <div
          key={att.localId}
          className={`relative w-20 rounded-[var(--radius-md)] border overflow-hidden bg-[var(--color-card)] ${
            att.status === 'error'
              ? 'border-[var(--color-danger)]'
              : 'border-[var(--color-border)]'
          }`}
        >
          {/* 缩略图 / 视频封面 */}
          <div className="relative w-20 h-20 bg-black/5 flex items-center justify-center overflow-hidden">
            {att.fileType === 'image' ? (
              <img
                src={att.previewUrl}
                alt={att.name}
                className="w-full h-full object-cover"
              />
            ) : (
              <>
                <video
                  src={att.previewUrl}
                  muted
                  preload="metadata"
                  className="w-full h-full object-cover"
                />
                <div className="absolute inset-0 flex items-center justify-center bg-black/30">
                  <Play size={20} className="text-white" />
                </div>
              </>
            )}

            {/* 上传进度遮罩 */}
            {att.status === 'uploading' && (
              <div className="absolute inset-0 bg-black/50 flex flex-col items-center justify-center gap-1">
                <Loader2 size={16} className="text-white animate-spin" />
                <span className="text-[10px] text-white">{att.progress}%</span>
              </div>
            )}

            {/* 上传失败标记 */}
            {att.status === 'error' && (
              <div className="absolute inset-0 bg-black/60 flex flex-col items-center justify-center gap-1">
                <ImageIcon size={16} className="text-[var(--color-danger)]" />
                <span className="text-[10px] text-white">失败</span>
              </div>
            )}
          </div>

          {/* 删除按钮 */}
          <button
            onClick={() => onRemove(att.localId)}
            className="absolute top-0.5 right-0.5 w-5 h-5 rounded-full bg-black/50 text-white flex items-center justify-center hover:bg-black/70 transition-colors"
            title="移除附件"
          >
            <X size={12} />
          </button>

          {/* 文件名 */}
          <div className="px-1 py-0.5">
            <p className="text-[10px] text-[var(--color-text-secondary)] truncate" title={att.name}>
              {att.name}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
