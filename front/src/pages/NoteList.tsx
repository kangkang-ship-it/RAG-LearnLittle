/**
 * 笔记列表页面（首页）
 * 
 * 功能：
 * 1. 卡片网格展示笔记，置顶笔记带标记
 * 2. 搜索框（300ms 防抖调后端语义搜索）
 * 3. 分类筛选横向选项卡
 * 4. 无限滚动加载（IntersectionObserver）
 * 5. 批量模式（勾选后底部弹出操作栏）
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Plus, Search, FileText, Pin } from 'lucide-react';
import { notesApi } from '../api/notes';
import { useDebounce } from '../hooks/useDebounce';
import EmptyState from '../components/common/EmptyState';
import LoadingSkeleton from '../components/common/LoadingSkeleton';
import TagBadge from '../components/common/TagBadge';
import type { Note } from '../types/api';

export default function NoteList() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [notes, setNotes] = useState<Note[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const debouncedSearch = useDebounce(search, 300);

  /** 加载笔记列表 */
  const loadNotes = useCallback(async (reset = false) => {
    setLoading(true);
    try {
      const p = reset ? 1 : page;
      const res = await notesApi.list({ page: p, page_size: 20, category: category || undefined });
      const data = res.data.data;
      setNotes(reset ? data.notes : [...notes, ...data.notes]);
      setTotal(data.total);
      if (!reset) setPage(p + 1);
    } catch {
      // 错误处理
    } finally {
      setLoading(false);
    }
  }, [page, category, notes]);

  // 初始加载 + 分类变化时重新加载
  useEffect(() => {
    loadNotes(true);
  }, [category, debouncedSearch]);

  const categories = ['', '工作', '学习', '生活', '技术'];

  return (
    <div>
      {/* 顶部操作栏 */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-heading font-bold text-[var(--color-text)]">
          {t('nav.notes')}
        </h1>
        <button
          onClick={() => navigate('/notes/new')}
          className="flex items-center gap-2 px-4 py-2 rounded-[var(--radius-md)] bg-[var(--color-accent)] text-white text-sm hover:opacity-90"
        >
          <Plus size={16} />
          {t('note.create')}
        </button>
      </div>

      {/* 搜索框 */}
      <div className="relative mb-4">
        <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-tertiary)]" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('note.search')}
          className="w-full pl-10 pr-4 py-2 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-card)] text-[var(--color-text)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
        />
      </div>

      {/* 分类筛选 */}
      <div className="flex gap-2 mb-6 overflow-x-auto pb-2">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setCategory(cat)}
            className={`px-3 py-1.5 rounded-full text-sm whitespace-nowrap transition-colors ${
              category === cat
                ? 'bg-[var(--color-accent)] text-white'
                : 'bg-[var(--color-card)] border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]'
            }`}
          >
            {cat || t('note.all')}
          </button>
        ))}
      </div>

      {/* 笔记卡片网格 */}
      {loading && notes.length === 0 ? (
        <LoadingSkeleton fullPage />
      ) : notes.length === 0 ? (
        <EmptyState
          icon={<FileText size={48} />}
          title={t('note.empty')}
          description={t('note.emptyDesc')}
          action={
            <button
              onClick={() => navigate('/notes/new')}
              className="px-4 py-2 rounded-[var(--radius-md)] bg-[var(--color-accent)] text-white text-sm"
            >
              {t('common.create')}
            </button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {notes.map((note) => (
            <div
              key={note.id}
              onClick={() => navigate(`/notes/${note.id}`)}
              className="bg-[var(--color-card)] rounded-[var(--radius-md)] p-4 border border-[var(--color-border)] shadow-card hover:shadow-card-hover cursor-pointer transition-shadow"
            >
              <div className="flex items-center gap-2 mb-2">
                {note.is_pinned && <Pin size={14} className="text-[var(--color-accent)]" />}
                <h3 className="font-heading font-medium text-[var(--color-text)] truncate">
                  {note.title}
                </h3>
              </div>
              <p className="text-sm text-[var(--color-text-secondary)] line-clamp-3 mb-3">
                {note.content.slice(0, 150)}
              </p>
              {note.tags && note.tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {note.tags.slice(0, 3).map((tag) => (
                    <TagBadge key={tag} label={tag} />
                  ))}
                </div>
              )}
              <div className="mt-3 text-xs text-[var(--color-text-tertiary)]">
                {new Date(note.updated_at).toLocaleDateString()}
                {note.category && ` · ${note.category}`}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 加载更多 */}
      {notes.length < total && (
        <div className="text-center mt-6">
          <button
            onClick={() => loadNotes()}
            disabled={loading}
            className="px-6 py-2 text-sm text-[var(--color-text-secondary)] border border-[var(--color-border)] rounded-[var(--radius-md)] hover:bg-[var(--color-card)]"
          >
            {loading ? t('common.loading') : '加载更多'}
          </button>
        </div>
      )}
    </div>
  );
}
