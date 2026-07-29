/**
 * 确认弹窗组件
 * 
 * 纯 React 实现，不依赖 Radix UI。
 * 直接在 React 树中渲染，使用 fixed 定位 + 高 z-index。
 * 支持 danger 变体（红色确认按钮）。
 */

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
  if (!open) return null;

  const confirmBg = variant === 'danger' ? '#e05555' : '#1677ff';

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100vw',
        height: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(0,0,0,0.4)',
        zIndex: 2147483647,
      }}
      onClick={onCancel}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '28rem',
          padding: '1.5rem',
          backgroundColor: '#ffffff',
          borderRadius: '1rem',
          boxShadow: '0 12px 48px rgba(22,119,255,0.1)',
          border: '1px solid #d4dff0',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#1a2a4a', margin: 0 }}>
          {title}
        </h3>
        <p style={{ marginTop: '0.5rem', fontSize: '0.875rem', color: '#5a6a8a' }}>
          {description}
        </p>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1.5rem' }}>
          <button
            onClick={onCancel}
            style={{
              padding: '0.5rem 1rem',
              fontSize: '0.875rem',
              borderRadius: '0.75rem',
              border: '1px solid #d4dff0',
              backgroundColor: '#fff',
              color: '#5a6a8a',
              cursor: 'pointer',
            }}
          >
            {cancelLabel}
          </button>
          <button
            onClick={() => { onConfirm(); onCancel(); }}
            style={{
              padding: '0.5rem 1rem',
              fontSize: '0.875rem',
              borderRadius: '999px',
              border: 'none',
              backgroundColor: confirmBg,
              color: '#fff',
              cursor: 'pointer',
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
