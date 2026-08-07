/**
 * PPT 模板库页面（设计方案 §6.5，v1.4）
 *
 * 功能：上传 / 列表 / 删除用户自己的 .pptx 模板。
 * 模板在 AI 对话中与笔记一起选中，用于生成讲解 PPT（v1 有限支持见 §5.6）。
 * v1 不做：模板预览/缩略图、模板编辑（上传后只能删除重传）。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Presentation, Upload, Trash2, FileUp, Loader2, X } from 'lucide-react';
import { pptTemplatesApi, type PptTemplateInfo } from '../api/pptTemplates';

/** 文件大小格式化 */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function PPTTemplates() {
  const [templates, setTemplates] = useState<PptTemplateInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadName, setUploadName] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    try {
      const res = await pptTemplatesApi.list();
      setTemplates(res.data?.data?.templates ?? []);
    } catch {
      setError('模板列表加载失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  /** 选择文件后立即上传（.pptx 校验 + 大小由后端完成，前端给提示） */
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pptx')) {
      setError('请选择 .pptx 格式的模板文件');
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setError('模板文件过大（上限 10MB）');
      return;
    }
    setError('');
    setUploading(true);
    setSuccess('');
    try {
      await pptTemplatesApi.upload(file, uploadName.trim());
      setSuccess(`模板「${uploadName.trim() || file.name}」上传成功`);
      setUploadName('');
      await loadTemplates();
    } catch (err) {
      setError((err as Error).message || '上传失败');
    } finally {
      setUploading(false);
    }
  };

  /** 删除模板（确认后执行） */
  const handleDelete = async (tmpl: PptTemplateInfo) => {
    if (!window.confirm(`确定删除模板「${tmpl.name}」吗？删除后不可恢复。`)) return;
    try {
      await pptTemplatesApi.remove(tmpl.id);
      setTemplates((prev) => prev.filter((x) => x.id !== tmpl.id));
      setSuccess(`模板「${tmpl.name}」已删除`);
    } catch {
      setError('删除失败，请稍后重试');
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <div className="flex items-center gap-2 mb-6">
        <Presentation size={22} className="text-[var(--color-accent)]" />
        <h1 className="text-2xl font-heading font-bold text-[var(--color-text)]">PPT 模板</h1>
      </div>

      {/* 提示 */}
      <p className="text-sm text-[var(--color-text-secondary)] mb-4 leading-relaxed">
        上传自己的 .pptx 模板后，在 AI 对话中与笔记一起选中，即可按模板生成讲解 PPT。
        模板中的幻灯片需命名为{' '}
        <code className="px-1 rounded bg-[var(--color-accent-bg)] text-[var(--color-accent)]">cover / agenda / section / content / summary</code>
        ，并在文本框中写{' '}
        <code className="px-1 rounded bg-[var(--color-accent-bg)] text-[var(--color-accent)]">{'{{title}} / {{bullets}}'}</code>{' '}
        等占位符（详见设计方案 §5.6）。
      </p>

      {/* 上传区 */}
      <div className="flex items-center gap-2 mb-6 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-card)] p-3">
        <input
          type="text"
          value={uploadName}
          onChange={(e) => setUploadName(e.target.value)}
          placeholder="模板名称（可选）"
          className="flex-1 min-w-0 px-3 py-2 text-sm rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-card)] text-[var(--color-text)] placeholder:text-[var(--color-text-tertiary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="flex items-center gap-1.5 px-4 py-2 text-sm rounded-[var(--radius-md)] bg-[var(--color-accent)] text-[var(--color-on-accent)] hover:opacity-90 disabled:opacity-50"
        >
          {uploading ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
          {uploading ? '上传中…' : '上传 .pptx'}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pptx"
          className="hidden"
          onChange={handleFileChange}
        />
      </div>

      {/* 状态提示 */}
      {error && (
        <div className="mb-4 flex items-center gap-2 text-sm text-[var(--color-danger)] bg-[var(--color-danger)]/10 rounded-[var(--radius-md)] px-3 py-2">
          <X size={14} /> {error}
          <button onClick={() => setError('')} className="ml-auto hover:opacity-70"><X size={12} /></button>
        </div>
      )}
      {success && (
        <div className="mb-4 text-sm text-[var(--color-accent)] bg-[var(--color-accent-bg)] rounded-[var(--radius-md)] px-3 py-2">
          {success}
        </div>
      )}

      {/* 模板列表 */}
      {loading ? (
        <div className="text-center py-10 text-sm text-[var(--color-text-tertiary)]">加载中...</div>
      ) : templates.length === 0 ? (
        <div className="text-center py-10">
          <FileUp size={32} className="mx-auto mb-2 text-[var(--color-text-tertiary)]" />
          <p className="text-sm text-[var(--color-text-tertiary)]">还没有 PPT 模板，上传一个开始吧</p>
        </div>
      ) : (
        <div className="space-y-2">
          {templates.map((tmpl) => (
            <div
              key={tmpl.id}
              className="flex items-center gap-3 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-card)] px-3 py-2.5"
            >
              <Presentation size={16} className="text-[var(--color-accent)] flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-[var(--color-text)] truncate">{tmpl.name}</p>
                <p className="text-xs text-[var(--color-text-tertiary)]">
                  {formatSize(tmpl.file_size)}
                  {tmpl.created_at ? ` · ${tmpl.created_at.slice(0, 10)}` : ''}
                </p>
              </div>
              <button
                onClick={() => handleDelete(tmpl)}
                className="flex items-center gap-1 px-2 py-1 text-xs rounded-[var(--radius-md)] text-[var(--color-text-secondary)] hover:bg-[var(--color-danger)]/10 hover:text-[var(--color-danger)]"
              >
                <Trash2 size={14} />
                删除
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
