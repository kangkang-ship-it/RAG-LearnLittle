/**
 * 根组件
 * 
 * 职责：
 * 1. 使用 useRoutes 渲染路由
 * 2. 监听主题变化，切换 document.documentElement 的 dark class
 */

import { useEffect } from 'react';
import { useRoutes } from 'react-router-dom';
import { useThemeStore } from './stores/useThemeStore';
import { routes } from './router';

export default function App() {
  const theme = useThemeStore((s) => s.theme);
  const element = useRoutes(routes);

  // 主题切换：切换 dark class，所有 CSS 变量自动切换
  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  return element;
}
