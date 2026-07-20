/**
 * 认证页面布局
 * 
 * 居中卡片式布局，用于 Login / Register 页面。
 * 背景为暖白色，中间放置白色卡片。
 */

import { Outlet } from 'react-router-dom';

export default function AuthLayout() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)]">
      <div className="w-full max-w-md p-8 bg-[var(--color-card)] rounded-[var(--radius-lg)] shadow-card animate-slide-up">
        <Outlet />
      </div>
    </div>
  );
}
