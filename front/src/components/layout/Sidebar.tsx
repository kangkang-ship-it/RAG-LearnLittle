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

import { useEffect, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  FileText, MessageSquare, History, BookOpen, Library,
  User, Settings, Info, LogOut, ChevronLeft, ChevronRight, Trash2,
} from 'lucide-react';
import { useUserStore } from '../../stores/useUserStore';
import { authApi } from '../../api/auth';
import { notesApi } from '../../api/notes';

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
  { to: '/recycle-bin', icon: Trash2, labelKey: 'nav.recycle_bin' },
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

  /** 回收站角标：已删除笔记数量（通过列表接口 total 获取） */
  const [trashCount, setTrashCount] = useState(0);

  useEffect(() => {
    notesApi
      .listDeleted({ page_size: 1 })
      .then((res) => setTrashCount(res.data.data?.total ?? 0))
      .catch(() => {
        // 加载失败不阻塞导航渲染
      });
  }, []);

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

  /** 渲染导航项（回收站项附带已删除数量角标） */
  const renderNavItem = (item: { to: string; icon: React.ElementType; labelKey: string }) => {
    const Icon = item.icon;
    const showBadge = item.to === '/recycle-bin' && trashCount > 0;
    return (
      <NavLink
        key={item.to}
        to={item.to}
        className={({ isActive }) =>
          `flex items-center gap-3 ${collapsed ? 'px-0' : 'px-4'} py-2.5 rounded-[var(--radius-md)] transition-all duration-200 ${
            isActive
              ? 'bg-[var(--color-accent)] text-[var(--color-on-accent)] shadow-[var(--shadow-accent-sm)]'
              : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-bg)] hover:text-[var(--color-accent)]'
          } ${collapsed ? 'justify-center' : ''}`
        }
        title={collapsed ? t(item.labelKey) : undefined}
      >
        <div className="relative">
          <Icon size={20} />
          {showBadge && (
            <span className="absolute -top-1.5 -right-2 min-w-4 h-4 px-1 rounded-full bg-red-500 text-white text-[10px] leading-4 text-center">
              {trashCount > 99 ? '99+' : trashCount}
            </span>
          )}
        </div>
        {!collapsed && <span className="text-sm font-medium">{t(item.labelKey)}</span>}
      </NavLink>
    );
  };

  return (
    <aside
      className={`flex flex-col h-full border-r border-[var(--color-border)] transition-all duration-300 ${
        collapsed ? 'w-14' : 'w-60'
      }`}
      style={{
        background: 'var(--color-sidebar-bg)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
      }}
    >
      {/* Logo 区域 */}
      <div className={`flex items-center p-4 border-b border-[var(--color-border)] ${collapsed ? 'justify-center' : 'justify-between'}`}>
        {!collapsed && (
          <h1 className="font-heading text-2xl font-bold text-[var(--color-text)]">
            云尚
          </h1>
        )}
        <button
          onClick={onToggle}
          className={`p-2 rounded-[var(--radius-sm)] transition-all duration-200 ${
            collapsed
              ? 'bg-[var(--color-accent-bg)] text-[var(--color-accent)] hover:bg-[var(--color-accent)] hover:text-[var(--color-on-accent)]'
              : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-bg)] hover:text-[var(--color-accent)]'
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
          className={`flex items-center gap-3 ${collapsed ? 'px-0' : 'px-4'} py-2.5 rounded-[var(--radius-md)] w-full text-[var(--color-accent)] hover:bg-[var(--color-accent-bg)] transition-all duration-200 ${
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
