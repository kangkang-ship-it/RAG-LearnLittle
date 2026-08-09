/**
 * PPT 下载卡片（tool_file 事件，§7 下载实现）
 * 下载走 axios client（自动注入 JWT + 401 自动 refresh 重试，不能用 <a href>）
 *
 * 审查 ⑤：从 AIChat.tsx（1088 行巨型组件）拆出。
 */

import { useState } from 'react';
import { Download } from 'lucide-react';
import client from '../../api/client';

interface Props {
  file: { download_url?: string; title?: string; slide_count?: number };
}

export default function PptDownloadCard({ file }: Props) {
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      // 用 axios client 而非原生 fetch：
      // ① 请求拦截器自动注入 JWT；② 401 自动 refresh 并重试（access token
      // 30 分钟过期，原生 fetch 无此机制会导致过期后下载 401「缺少认证信息」）
      const res = await client.get(file.download_url ?? '', { responseType: 'blob' });
      const blob = res.data;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${file.title || '讲解PPT'}.pptx`;   // 文件名取自 tool_file 事件的 title
      document.body.appendChild(a);
      a.click();
      URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 404) {
        alert('文件已过期，请重新生成');
      } else if (status === 401) {
        alert('登录已过期，请重新登录');
      } else {
        alert(`下载失败(${status ?? '未知错误'})`);
      }
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="mt-2 flex items-center gap-3 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-accent-bg)] px-3 py-2">
      <span className="text-lg" role="img" aria-label="PPT">📄</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-[var(--color-text)] truncate">
          已生成讲解 PPT{file.slide_count ? `（${file.slide_count} 页）` : ''}
        </p>
        <p className="text-xs text-[var(--color-text-tertiary)] truncate">
          {file.title || '讲解PPT'}
        </p>
      </div>
      <button
        onClick={handleDownload}
        disabled={downloading}
        className="flex items-center gap-1 px-3 py-1.5 text-sm rounded-[var(--radius-md)] bg-[var(--color-accent)] text-[var(--color-on-accent)] hover:opacity-90 disabled:opacity-50 transition-opacity"
      >
        <Download size={14} />
        {downloading ? '下载中…' : '下载'}
      </button>
    </div>
  );
}
