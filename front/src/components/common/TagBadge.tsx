/**
 * 标签徽章组件
 * 
 * 彩色小圆角标签，用于笔记列表和详情页展示标签。
 */

interface TagBadgeProps {
  label: string;
  onRemove?: () => void;
}

/** 标签颜色池（循环使用） */
const TAG_COLORS = [
  'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
  'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300',
  'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300',
  'bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-300',
  'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-300',
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
