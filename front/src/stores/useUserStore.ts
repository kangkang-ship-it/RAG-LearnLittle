/**
 * 用户状态管理
 * 
 * 职责：管理用户身份、JWT Token、登录状态。
 * 持久化：localStorage（通过 Zustand persist 中间件）。
 * 
 * Token 双写：Zustand persist 存一份，同时手动写入 localStorage('jwt_token')，
 * 供 Axios 请求拦截器读取（拦截器不在 React 组件树内，无法访问 Store）。
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { UserInfo } from '../types/api';

interface UserState {
  /** Access Token（JWT） */
  token: string;
  /** Refresh Token */
  refreshToken: string;
  /** 用户信息 */
  userInfo: UserInfo | null;
  /** 是否已登录 */
  isLogin: boolean;

  /**
   * 登录成功 — 保存 Token 和用户信息
   * 双写 localStorage 供 Axios 拦截器使用
   */
  login: (token: string, refreshToken: string, user: UserInfo) => void;

  /** 登出 — 清除所有状态 */
  logout: () => void;

  /** 更新用户信息（不改变 Token） */
  updateUserInfo: (user: Partial<UserInfo>) => void;

  /** 更新 Token（刷新后调用） */
  updateTokens: (token: string, refreshToken: string) => void;
}

export const useUserStore = create<UserState>()(
  persist(
    (set) => ({
      token: '',
      refreshToken: '',
      userInfo: null,
      isLogin: false,

      login: (token, refreshToken, user) => {
        // 双写 localStorage
        localStorage.setItem('jwt_token', token);
        localStorage.setItem('jwt_refresh_token', refreshToken);
        set({ token, refreshToken, userInfo: user, isLogin: true });
      },

      logout: () => {
        localStorage.removeItem('jwt_token');
        localStorage.removeItem('jwt_refresh_token');
        set({ token: '', refreshToken: '', userInfo: null, isLogin: false });
      },

      updateUserInfo: (user) =>
        set((state) => ({
          userInfo: state.userInfo ? { ...state.userInfo, ...user } : null,
        })),

      updateTokens: (token, refreshToken) => {
        localStorage.setItem('jwt_token', token);
        localStorage.setItem('jwt_refresh_token', refreshToken);
        set({ token, refreshToken });
      },
    }),
    { name: 'user-store' }
  )
);
