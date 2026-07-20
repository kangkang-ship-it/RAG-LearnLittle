/**
 * 聊天 API（SSE 流式）
 * 
 * 对应后端路由：/api/v1/chat/query
 * 
 * SSE 流式通信使用原生 fetch + ReadableStream，
 * 不走 Axios（Axios 不支持流式读取）。
 */

import { endpoints } from './endpoints';

/**
 * 发起 SSE 流式对话请求
 * 
 * 使用原生 fetch 发送 POST 请求，返回 ReadableStream 供 useSSE Hook 消费。
 * 需要手动注入 JWT Token 到 Authorization 头。
 * 
 * @param body - 请求体（session_id, message, idempotency_key）
 * @param signal - AbortSignal 用于取消请求
 * @returns fetch Response 对象
 */
export async function sendChatSSE(
  body: { session_id?: string; message: string; idempotency_key?: string },
  signal?: AbortSignal
): Promise<Response> {
  const token = localStorage.getItem('jwt_token');

  const response = await fetch(endpoints.chat.query, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    throw new Error(`SSE 请求失败: ${response.status}`);
  }

  return response;
}
