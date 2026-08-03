/**
 * 用户相关 API
 * 
 * 对应后端路由：/api/v1/user/* 和 /api/v1/file/*
 */

import client from './client';
import { endpoints } from './endpoints';
import type {
  ApiResponse, UserInfo, UserUpdate, PasswordChange, EmailChangeRequest,
} from '../types/api';

export const userApi = {
  /** 获取当前用户信息 */
  getMe: () =>
    client.get<ApiResponse<UserInfo>>(endpoints.user.me),

  /** 更新用户信息（注意：不含 email，邮箱变更请使用 changeEmail） */
  updateMe: (data: UserUpdate) =>
    client.put<ApiResponse<null>>(endpoints.user.me, data),

  /** 修改/绑定邮箱（两步流程第二步：提交新邮箱 + 验证码） */
  changeEmail: (data: EmailChangeRequest) =>
    client.post<ApiResponse<null>>(endpoints.user.changeEmail, data),

  /** 修改密码 */
  changePassword: (data: PasswordChange) =>
    client.post<ApiResponse<null>>(endpoints.user.password, data),

  /** 上传头像（FormData） */
  uploadAvatar: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post<ApiResponse<{ avatar_url: string; filename: string }>>(
      endpoints.user.avatar,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    );
  },
};
