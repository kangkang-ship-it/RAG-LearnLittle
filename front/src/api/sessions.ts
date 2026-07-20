/**
 * 聊天会话 API
 * 
 * 对应后端路由：/api/v1/chat/sessions* 和 /api/v1/chat/{session_id}/*
 */

import client from './client';
import { endpoints } from './endpoints';
import type { ApiResponse, ChatSession, MessageListResponse, SessionTitleUpdate } from '../types/api';

export const sessionsApi = {
  /** 获取会话列表 */
  list: () =>
    client.get<ApiResponse<{ sessions: ChatSession[] }>>(endpoints.chat.sessions),

  /** 删除会话 */
  delete: (sessionId: string) =>
    client.delete<ApiResponse<null>>(endpoints.chat.sessionDetail(sessionId)),

  /** 获取消息历史（游标分页） */
  getMessages: (sessionId: string, params?: { cursor?: string; limit?: number }) =>
    client.get<ApiResponse<MessageListResponse>>(endpoints.chat.messages(sessionId), { params }),

  /** 修改会话标题 */
  updateTitle: (sessionId: string, data: SessionTitleUpdate) =>
    client.put<ApiResponse<null>>(endpoints.chat.sessionTitle(sessionId), data),
};
