/**
 * Tiptap 富文本编辑器组件
 * 
 * 基于 Tiptap（ProseMirror）实现的富文本编辑器，支持：
 * - 加粗、斜体、删除线、行内代码
 * - 标题（H1-H3）
 * - 无序列表、有序列表
 * - 引用块、代码块
 * - 分割线
 * - 撤销 / 重做
 * 
 * 工具栏按钮使用 lucide-react 图标，样式与主题变量一致。
 */

import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Placeholder from '@tiptap/extension-placeholder';
import {
  Bold, Italic, Strikethrough, Code,
  Heading1, Heading2, Heading3,
  List, ListOrdered,
  Quote, FileCode,
  Minus, Undo, Redo,
} from 'lucide-react';
import type { Editor } from '@tiptap/react';

interface TiptapEditorProps {
  /** 编辑器内容（HTML 格式） */
  content: string;
  /** 内容变更回调 */
  onChange: (html: string) => void;
  /** 占位提示文字 */
  placeholder?: string;
  /** 是否只读 */
  editable?: boolean;
}

export default function TiptapEditor({
  content,
  onChange,
  placeholder = '开始写作...',
  editable = true,
}: TiptapEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
      }),
      Placeholder.configure({ placeholder }),
    ],
    content,
    editable,
    onUpdate: ({ editor }) => {
      onChange(editor.getHTML());
    },
    editorProps: {
      attributes: {
        class: 'tiptap-content',
      },
    },
  });

  if (!editor) return null;

  return (
    <div className="border border-[var(--color-border)] rounded-[var(--radius-md)] bg-[var(--color-card)] overflow-hidden">
      {/* 工具栏 */}
      {editable && (
        <Toolbar editor={editor} />
      )}

      {/* 编辑区域 */}
      <EditorContent editor={editor} />
    </div>
  );
}

/** 工具栏组件 */
function Toolbar({ editor }: { editor: Editor }) {
  return (
    <div className="flex flex-wrap items-center gap-0.5 px-2 py-1.5 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
      {/* 文本格式 */}
      <ToolbarBtn
        active={editor.isActive('bold')}
        onClick={() => editor.chain().focus().toggleBold().run()}
        title="加粗"
      >
        <Bold size={16} />
      </ToolbarBtn>
      <ToolbarBtn
        active={editor.isActive('italic')}
        onClick={() => editor.chain().focus().toggleItalic().run()}
        title="斜体"
      >
        <Italic size={16} />
      </ToolbarBtn>
      <ToolbarBtn
        active={editor.isActive('strike')}
        onClick={() => editor.chain().focus().toggleStrike().run()}
        title="删除线"
      >
        <Strikethrough size={16} />
      </ToolbarBtn>
      <ToolbarBtn
        active={editor.isActive('code')}
        onClick={() => editor.chain().focus().toggleCode().run()}
        title="行内代码"
      >
        <Code size={16} />
      </ToolbarBtn>

      <Divider />

      {/* 标题 */}
      <ToolbarBtn
        active={editor.isActive('heading', { level: 1 })}
        onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
        title="标题 1"
      >
        <Heading1 size={16} />
      </ToolbarBtn>
      <ToolbarBtn
        active={editor.isActive('heading', { level: 2 })}
        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
        title="标题 2"
      >
        <Heading2 size={16} />
      </ToolbarBtn>
      <ToolbarBtn
        active={editor.isActive('heading', { level: 3 })}
        onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
        title="标题 3"
      >
        <Heading3 size={16} />
      </ToolbarBtn>

      <Divider />

      {/* 列表 */}
      <ToolbarBtn
        active={editor.isActive('bulletList')}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
        title="无序列表"
      >
        <List size={16} />
      </ToolbarBtn>
      <ToolbarBtn
        active={editor.isActive('orderedList')}
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
        title="有序列表"
      >
        <ListOrdered size={16} />
      </ToolbarBtn>

      <Divider />

      {/* 块级元素 */}
      <ToolbarBtn
        active={editor.isActive('blockquote')}
        onClick={() => editor.chain().focus().toggleBlockquote().run()}
        title="引用"
      >
        <Quote size={16} />
      </ToolbarBtn>
      <ToolbarBtn
        active={editor.isActive('codeBlock')}
        onClick={() => editor.chain().focus().toggleCodeBlock().run()}
        title="代码块"
      >
        <FileCode size={16} />
      </ToolbarBtn>
      <ToolbarBtn
        onClick={() => editor.chain().focus().setHorizontalRule().run()}
        title="分割线"
      >
        <Minus size={16} />
      </ToolbarBtn>

      <Divider />

      {/* 撤销 / 重做 */}
      <ToolbarBtn
        onClick={() => editor.chain().focus().undo().run()}
        disabled={!editor.can().undo()}
        title="撤销"
      >
        <Undo size={16} />
      </ToolbarBtn>
      <ToolbarBtn
        onClick={() => editor.chain().focus().redo().run()}
        disabled={!editor.can().redo()}
        title="重做"
      >
        <Redo size={16} />
      </ToolbarBtn>
    </div>
  );
}

/** 工具栏按钮 */
function ToolbarBtn({
  children,
  active,
  disabled,
  onClick,
  title,
}: {
  children: React.ReactNode;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
  title: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`
        p-1.5 rounded transition-colors
        ${active
          ? 'bg-[var(--color-accent)] text-white'
          : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-bg)] hover:text-[var(--color-accent)]'
        }
        disabled:opacity-30 disabled:cursor-not-allowed
      `}
    >
      {children}
    </button>
  );
}

/** 工具栏分隔线 */
function Divider() {
  return <div className="w-px h-5 bg-[var(--color-border)] mx-1" />;
}
