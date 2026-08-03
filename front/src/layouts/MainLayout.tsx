/**
 * 主布局
 * 
 * 左侧可折叠侧边栏 + 右侧内容区。
 * 包含路由守卫：未登录 → 重定向到 /login。
 */

import { useState } from 'react';
import { Outlet, Navigate } from 'react-router-dom';
import { useUserStore } from '../stores/useUserStore';
import Sidebar from '../components/layout/Sidebar';

export default function MainLayout() {
  const isLogin = useUserStore((s) => s.isLogin);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  // 路由守卫：未登录 → 重定向到登录页
  if (!isLogin) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="flex h-screen relative overflow-hidden"
      style={{ background: 'var(--color-gradient-bg)' }}>

      {/* 低透明度浮动圆角矩形装饰 */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden="true">
        <div className="absolute -top-16 -right-20 w-72 h-72 rounded-[40px] rotate-12"
          style={{ background: 'var(--color-decor-1)' }} />
        <div className="absolute top-1/3 -left-16 w-56 h-56 rounded-[32px] -rotate-6"
          style={{ background: 'var(--color-decor-2)' }} />
        <div className="absolute -bottom-20 right-1/4 w-64 h-64 rounded-[36px] rotate-45"
          style={{ background: 'var(--color-decor-3)' }} />
      </div>

      {/* 侧边导航栏 */}
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      {/* 右侧内容区 */}
      <main className="flex-1 overflow-y-auto relative" style={{ zIndex: 1 }}>
        <div className="p-6 max-w-6xl mx-auto">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
