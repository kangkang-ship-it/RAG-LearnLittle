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
import { useSessionStore } from '../stores/useSessionStore';
import EmptyState from '../components/common/EmptyState';
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
      // 如果删除的是当前活跃会话，清除 store 中的残留状态
      const { lastSessionId, clearCurrentSession } = useSessionStore.getState();
      if (lastSessionId === deleteId) {
        clearCurrentSession();
      }
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

      {/* 删除确认弹窗 */}
      {deleteId && (
        <div
          style={{
            position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            backgroundColor: 'rgba(0,0,0,0.4)', zIndex: 2147483647,
          }}
          onClick={() => setDeleteId(null)}
        >
          <div
            style={{
              width: '100%', maxWidth: '28rem', padding: '1.5rem',
              backgroundColor: 'var(--color-card)', borderRadius: '1rem',
              boxShadow: 'var(--shadow-dialog)', border: '1px solid var(--color-border)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: 'var(--color-text)', margin: 0 }}>确认删除</h3>
            <p style={{ marginTop: '0.5rem', fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>删除后不可恢复，对话记录将永久丢失。</p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1.5rem' }}>
              <button onClick={() => setDeleteId(null)}
                style={{ padding: '0.5rem 1rem', fontSize: '0.875rem', borderRadius: '0.75rem', border: '1px solid var(--color-border)', backgroundColor: 'var(--color-card)', color: 'var(--color-text-secondary)', cursor: 'pointer' }}>
                取消
              </button>
              <button onClick={handleDelete}
                style={{ padding: '0.5rem 1rem', fontSize: '0.875rem', borderRadius: '999px', border: 'none', backgroundColor: 'var(--color-danger)', color: '#fff', cursor: 'pointer' }}>
                删除
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
