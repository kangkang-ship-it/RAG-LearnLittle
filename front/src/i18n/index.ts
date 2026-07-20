/**
 * i18next 国际化配置
 * 
 * 默认中文，支持中英切换。
 * 切换方式：useLanguageStore.setLang('en-US')
 */

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import zh from './locales/zh-CN';
import en from './locales/en-US';

i18n.use(initReactI18next).init({
  resources: {
    'zh-CN': { translation: zh },
    'en-US': { translation: en },
  },
  lng: 'zh-CN',
  fallbackLng: 'zh-CN',
  interpolation: { escapeValue: false },
});

export default i18n;
