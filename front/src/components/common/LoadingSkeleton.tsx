/**
 * 骨架屏组件
 * 
 * 用于页面懒加载和数据加载时的占位显示。
 * 支持两种模式：
 * - 页面级：整页骨架（模拟笔记列表/对话界面形状）
 * - 卡片级：单条卡片骨架（标题条 + 内容行）
 */

interface LoadingSkeletonProps {
  /** 骨架行数（卡片级），默认 3 */
  lines?: number;
  /** 是否为页面级骨架 */
  fullPage?: boolean;
}

export default function LoadingSkeleton({ lines = 3, fullPage = false }: LoadingSkeletonProps) {
  const cardCount = fullPage ? 6 : 1;

  return (
    <div className={fullPage ? 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 p-6' : ''}>
      {Array.from({ length: cardCount }).map((_, i) => (
        <div
          key={i}
          className="bg-[var(--color-card)] rounded-2xl p-4 animate-pulse border border-[var(--color-border)] shadow-[var(--shadow-card)]"
        >
          {/* 标题条 */}
          <div className="h-5 bg-[var(--color-border)] rounded w-3/4 mb-3" />
          {/* 内容行 */}
          {Array.from({ length: lines }).map((_, j) => (
            <div
              key={j}
              className="h-3 bg-[var(--color-border)] rounded mb-2"
              style={{ width: `${70 + Math.random() * 30}%` }}
            />
          ))}
          {/* 底部标签 */}
          <div className="flex gap-2 mt-3">
            <div className="h-5 w-16 bg-[var(--color-border)] rounded-full" />
            <div className="h-5 w-12 bg-[var(--color-border)] rounded-full" />
          </div>
        </div>
      ))}
    </div>
  );
}
