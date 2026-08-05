/**
 * 应用入口
 * 
 * 挂载：
 * 1. BrowserRouter — 路由
 * 2. App — 根组件（主题切换 + 路由渲染）
 * 3. Toaster — sonner 通知
 * 4. i18n — 国际化初始化
 */

import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { Toaster } from 'sonner';
import App from './App';
import './i18n';
import 'katex/dist/katex.min.css';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
      <Toaster
        position="top-right"
        toastOptions={{
          style: {
            background: 'var(--color-card)',
            color: 'var(--color-text)',
            border: '1px solid var(--color-border)',
          },
        }}
      />
    </BrowserRouter>
  </React.StrictMode>
);
