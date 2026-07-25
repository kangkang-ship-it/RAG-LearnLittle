/**
 * 笔记编辑器页面
 * 
 * 功能：
 * 1. 新建/编辑笔记（根据 URL 参数 id 判断）
 * 2. Tiptap 富文本编辑器
 * 3. 标签输入、分类选择
 * 4. 保存笔记
 */

import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ArrowLeft, Save, Download } from 'lucide-react';
import { notesApi } from '../api/notes';
import TagInput from '../components/common/TagInput';
import TiptapEditor from '../components/common/TiptapEditor';
import LoadingSkeleton from '../components/common/LoadingSkeleton';
import type { Note } from '../types/api';

export default function NoteEditor() {
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(!!id);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [category, setCategory] = useState('');
  const [isPinned, setIsPinned] = useState(false);

  /** 加载笔记详情 */
  useEffect(() => {
    if (!id) return;
    (async () => {
      try {
        const res = await notesApi.detail(id);
        const note: Note = res.data.data;
        setTitle(note.title);
        setContent(note.content);
        setTags(note.tags || []);
        setCategory(note.category || '');
        setIsPinned(note.is_pinned);
      } catch {
        toast.error('加载笔记失败');
        navigate('/notes');
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  /** 保存笔记 */
  const handleSave = async () => {
    if (!title.trim() || !content.trim()) {
      toast.error('标题和内容不能为空');
      return;
    }

    try {
      if (id) {
        await notesApi.update(id, { title, content, tags, category, is_pinned: isPinned });
        toast.success('保存成功');
      } else {
        const res = await notesApi.create({ title, content, tags, category, is_pinned: isPinned });
        toast.success('创建成功');
        navigate(`/notes/${res.data.data.id}`, { replace: true });
      }
    } catch {
      toast.error(t('common.error'));
    }
  };

  /** HTML 转 Markdown（简易转换） */
  const htmlToMarkdown = (html: string): string => {
    let md = html;
    // 标题
    md = md.replace(/<h1[^>]*>(.*?)<\/h1>/gi, '# $1\n');
    md = md.replace(/<h2[^>]*>(.*?)<\/h2>/gi, '## $1\n');
    md = md.replace(/<h3[^>]*>(.*?)<\/h3>/gi, '### $1\n');
    // 粗体/斜体/删除线
    md = md.replace(/<(strong|b)[^>]*>(.*?)<\/\1>/gi, '**$2**');
    md = md.replace(/<(em|i)[^>]*>(.*?)<\/\1>/gi, '*$2*');
    md = md.replace(/<s[^>]*>(.*?)<\/s>/gi, '~~$1~~');
    // 行内代码
    md = md.replace(/<code[^>]*>(.*?)<\/code>/gi, '`$1`');
    // 代码块
    md = md.replace(/<pre[^>]*><code[^>]*>([\s\S]*?)<\/code><\/pre>/gi, '```\n$1\n```\n');
    // 引用
    md = md.replace(/<blockquote[^>]*>([\s\S]*?)<\/blockquote>/gi, (_, inner) => {
      return inner.replace(/<[^>]*>/g, '').split('\n').map((l: string) => `> ${l}`).join('\n') + '\n';
    });
    // 无序列表
    md = md.replace(/<ul[^>]*>([\s\S]*?)<\/ul>/gi, (_, inner) => {
      return inner.replace(/<li[^>]*>([\s\S]*?)<\/li>/gi, '- $1\n').trim() + '\n';
    });
    // 有序列表
    md = md.replace(/<ol[^>]*>([\s\S]*?)<\/ol>/gi, (_, inner) => {
      let idx = 0;
      return inner.replace(/<li[^>]*>([\s\S]*?)<\/li>/gi, () => `${++idx}. $1\n`).trim() + '\n';
    });
    // 链接
    md = md.replace(/<a[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/gi, '[$2]($1)');
    // 图片
    md = md.replace(/<img[^>]*src="([^"]*)"[^>]*alt="([^"]*)"[^>]*\/?>/gi, '![$2]($1)');
    // 分割线
    md = md.replace(/<hr[^>]*\/?>/gi, '\n---\n');
    // 段落和换行
    md = md.replace(/<p[^>]*>([\s\S]*?)<\/p>/gi, '$1\n\n');
    md = md.replace(/<br[^>]*\/?>/gi, '\n');
    // 清除剩余 HTML 标签
    md = md.replace(/<[^>]+>/g, '');
    // 解码 HTML 实体
    md = md.replace(/&nbsp;/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
    // 清理多余空行
    md = md.replace(/\n{3,}/g, '\n\n');
    return md.trim();
  };

  /** 导出为 Markdown 文件 */
  const handleExport = () => {
    if (!title.trim()) {
      toast.error('标题不能为空');
      return;
    }
    const mdContent = `# ${title}\n\n${htmlToMarkdown(content)}`;
    const blob = new Blob([mdContent], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${title.replace(/[\\/:*?"<>|]/g, '_')}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast.success('导出成功');
  };

  if (loading) return <LoadingSkeleton />;

  return (
    <div>
      {/* 顶部操作栏 */}
      <div className="flex items-center justify-between mb-6">
        <button
          onClick={() => navigate('/notes')}
          className="flex items-center gap-1 text-[var(--color-text-secondary)] hover:text-[var(--color-text)]"
        >
          <ArrowLeft size={18} />
          {t('common.back')}
        </button>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExport}
            className="flex items-center gap-2 px-4 py-2 rounded-[var(--radius-md)] border border-[var(--color-border)] text-[var(--color-text-secondary)] text-sm hover:bg-[var(--color-accent-bg)] hover:text-[var(--color-accent)] hover:border-[var(--color-accent)] transition-colors"
            title="导出为 Markdown 文件"
          >
            <Download size={16} />
            导出
          </button>
          <button
            onClick={handleSave}
            className="flex items-center gap-2 px-4 py-2 rounded-[var(--radius-md)] bg-[var(--color-accent)] text-white text-sm hover:opacity-90"
          >
            <Save size={16} />
            {t('note.save')}
          </button>
        </div>
      </div>

      {/* 标题输入 */}
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder={t('note.title')}
        className="w-full text-2xl font-heading font-bold bg-transparent border-none outline-none text-[var(--color-text)] mb-4"
      />

      {/* 标签和分类 */}
      <div className="flex flex-wrap gap-4 mb-4 p-3 bg-[var(--color-card)] rounded-[var(--radius-md)] border border-[var(--color-border)]">
        <div className="flex-1 min-w-[200px]">
          <label className="block text-xs text-[var(--color-text-tertiary)] mb-1">{t('note.tags')}</label>
          <TagInput tags={tags} onChange={setTags} />
        </div>
        <div className="w-40">
          <label className="block text-xs text-[var(--color-text-tertiary)] mb-1">{t('note.category')}</label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full px-2 py-1 text-sm rounded border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
          >
            <option value="">未分类</option>
            <option value="工作">工作</option>
            <option value="学习">学习</option>
            <option value="生活">生活</option>
            <option value="技术">技术</option>
          </select>
        </div>
        <div className="flex items-end">
          <label className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)] cursor-pointer">
            <input
              type="checkbox"
              checked={isPinned}
              onChange={(e) => setIsPinned(e.target.checked)}
              className="rounded"
            />
            {t('note.pinned')}
          </label>
        </div>
      </div>

      {/* Tiptap 富文本编辑器 */}
      <TiptapEditor
        content={content}
        onChange={setContent}
        placeholder={t('note.content')}
      />
    </div>
  );
}
