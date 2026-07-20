/**
 * 空状态占位组件
 * 
 * 当列表无数据时显示，包含图标、标题、描述和操作按钮。
 */

import type { ReactNode } from 'react';

interface EmptyStateProps {
  icon: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}

export default function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="text-[var(--color-text-tertiary)] mb-4">
        {icon}
      </div>
      <h3 className="text-lg font-medium text-[var(--color-text-secondary)] mb-2">
        {title}
      </h3>
      {description && (
        <p className="text-sm text-[var(--color-text-tertiary)] mb-4 max-w-sm">
          {description}
        </p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
