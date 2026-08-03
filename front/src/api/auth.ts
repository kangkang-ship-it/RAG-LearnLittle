/**
 * 认证相关 API
 * 
 * 对应后端路由：/api/v1/auth/*
 */

import client from './client';
import { endpoints } from './endpoints';
import type { ApiResponse, TokenResponse, UserRegister, UserLogin, SessionInfo } from '../types/api';

export const authApi = {
  /** 用户注册 */
  register: (data: UserRegister) =>
    client.post<ApiResponse<{ user_id: string; username: string }>>(endpoints.auth.register, data),

  /** 用户登录 */
  login: (data: UserLogin) =>
    client.post<ApiResponse<TokenResponse>>(endpoints.auth.login, data),

  /** 发送邮箱验证码（注册 / 修改邮箱复用） */
  sendVerificationCode: (email: string) =>
    client.post<ApiResponse<null>>(endpoints.auth.sendCode, { email }),

  /**
   * 用户登出
   * @param deviceId 可选，传入则只撤销当前设备会话；不传则撤销所有
   */
  logout: (deviceId?: string) =>
    client.post<ApiResponse<null>>(endpoints.auth.logout, deviceId ? { device_id: deviceId } : {}),

  /** 刷新 Token（Rotation 防重放） */
  refresh: (refreshToken: string, deviceId?: string) =>
    client.post<ApiResponse<TokenResponse>>(endpoints.auth.refresh, {
      refresh_token: refreshToken,
      ...(deviceId ? { device_id: deviceId } : {}),
    }),

  /** 获取 SSE 短期 Token */
  getSseToken: () =>
    client.post<ApiResponse<{ token: string; expires_in: number }>>(endpoints.auth.sseToken),

  /** 获取活跃设备会话列表 */
  getSessions: () =>
    client.get<ApiResponse<{ sessions: SessionInfo[] }>>(endpoints.auth.sessions),

  /** 撤销指定设备会话 */
  revokeSession: (deviceId: string) =>
    client.delete<ApiResponse<null>>(endpoints.auth.sessionRevoke(deviceId)),
};
