/**
 * 标签徽章组件
 * 
 * 彩色小圆角标签，用于笔记列表和详情页展示标签。
 */

interface TagBadgeProps {
  label: string;
  onRemove?: () => void;
}

/** 标签颜色池 — 蓝色系深浅分层（循环使用） */
const TAG_COLORS = [
  'bg-blue-50 text-[#1677ff]',
  'bg-sky-50 text-[#0284c7]',
  'bg-indigo-50 text-[#4f46e5]',
  'bg-cyan-50 text-[#0891b2]',
  'bg-blue-100 text-[#1a56db]',
  'bg-slate-50 text-[#475569]',
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
