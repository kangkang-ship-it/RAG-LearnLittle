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
    <div className="flex h-screen bg-[var(--color-bg)]">
      {/* 侧边导航栏 */}
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      {/* 右侧内容区 */}
      <main className="flex-1 overflow-y-auto">
        <div className="p-6 max-w-6xl mx-auto">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
