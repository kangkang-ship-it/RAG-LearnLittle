/**
 * 笔记编辑器页面
 *
 * 功能：
 * 1. 新建/编辑笔记（根据 URL 参数 id 判断）
 * 2. Markdown 分栏编辑 + 实时预览
 * 3. 标签输入、分类选择、置顶
 * 4. 保存/导出笔记
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ArrowLeft, Save, Download, Bold, Italic, Heading1, Heading2, Code, List, ListOrdered, Quote, Pencil, Columns, Eye } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { normalizeCategory } from '../constants/noteCategories';
import 'highlight.js/styles/github.css';
import { notesApi } from '../api/notes';
import TagInput from '../components/common/TagInput';
import LoadingSkeleton from '../components/common/LoadingSkeleton';
import type { Note } from '../types/api';

type EditorMode = 'edit' | 'split' | 'preview';

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
  const [editorMode, setEditorMode] = useState<EditorMode>('split');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  /** 检测内容是否为 HTML 格式 */
  const isHtml = (str: string) => /<[a-z][\s\S]*>/i.test(str);

  /** HTML 转 Markdown（简易转换，用于兼容旧数据） */
  const htmlToMarkdown = (html: string): string => {
    let md = html;
    md = md.replace(/<h1[^>]*>(.*?)<\/h1>/gi, '# $1\n');
    md = md.replace(/<h2[^>]*>(.*?)<\/h2>/gi, '## $1\n');
    md = md.replace(/<h3[^>]*>(.*?)<\/h3>/gi, '### $1\n');
    md = md.replace(/<(strong|b)[^>]*>(.*?)<\/\1>/gi, '**$2**');
    md = md.replace(/<(em|i)[^>]*>(.*?)<\/\1>/gi, '*$2*');
    md = md.replace(/<s[^>]*>(.*?)<\/s>/gi, '~~$1~~');
    md = md.replace(/<code[^>]*>(.*?)<\/code>/gi, '`$1`');
    md = md.replace(/<pre[^>]*><code[^>]*>([\s\S]*?)<\/code><\/pre>/gi, '```\n$1\n```\n');
    md = md.replace(/<blockquote[^>]*>([\s\S]*?)<\/blockquote>/gi, (_, inner) => {
      return inner.replace(/<[^>]*>/g, '').split('\n').map((l: string) => `> ${l}`).join('\n') + '\n';
    });
    md = md.replace(/<ul[^>]*>([\s\S]*?)<\/ul>/gi, (_, inner) => {
      return inner.replace(/<li[^>]*>([\s\S]*?)<\/li>/gi, '- $1\n').trim() + '\n';
    });
    md = md.replace(/<ol[^>]*>([\s\S]*?)<\/ol>/gi, (_, inner) => {
      let idx = 0;
      return inner.replace(/<li[^>]*>([\s\S]*?)<\/li>/gi, (_match: string, p1: string) => `${++idx}. ${p1}\n`).trim() + '\n';
    });
    md = md.replace(/<a[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/gi, '[$2]($1)');
    md = md.replace(/<img[^>]*src="([^"]*)"[^>]*alt="([^"]*)"[^>]*\/?>/gi, '![$2]($1)');
    md = md.replace(/<hr[^>]*\/?>/gi, '\n---\n');
    md = md.replace(/<p[^>]*>([\s\S]*?)<\/p>/gi, '$1\n\n');
    md = md.replace(/<br[^>]*\/?>/gi, '\n');
    md = md.replace(/<[^>]+>/g, '');
    md = md.replace(/&nbsp;/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
    md = md.replace(/\n{3,}/g, '\n\n');
    return md.trim();
  };

  /** 加载笔记详情 */
  useEffect(() => {
    if (!id) return;
    (async () => {
      try {
        const res = await notesApi.detail(id);
        const note: Note = res.data.data;
        setTitle(note.title);
        // 兼容旧数据：如果内容是 HTML，自动转换为 Markdown
        const raw = note.content || '';
        setContent(isHtml(raw) ? htmlToMarkdown(raw) : raw);
        setTags(note.tags || []);
        // 分类归一化：非标准分类（如历史脏数据）统一归为"其他"，编辑保存时顺带规范化数据
        setCategory(normalizeCategory(note.category) || '');
        setIsPinned(note.is_pinned);
      } catch {
        toast.error('加载笔记失败');
        navigate('/notes');
      } finally {
        setLoading(false);
      }
    })();
    // navigate 为 router 稳定引用
  }, [id, navigate]);

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

  /** 导出为 Markdown 文件 */
  const handleExport = () => {
    if (!title.trim()) {
      toast.error('标题不能为空');
      return;
    }
    const mdContent = `# ${title}\n\n${content}`;
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

  /** 向 textarea 插入/包裹选中文本 */
  const wrapSelection = useCallback((before: string, after: string = before) => {
    const ta = textareaRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const selected = content.substring(start, end);
    const replacement = `${before}${selected || '文本'}${after}`;
    const newContent = content.substring(0, start) + replacement + content.substring(end);
    setContent(newContent);
    requestAnimationFrame(() => {
      ta.focus();
      const cursorPos = start + before.length;
      ta.setSelectionRange(cursorPos, cursorPos + (selected || '文本').length);
    });
  }, [content]);

  /** 在行首插入前缀 */
  const prefixLine = useCallback((prefix: string) => {
    const ta = textareaRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    // 找到当前行的起始位置
    const lineStart = content.lastIndexOf('\n', start - 1) + 1;
    const newContent = content.substring(0, lineStart) + prefix + content.substring(lineStart);
    setContent(newContent);
    requestAnimationFrame(() => {
      ta.focus();
      ta.setSelectionRange(start + prefix.length, start + prefix.length);
    });
  }, [content]);

  /** 工具栏按钮配置 */
  const toolbarActions = [
    { icon: <Bold size={15} />, title: '加粗', action: () => wrapSelection('**') },
    { icon: <Italic size={15} />, title: '斜体', action: () => wrapSelection('*') },
    { type: 'divider' as const },
    { icon: <Heading1 size={15} />, title: '一级标题', action: () => prefixLine('# ') },
    { icon: <Heading2 size={15} />, title: '二级标题', action: () => prefixLine('## ') },
    { type: 'divider' as const },
    { icon: <Code size={15} />, title: '代码块', action: () => wrapSelection('\n```\n', '\n```\n') },
    { icon: <Quote size={15} />, title: '引用', action: () => prefixLine('> ') },
    { type: 'divider' as const },
    { icon: <List size={15} />, title: '无序列表', action: () => prefixLine('- ') },
    { icon: <ListOrdered size={15} />, title: '有序列表', action: () => prefixLine('1. ') },
  ];

  if (loading) return <LoadingSkeleton />;

  return (
    <div>
      {/* 顶部操作栏 */}
      <div className="flex items-center justify-between mb-6">
        <button
          onClick={() => navigate('/notes')}
          className="flex items-center gap-1 text-[var(--color-text-secondary)] hover:text-[var(--color-accent)] transition-colors"
        >
          <ArrowLeft size={18} />
          {t('common.back')}
        </button>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExport}
            className="flex items-center gap-2 px-4 py-2 rounded-xl border border-[var(--color-border)] text-[var(--color-accent)] text-sm hover:bg-[var(--color-accent-bg)] transition-all duration-200"
            title="导出为 Markdown 文件"
          >
            <Download size={16} />
            导出
          </button>
          <button
            onClick={handleSave}
            className="flex items-center gap-2 px-4 py-2 rounded-[999px] bg-[var(--color-accent)] text-[var(--color-on-accent)] text-sm hover:bg-[var(--color-accent-hover)] active:scale-[0.98] transition-all duration-200 shadow-[var(--shadow-accent-md)]"
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
      <div className="flex flex-wrap gap-4 mb-4 p-3 bg-[var(--color-card)]/80 rounded-xl border border-[var(--color-border)] shadow-[var(--shadow-card)]">
        <div className="flex-1 min-w-[200px]">
          <label className="block text-xs text-[var(--color-text-tertiary)] mb-1">{t('note.tags')}</label>
          <TagInput tags={tags} onChange={setTags} />
        </div>
        <div className="w-40">
          <label className="block text-xs text-[var(--color-text-tertiary)] mb-1">{t('note.category')}</label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full px-2 py-1 text-sm rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] text-[var(--color-text)] focus:outline-none focus:border-[var(--color-accent)] transition-all duration-200"
          >
            <option value="">未分类</option>
            <option value="工作">工作</option>
            <option value="学习">学习</option>
            <option value="生活">生活</option>
            <option value="技术">技术</option>
            <option value="其他">其他</option>
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

      {/* Markdown 分栏编辑器 */}
      <div className="border border-[var(--color-border)] rounded-xl bg-[var(--color-card)] overflow-hidden shadow-[var(--shadow-card)]">
        {/* 工具栏 */}
        <div className="flex flex-wrap items-center gap-0.5 px-2 py-1.5 border-b border-[var(--color-border)] bg-[var(--color-surface)]">
          {editorMode !== 'preview' && toolbarActions.map((item, i) =>
            'type' in item && item.type === 'divider' ? (
              <div key={i} className="w-px h-5 bg-[var(--color-border)] mx-1" />
            ) : (
              <button
                key={i}
                type="button"
                onClick={'action' in item ? item.action : undefined}
                title={'title' in item ? item.title : ''}
                className="p-1.5 rounded-lg text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-bg)] hover:text-[var(--color-accent)] transition-all duration-200"
              >
                {'icon' in item && item.icon}
              </button>
            )
          )}
          {/* 模式切换 + 标签 */}
          <div className="ml-auto flex items-center gap-1">
            <div className="flex items-center rounded-lg border border-[var(--color-border)] overflow-hidden">
              <button
                type="button"
                onClick={() => setEditorMode('edit')}
                title="纯编辑"
                className={`p-1.5 transition-all duration-200 ${
                  editorMode === 'edit'
                    ? 'bg-[var(--color-accent)] text-[var(--color-on-accent)]'
                    : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-bg)] hover:text-[var(--color-accent)]'
                }`}
              >
                <Pencil size={14} />
              </button>
              <button
                type="button"
                onClick={() => setEditorMode('split')}
                title="分栏模式"
                className={`p-1.5 transition-all duration-200 ${
                  editorMode === 'split'
                    ? 'bg-[#1677ff] text-white'
                    : 'text-[#5a6a8a] hover:bg-[#e8f0fe] hover:text-[#1677ff]'
                }`}
              >
                <Columns size={14} />
              </button>
              <button
                type="button"
                onClick={() => setEditorMode('preview')}
                title="纯预览"
                className={`p-1.5 transition-all duration-200 ${
                  editorMode === 'preview'
                    ? 'bg-[#1677ff] text-white'
                    : 'text-[#5a6a8a] hover:bg-[#e8f0fe] hover:text-[#1677ff]'
                }`}
              >
                <Eye size={14} />
              </button>
            </div>
            <span className="text-xs text-[var(--color-text-tertiary)] select-none ml-1">Markdown</span>
          </div>
        </div>

        {/* 内容区域 */}
        <div className="flex" style={{ height: 'calc(100vh - 380px)', minHeight: '400px' }}>
          {/* 左侧：Markdown 源码编辑 */}
          {editorMode !== 'preview' && (
            <div className={`flex flex-col transition-all duration-300 ${
              editorMode === 'edit' ? 'w-full' : 'w-1/2 border-r border-[var(--color-border)]'
            }`}>
              {editorMode === 'edit' && (
                <div className="px-3 py-1.5 text-xs text-[var(--color-text-tertiary)] border-b border-[var(--color-border)] bg-[var(--color-surface-alt)] select-none">
                  编辑
                </div>
              )}
              <textarea
                ref={textareaRef}
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder={t('note.content')}
                className="flex-1 w-full resize-none p-4 text-sm leading-relaxed text-[var(--color-text)] bg-transparent outline-none font-[var(--font-mono)]"
                spellCheck={false}
              />
            </div>
          )}

          {/* 右侧：实时渲染预览 */}
          {editorMode !== 'edit' && (
            <div className={`flex flex-col transition-all duration-300 ${
              editorMode === 'preview' ? 'w-full' : 'w-1/2'
            }`}>
              {editorMode === 'preview' && (
                <div className="px-3 py-1.5 text-xs text-[var(--color-text-tertiary)] border-b border-[var(--color-border)] bg-[var(--color-surface-alt)] select-none">
                  预览
                </div>
              )}
              <div className="flex-1 overflow-y-auto p-4">
                {content.trim() ? (
                  <div className="md-prose">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      rehypePlugins={[rehypeHighlight]}
                    >
                      {content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <p className="text-[var(--color-text-tertiary)] text-sm italic">预览区域</p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
