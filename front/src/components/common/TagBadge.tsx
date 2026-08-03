/**
 * 标签徽章组件
 * 
 * 彩色小圆角标签，用于笔记列表和详情页展示标签。
 */

interface TagBadgeProps {
  label: string;
  onRemove?: () => void;
}

/** 标签颜色池 — 蓝色系深浅分层（循环使用），含暗色模式变体 */
const TAG_COLORS = [
  'bg-blue-50 text-[#1677ff] dark:bg-blue-950/30 dark:text-blue-400',
  'bg-sky-50 text-[#0284c7] dark:bg-sky-950/30 dark:text-sky-400',
  'bg-indigo-50 text-[#4f46e5] dark:bg-indigo-950/30 dark:text-indigo-400',
  'bg-cyan-50 text-[#0891b2] dark:bg-cyan-950/30 dark:text-cyan-400',
  'bg-blue-100 text-[#1a56db] dark:bg-blue-900/30 dark:text-blue-300',
  'bg-slate-50 text-[#475569] dark:bg-slate-800/30 dark:text-slate-300',
];

/** 根据标签文本生成稳定的颜色索引 */
function getColorIndex(label: string): number {
  let hash = 0;
  for (let i = 0; i < label.length; i++) {
    hash = label.charCodeAt(i) + ((hash << 5) - hash);
  }
  return Math.abs(hash) % TAG_COLORS.length;
}

export default function TagBadge({ label, onRemove }: TagBadgeProps) {
  const colorClass = TAG_COLORS[getColorIndex(label)];

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${colorClass}`}>
      {label}
      {onRemove && (
        <button
          onClick={onRemove}
          className="ml-0.5 hover:opacity-70"
          aria-label={`移除标签 ${label}`}
        >
          ×
        </button>
      )}
    </span>
  );
}
