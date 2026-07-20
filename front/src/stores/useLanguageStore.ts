/**
 * 语言状态管理
 * 
 * 职责：管理界面语言（中/英）。
 * 持久化：localStorage。
 * 
 * 切换时同步调用 i18n.changeLanguage() 使整个应用即时生效。
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface LanguageState {
  /** 当前语言 */
  lang: 'zh-CN' | 'en-US';
  /** 设置语言 */
  setLang: (lang: 'zh-CN' | 'en-US') => void;
}

export const useLanguageStore = create<LanguageState>()(
  persist(
    (set) => ({
      lang: 'zh-CN',

      setLang: (lang) => {
        set({ lang });
        // 同步切换 i18next 语言
        import('../i18n').then((mod) => {
          mod.default.changeLanguage(lang);
        });
      },
    }),
    { name: 'language-store' }
  )
);
