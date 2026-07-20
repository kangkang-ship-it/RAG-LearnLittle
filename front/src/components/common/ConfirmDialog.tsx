/**
 * 确认弹窗组件
 * 
 * 基于 Radix AlertDialog 封装。
 * 支持 danger 变体（红色确认按钮）。
 */

import * as AlertDialog from '@radix-ui/react-alert-dialog';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = '确认',
  cancelLabel = '取消',
  variant = 'default',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmClass = variant === 'danger'
    ? 'bg-[var(--color-danger)] text-white hover:opacity-90'
    : 'bg-[var(--color-accent)] text-white hover:opacity-90';

  return (
    <AlertDialog.Root open={open} onOpenChange={(v) => !v && onCancel()}>
      <AlertDialog.Portal>
        {/* 遮罩层 */}
        <AlertDialog.Overlay className="fixed inset-0 bg-black/40 animate-fade-in" />
        {/* 弹窗内容 */}
        <AlertDialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-md p-6 bg-[var(--color-card)] rounded-[var(--radius-lg)] shadow-card animate-fade-in">
          <AlertDialog.Title className="text-lg font-heading font-bold text-[var(--color-text)]">
            {title}
          </AlertDialog.Title>
          <AlertDialog.Description className="mt-2 text-sm text-[var(--color-text-secondary)]">
            {description}
          </AlertDialog.Description>
          {/* 操作按钮 */}
          <div className="flex justify-end gap-3 mt-6">
            <AlertDialog.Cancel asChild>
              <button className="px-4 py-2 text-sm rounded-[var(--radius-md)] border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-border)]">
                {cancelLabel}
              </button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <button className={`px-4 py-2 text-sm rounded-[var(--radius-md)] ${confirmClass}`} onClick={onConfirm}>
                {confirmLabel}
              </button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
