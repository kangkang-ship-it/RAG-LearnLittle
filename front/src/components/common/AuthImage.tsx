/**
 * 认证页装饰插图
 * 
 * 用于 Login / Register 页面的装饰性 SVG 插图。
 */

export default function AuthImage() {
  return (
    <div className="flex justify-center mb-6">
      <svg width="120" height="120" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
        {/* 书本形状 */}
        <rect x="20" y="30" width="80" height="60" rx="4" fill="var(--color-accent-bg)" stroke="var(--color-accent)" strokeWidth="2" />
        <line x1="60" y1="30" x2="60" y2="90" stroke="var(--color-accent)" strokeWidth="2" />
        {/* 页面线条 */}
        <line x1="30" y1="45" x2="55" y2="45" stroke="var(--color-border)" strokeWidth="1.5" />
        <line x1="30" y1="55" x2="50" y2="55" stroke="var(--color-border)" strokeWidth="1.5" />
        <line x1="30" y1="65" x2="52" y2="65" stroke="var(--color-border)" strokeWidth="1.5" />
        <line x1="65" y1="45" x2="90" y2="45" stroke="var(--color-border)" strokeWidth="1.5" />
        <line x1="65" y1="55" x2="85" y2="55" stroke="var(--color-border)" strokeWidth="1.5" />
        <line x1="65" y1="65" x2="88" y2="65" stroke="var(--color-border)" strokeWidth="1.5" />
        {/* AI 星标 */}
        <circle cx="60" cy="18" r="8" fill="var(--color-accent)" opacity="0.2" />
        <text x="60" y="22" textAnchor="middle" fill="var(--color-accent)" fontSize="12" fontWeight="bold">AI</text>
      </svg>
    </div>
  );
}
