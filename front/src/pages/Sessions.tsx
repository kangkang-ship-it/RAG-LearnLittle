/**
 * 对话历史页面
 * 
 * 展示所有聊天会话列表，支持搜索和删除。
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { MessageSquare, Trash2, RefreshCw } from 'lucide-react';
import { sessionsApi } from '../api/sessions';
import EmptyState from '../components/common/EmptyState';
import ConfirmDialog from '../components/common/ConfirmDialog';
import type { ChatSession } from '../types/api';

export default function Sessions() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  /** 加载会话列表 */
  const fetchSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await sessionsApi.list();
      const list = res.data?.data?.sessions ?? [];
      setSessions(list);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '加载失败';
      console.error('[Sessions] 加载会话列表失败:', err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  /** 删除会话 */
  const handleDelete = async () => {
    if (!deleteId) return;
    try {
      await sessionsApi.delete(deleteId);
      setSessions(sessions.filter((s) => s.id !== deleteId));
      toast.success('已删除');
    } catch {
      toast.error(t('common.error'));
    }
    setDeleteId(null);
  };

  return (
    <div>
      {/* 刷新按钮 */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-heading font-bold text-[var(--color-text)]">
          {t('nav.sessions')}
        </h1>
        <button
          onClick={fetchSessions}
          disabled={loading}
          className="p-2 rounded-[var(--radius-md)] text-[var(--color-text-secondary)] hover:bg-[var(--color-border)] hover:text-[var(--color-text)] transition-colors"
          title="刷新"
        >
          <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-[var(--radius-md)] bg-[var(--color-danger-bg)] text-[var(--color-danger)] text-sm">
          加载失败: {error}
          <button onClick={fetchSessions} className="ml-2 underline">重试</button>
        </div>
      )}

      {loading && sessions.length === 0 ? (
        <p className="text-center text-[var(--color-text-tertiary)]">{t('common.loading')}</p>
      ) : sessions.length === 0 ? (
        <EmptyState icon={<MessageSquare size={48} />} title="暂无对话记录" />
      ) : (
        <div className="space-y-2">
          {sessions.map((session) => (
            <div
              key={session.id}
              className="flex items-center justify-between p-4 bg-[var(--color-card)] rounded-[var(--radius-md)] border border-[var(--color-border)] hover:shadow-card cursor-pointer"
              onClick={() => navigate(`/chat/${session.id}`)}
            >
              <div>
                <h3 className="font-medium text-[var(--color-text)]">{session.title}</h3>
                <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
                  {new Date(session.updated_at).toLocaleString()}
                </p>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); setDeleteId(session.id); }}
                className="p-2 text-[var(--color-text-tertiary)] hover:text-[var(--color-danger)]"
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={!!deleteId}
        title="确认删除"
        description="删除后不可恢复，对话记录将永久丢失。"
        confirmLabel="删除"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeleteId(null)}
      />
    </div>
  );
}
