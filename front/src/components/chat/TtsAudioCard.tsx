/**
 * TTS 语音卡片（tool_file 事件，外部 API 工具文档 §10 C3）
 * 播放/下载均走 axios client（自动注入 JWT + 401 自动 refresh），
 * 不能用原生 <audio src>/<a href>（不携带 Authorization header）
 *
 * 审查 ⑤：从 AIChat.tsx（1088 行巨型组件）拆出。
 */

import { useEffect, useState } from 'react';
import { Download } from 'lucide-react';
import client from '../../api/client';

interface Props {
  file: { download_url?: string; duration_estimate?: string };
}

export default function TtsAudioCard({ file }: Props) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const loadAudio = async () => {
    if (audioUrl || loading) return;
    setLoading(true);
    try {
      const res = await client.get(file.download_url ?? '', { responseType: 'blob' });
      setAudioUrl(URL.createObjectURL(res.data));
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      alert(status === 404 ? '音频已过期，请重新生成' : '音频加载失败，请重新生成');
    } finally {
      setLoading(false);
    }
  };
  // 卡片挂载后自动加载音频（生成完成即可播放）
  useEffect(() => {
    void loadAudio();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleDownload = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      const res = await client.get(file.download_url ?? '', { responseType: 'blob' });
      const blob = res.data;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = '语音朗读.mp3';
      document.body.appendChild(a);
      a.click();
      URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      alert(status === 404 ? '音频已过期，请重新生成' : `下载失败(${status ?? '未知错误'})`);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="mt-2 flex items-center gap-3 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-accent-bg)] px-3 py-2">
      <span className="text-lg" role="img" aria-label="语音">🔊</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-[var(--color-text)] truncate">
          已生成语音朗读{file.duration_estimate ? `（${file.duration_estimate}）` : ''}
        </p>
        {audioUrl ? (
          <audio controls src={audioUrl} className="w-full h-8 mt-1" />
        ) : (
          <p className="text-xs text-[var(--color-text-tertiary)]">{loading ? '音频加载中…' : '音频加载失败'}</p>
        )}
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
