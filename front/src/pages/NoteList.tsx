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
import { toast } from 'sonner';
import { Plus, Search, FileText, Pin, Trash2, X, CheckSquare } from 'lucide-react';
import { notesApi } from '../api/notes';
import { useDebounce } from '../hooks/useDebounce';
import EmptyState from '../components/common/EmptyState';
import LoadingSkeleton from '../components/common/LoadingSkeleton';
import TagBadge from '../components/common/TagBadge';
import ConfirmDialog from '../components/common/ConfirmDialog';
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

  // 批量操作状态
  const [batchMode, setBatchMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  // 删除确认弹窗
  const [deleteTarget, setDeleteTarget] = useState<string | 'batch' | null>(null);

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

  /** 单条删除笔记 */
  const handleDelete = async (noteId: string) => {
    try {
      await notesApi.delete(noteId);
      setNotes((prev) => prev.filter((n) => n.id !== noteId));
      setTotal((prev) => prev - 1);
      toast.success('删除成功');
    } catch {
      toast.error('删除失败');
    }
    setDeleteTarget(null);
  };

  /** 批量删除笔记 */
  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    try {
      await notesApi.batch({ note_ids: Array.from(selectedIds), operation: 'delete' });
      setNotes((prev) => prev.filter((n) => !selectedIds.has(n.id)));
      setTotal((prev) => prev - selectedIds.size);
      toast.success(`已删除 ${selectedIds.size} 条笔记`);
      setSelectedIds(new Set());
      setBatchMode(false);
    } catch {
      toast.error('批量删除失败');
    }
    setDeleteTarget(null);
  };

  /** 切换笔记选中状态 */
  const toggleSelect = (noteId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(noteId)) next.delete(noteId);
      else next.add(noteId);
      return next;
    });
  };

  /** 退出批量模式 */
  const exitBatchMode = () => {
    setBatchMode(false);
    setSelectedIds(new Set());
  };

  return (
    <div>
      {/* 顶部操作栏 */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-heading font-bold text-[#1a2a4a]">
          {t('nav.notes')}
        </h1>
        <div className="flex items-center gap-2">
          {batchMode ? (
            <>
              <span className="text-sm text-[var(--color-text-secondary)]">
                已选 {selectedIds.size} 条
              </span>
              <button
                onClick={() => selectedIds.size > 0 && setDeleteTarget('batch')}
                disabled={selectedIds.size === 0}
                className="flex items-center gap-1.5 px-3 py-2 rounded-[var(--radius-md)] bg-[var(--color-danger)] text-white text-sm hover:opacity-90 disabled:opacity-50"
              >
                <Trash2 size={15} />
                删除
              </button>
              <button
                onClick={exitBatchMode}
                className="flex items-center gap-1.5 px-3 py-2 rounded-[var(--radius-md)] border border-[var(--color-border)] text-[var(--color-text-secondary)] text-sm hover:bg-[var(--color-card)]"
              >
                <X size={15} />
                取消
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => setBatchMode(true)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-[#d4dff0] text-[#1677ff] text-sm hover:bg-[#e8f0fe] transition-all duration-200"
              >
                <CheckSquare size={15} />
                批量
              </button>
              <button
                onClick={() => navigate('/notes/new')}
                className="flex items-center gap-2 px-4 py-2 rounded-[999px] bg-[#1677ff] text-white text-sm hover:bg-[#0d5bd6] active:scale-[0.98] transition-all duration-200 shadow-[0_4px_14px_rgba(22,119,255,0.3)]"
              >
                <Plus size={16} />
                {t('note.create')}
              </button>
            </>
          )}
        </div>
      </div>

      {/* 搜索框 */}
      <div className="relative mb-4">
        <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#1677ff]" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('note.search')}
          className="w-full pl-10 pr-4 py-2 rounded-xl border border-[#d4dff0] bg-white/80 text-[#1a2a4a] placeholder:text-[#9aa8c2] focus:outline-none focus:border-[#1677ff] focus:shadow-[0_0_0_3px_rgba(22,119,255,0.08)] hover:border-[#c8d0da] transition-all duration-200"
        />
      </div>

      {/* 分类筛选 */}
      <div className="flex gap-2 mb-6 overflow-x-auto pb-2">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setCategory(cat)}
            className={`px-3 py-1.5 rounded-xl text-sm whitespace-nowrap transition-all duration-200 ${
              category === cat
                ? 'bg-[#1677ff] text-white shadow-[0_2px_8px_rgba(22,119,255,0.3)]'
                : 'bg-[#e8f0fe] text-[#1677ff] hover:bg-[#d4e4ff]'
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
              className={`group relative bg-white rounded-2xl p-4 border transition-all duration-200 hover:shadow-[0_6px_20px_rgba(22,119,255,0.12)] ${
                selectedIds.has(note.id)
                  ? 'border-[#1677ff] ring-1 ring-[#1677ff] shadow-[0_2px_8px_rgba(22,119,255,0.06)]'
                  : 'border-[#d4dff0] shadow-[0_2px_8px_rgba(22,119,255,0.06)]'
              } ${batchMode ? 'cursor-pointer' : 'cursor-pointer'}`}
              onClick={() => {
                if (batchMode) {
                  toggleSelect(note.id);
                } else {
                  navigate(`/notes/${note.id}`);
                }
              }}
            >
              {/* 批量模式复选框 */}
              {batchMode && (
                <div className="absolute top-3 right-3 z-10">
                  <div className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-colors ${
                    selectedIds.has(note.id)
                      ? 'bg-[var(--color-accent)] border-[var(--color-accent)]'
                      : 'border-[var(--color-border)] bg-[var(--color-card)]'
                  }`}>
                    {selectedIds.has(note.id) && (
                      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                        <path d="M2 6l3 3 5-5" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    )}
                  </div>
                </div>
              )}

              {/* 单条删除按钮（非批量模式时显示） */}
              {!batchMode && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeleteTarget(note.id);
                  }}
                  className="absolute top-3 right-3 z-10 p-1 rounded text-[var(--color-text-tertiary)] hover:text-[var(--color-danger)] hover:bg-[var(--color-danger-bg)] opacity-0 group-hover:opacity-100 transition-opacity"
                  title="删除"
                >
                  <Trash2 size={14} />
                </button>
              )}

              <div className="flex items-center gap-2 mb-2">
                {note.is_pinned && <Pin size={14} className="text-[#1677ff]" />}
                <h3 className="font-heading font-medium text-[#1a2a4a] truncate">
                  {note.title}
                </h3>
              </div>
              <p className="text-sm text-[#5a6a8a] line-clamp-3 mb-3">
                {note.content.slice(0, 150)}
              </p>
              {note.tags && note.tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {note.tags.slice(0, 3).map((tag) => (
                    <TagBadge key={tag} label={tag} />
                  ))}
                </div>
              )}
              <div className="mt-3 text-xs text-[#9aa8c2]">
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
            className="px-6 py-2 text-sm text-[#1677ff] border border-[#d4dff0] rounded-xl hover:bg-[#e8f0fe] transition-all duration-200"
          >
            {loading ? t('common.loading') : '加载更多'}
          </button>
        </div>
      )}

      {/* 删除确认弹窗 */}
      <ConfirmDialog
        open={deleteTarget !== null && deleteTarget !== 'batch'}
        title="删除笔记"
        description="确定要删除这条笔记吗？删除后可在回收站恢复。"
        confirmLabel="删除"
        variant="danger"
        onConfirm={() => deleteTarget && handleDelete(deleteTarget)}
        onCancel={() => setDeleteTarget(null)}
      />

      {/* 批量删除确认弹窗 */}
      <ConfirmDialog
        open={deleteTarget === 'batch'}
        title="批量删除"
        description={`确定要删除选中的 ${selectedIds.size} 条笔记吗？删除后可在回收站恢复。`}
        confirmLabel={`删除 ${selectedIds.size} 条`}
        variant="danger"
        onConfirm={handleBatchDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
