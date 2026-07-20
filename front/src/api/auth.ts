/**
 * 认证相关 API
 * 
 * 对应后端路由：/api/v1/auth/*
 */

import client from './client';
import { endpoints } from './endpoints';
import type { ApiResponse, TokenResponse, UserRegister, UserLogin } from '../types/api';

export const authApi = {
  /** 用户注册 */
  register: (data: UserRegister) =>
    client.post<ApiResponse<{ user_id: string; username: string }>>(endpoints.auth.register, data),

  /** 用户登录 */
  login: (data: UserLogin) =>
    client.post<ApiResponse<TokenResponse>>(endpoints.auth.login, data),

  /** 用户登出 */
  logout: () =>
    client.post<ApiResponse<null>>(endpoints.auth.logout),

  /** 刷新 Token（Rotation 防重放） */
  refresh: (refreshToken: string) =>
    client.post<ApiResponse<TokenResponse>>(endpoints.auth.refresh, { refresh_token: refreshToken }),

  /** 获取 SSE 短期 Token */
  getSseToken: () =>
    client.post<ApiResponse<{ token: string; expires_in: number }>>(endpoints.auth.sseToken),
};
