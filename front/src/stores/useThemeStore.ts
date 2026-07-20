/**
 * 主题状态管理
 * 
 * 职责：管理亮/暗主题切换。
 * 持久化：localStorage。
 * 
 * 通过切换 document.documentElement 的 'dark' class，
 * 所有 CSS 变量自动切换。
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface ThemeState {
  /** 当前主题 */
  theme: 'light' | 'dark';
  /** 切换主题 */
  toggleTheme: () => void;
  /** 设置指定主题 */
  setTheme: (theme: 'light' | 'dark') => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: 'light',

      toggleTheme: () =>
        set((state) => ({ theme: state.theme === 'light' ? 'dark' : 'light' })),

      setTheme: (theme) => set({ theme }),
    }),
    { name: 'theme-store' }
  )
);
