/**
 * 路由配置
 * 
 * 两种布局：
 * - AuthLayout: /login, /register（不需要登录）
 * - MainLayout: 其余页面（需要登录，含路由守卫）
 * 
 * 所有页面组件使用 React.lazy() 懒加载。
 */

import { lazy, Suspense } from 'react';
import type { RouteObject } from 'react-router-dom';
import AuthLayout from '../layouts/AuthLayout';
import MainLayout from '../layouts/MainLayout';
import LoadingSkeleton from '../components/common/LoadingSkeleton';

// 懒加载页面组件
const Login = lazy(() => import('../pages/Login'));
const Register = lazy(() => import('../pages/Register'));
const NoteList = lazy(() => import('../pages/NoteList'));
const NoteEditor = lazy(() => import('../pages/NoteEditor'));
const AIChat = lazy(() => import('../pages/AIChat'));
const Sessions = lazy(() => import('../pages/Sessions'));
const KnowledgeBase = lazy(() => import('../pages/KnowledgeBase'));
const DailyReview = lazy(() => import('../pages/DailyReview'));
const RecycleBin = lazy(() => import('../pages/RecycleBin'));
const Profile = lazy(() => import('../pages/Profile'));
const Settings = lazy(() => import('../pages/Settings'));
const AboutUs = lazy(() => import('../pages/AboutUs'));

/** 包装 Suspense */
function LazyPage({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<LoadingSkeleton />}>
      {children}
    </Suspense>
  );
}

/** 路由配置 */
export const routes: RouteObject[] = [
  // 认证页面（AuthLayout）
  {
    element: <AuthLayout />,
    children: [
      {
        path: '/login',
        element: <LazyPage><Login /></LazyPage>,
      },
      {
        path: '/register',
        element: <LazyPage><Register /></LazyPage>,
      },
    ],
  },
  // 主应用（MainLayout，需要登录）
  {
    element: <MainLayout />,
    children: [
      {
        path: '/',
        element: <LazyPage><NoteList /></LazyPage>,
      },
      {
        path: '/notes',
        element: <LazyPage><NoteList /></LazyPage>,
      },
      {
        path: '/notes/new',
        element: <LazyPage><NoteEditor /></LazyPage>,
      },
      {
        path: '/notes/:id',
        element: <LazyPage><NoteEditor /></LazyPage>,
      },
      {
        path: '/chat',
        element: <LazyPage><AIChat /></LazyPage>,
      },
      {
        path: '/chat/:sessionId',
        element: <LazyPage><AIChat /></LazyPage>,
      },
      {
        path: '/sessions',
        element: <LazyPage><Sessions /></LazyPage>,
      },
      {
        path: '/knowledge',
        element: <LazyPage><KnowledgeBase /></LazyPage>,
      },
      {
        path: '/review',
        element: <LazyPage><DailyReview /></LazyPage>,
      },
      {
        path: '/recycle-bin',
        element: <LazyPage><RecycleBin /></LazyPage>,
      },
      {
        path: '/profile',
        element: <LazyPage><Profile /></LazyPage>,
      },
      {
        path: '/settings',
        element: <LazyPage><Settings /></LazyPage>,
      },
      {
        path: '/about',
        element: <LazyPage><AboutUs /></LazyPage>,
      },
    ],
  },
];
