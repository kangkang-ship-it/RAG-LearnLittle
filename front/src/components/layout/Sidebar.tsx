/**
 * 侧边导航栏
 * 
 * 可折叠设计：
 * - 展开态：240px 宽，显示图标 + 文字
 * - 折叠态：54px 宽，只显示图标 + Tooltip
 * 
 * 分为三个区域：
 * 1. 功能导航（5 项）：笔记、AI 对话、对话历史、每日回顾、知识库
 * 2. 设置导航（3 项）：个人信息、设置、关于
 * 3. 底部：退出登录
 */

import { NavLink, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  FileText, MessageSquare, History, BookOpen, Library,
  User, Settings, Info, LogOut, ChevronLeft, ChevronRight,
} from 'lucide-react';
import { useUserStore } from '../../stores/useUserStore';
import { authApi } from '../../api/auth';

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

/** 导航项配置 */
const navItems = [
  { to: '/notes', icon: FileText, labelKey: 'nav.notes' },
  { to: '/chat', icon: MessageSquare, labelKey: 'nav.chat' },
  { to: '/sessions', icon: History, labelKey: 'nav.sessions' },
  { to: '/review', icon: BookOpen, labelKey: 'nav.review' },
  { to: '/knowledge', icon: Library, labelKey: 'nav.knowledge' },
];

const settingItems = [
  { to: '/profile', icon: User, labelKey: 'nav.profile' },
  { to: '/settings', icon: Settings, labelKey: 'nav.settings' },
  { to: '/about', icon: Info, labelKey: 'nav.about' },
];

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const logout = useUserStore((s) => s.logout);

  /** 处理登出 */
  const handleLogout = async () => {
    try {
      // 传入 device_id 精确撤销当前设备会话
      const deviceId = localStorage.getItem('device_id') || undefined;
      await authApi.logout(deviceId);
    } catch {
      // 即使后端失败也清除本地状态
    }
    logout();
    navigate('/login');
  };

  /** 渲染导航项 */
  const renderNavItem = (item: { to: string; icon: React.ElementType; labelKey: string }) => {
    const Icon = item.icon;
    return (
      <NavLink
        key={item.to}
        to={item.to}
        className={({ isActive }) =>
          `flex items-center gap-3 ${collapsed ? 'px-0' : 'px-4'} py-2.5 rounded-[var(--radius-md)] transition-all duration-200 ${
            isActive
              ? 'bg-[#1677ff] text-white shadow-[0_2px_8px_rgba(22,119,255,0.3)]'
              : 'text-[#5a6a8a] hover:bg-[#e8f0fe] hover:text-[#1677ff]'
          } ${collapsed ? 'justify-center' : ''}`
        }
        title={collapsed ? t(item.labelKey) : undefined}
      >
        <Icon size={20} />
        {!collapsed && <span className="text-sm font-medium">{t(item.labelKey)}</span>}
      </NavLink>
    );
  };

  return (
    <aside
      className={`flex flex-col h-full border-r border-[#d4dff0] transition-all duration-300 ${
        collapsed ? 'w-14' : 'w-60'
      }`}
      style={{
        background: 'rgba(240, 245, 255, 0.85)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
      }}
    >
      {/* Logo 区域 */}
      <div className={`flex items-center p-4 border-b border-[var(--color-border)] ${collapsed ? 'justify-center' : 'justify-between'}`}>
        {!collapsed && (
          <h1 className="font-heading text-2xl font-bold text-[#1a2a4a]">
            云上笔记
          </h1>
        )}
        <button
          onClick={onToggle}
          className={`p-2 rounded-[var(--radius-sm)] transition-all duration-200 ${
            collapsed
              ? 'bg-[#e8f0fe] text-[#1677ff] hover:bg-[#1677ff] hover:text-white'
              : 'text-[#5a6a8a] hover:bg-[#e8f0fe] hover:text-[#1677ff]'
          }`}
          title={collapsed ? t('nav.expand') : t('nav.collapse')}
        >
          {collapsed ? <ChevronRight size={20} /> : <ChevronLeft size={20} />}
        </button>
      </div>

      {/* 功能导航 */}
      <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
        {navItems.map(renderNavItem)}
      </nav>

      {/* 设置导航 */}
      <div className="p-3 space-y-1 border-t border-[var(--color-border)]">
        {settingItems.map(renderNavItem)}
      </div>

      {/* 退出登录 */}
      <div className="p-3 border-t border-[var(--color-border)]">
        <button
          onClick={handleLogout}
          className={`flex items-center gap-3 ${collapsed ? 'px-0' : 'px-4'} py-2.5 rounded-[var(--radius-md)] w-full text-[#1677ff] hover:bg-[#e8f0fe] transition-all duration-200 ${
            collapsed ? 'justify-center' : ''
          }`}
          title={collapsed ? t('nav.logout') : undefined}
        >
          <LogOut size={20} />
          {!collapsed && <span className="text-sm font-medium">{t('nav.logout')}</span>}
        </button>
      </div>
    </aside>
  );
}
