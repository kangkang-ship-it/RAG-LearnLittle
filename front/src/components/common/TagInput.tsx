/**
 * 标签输入组件
 * 
 * 回车添加标签，点击 × 删除标签。
 * 用于笔记编辑器的标签输入。
 */

import { useState } from 'react';
import type { KeyboardEvent } from 'react';
import TagBadge from './TagBadge';

interface TagInputProps {
  tags: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
}

export default function TagInput({ tags, onChange, placeholder = '输入标签后回车添加' }: TagInputProps) {
  const [input, setInput] = useState('');

  /** 回车添加标签 */
  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && input.trim()) {
      e.preventDefault();
      const newTag = input.trim();
      if (!tags.includes(newTag)) {
        onChange([...tags, newTag]);
      }
      setInput('');
    }
  };

  /** 删除标签 */
  const handleRemove = (tag: string) => {
    onChange(tags.filter((t) => t !== tag));
  };

  return (
    <div className="flex flex-wrap gap-2 items-center">
      {tags.map((tag) => (
        <TagBadge key={tag} label={tag} onRemove={() => handleRemove(tag)} />
      ))}
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={tags.length === 0 ? placeholder : ''}
        className="flex-1 min-w-[120px] text-sm bg-transparent border-none outline-none text-[var(--color-text)] placeholder:text-[var(--color-text-tertiary)]"
      />
    </div>
  );
}
