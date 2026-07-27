/**
 * 认证页面布局
 * 
 * Login: 左右分栏全页布局（组件自行管理）
 * Register: 居中卡片式布局
 */

import { Outlet, useLocation } from 'react-router-dom';

export default function AuthLayout() {
  const location = useLocation();
  const isLogin = location.pathname === '/login';

  if (isLogin) {
    return <Outlet />;
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)]">
      <div className="w-full max-w-md p-8 bg-[var(--color-card)] rounded-[var(--radius-lg)] shadow-card animate-slide-up">
        <Outlet />
      </div>
    </div>
  );
}
