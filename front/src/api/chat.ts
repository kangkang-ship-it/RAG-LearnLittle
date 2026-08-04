/**
 * 聊天 API（SSE 流式 + 附件上传）
 *
 * 对应后端路由：/api/v1/chat/query、/api/v1/chat/files
 *
 * SSE 流式通信使用原生 fetch + ReadableStream，不走 Axios（Axios 不支持流式读取）。
 * 附件上传使用 XHR（fetch 无上传进度事件），API 层对组件透明。
 */

import { endpoints } from './endpoints';
import type { UploadResponse } from '../types/api';

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

/**
 * 上传聊天附件（图片/视频）
 *
 * 使用 XHR 实现上传进度回调（fetch 无 upload.onprogress）。
 * 与知识库上传一致：原生 fetch/XHR + FormData + 手动注入 JWT。
 *
 * @param file - 本地文件
 * @param onProgress - 上传进度回调（0-100）
 * @returns 上传响应（file_id 等）
 */
export function uploadChatFile(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const token = localStorage.getItem('jwt_token');

    xhr.open('POST', endpoints.chat.fileUpload);
    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    }

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };

    xhr.onload = () => {
      try {
        const resp = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300 && resp.code === 0) {
          resolve(resp.data as UploadResponse);
        } else {
          reject(new Error(resp.detail || resp.message || `上传失败(${xhr.status})`));
        }
      } catch {
        reject(new Error(`上传失败(${xhr.status})`));
      }
    };

    xhr.onerror = () => reject(new Error('网络错误，上传失败'));
    xhr.ontimeout = () => reject(new Error('上传超时'));

    const formData = new FormData();
    formData.append('file', file);
    xhr.send(formData);
  });
}

/**
 * 删除未绑定的聊天附件（发送前删除）
 *
 * @param fileId - 附件 ID
 */
export async function deleteChatFile(fileId: string): Promise<void> {
  const token = localStorage.getItem('jwt_token');
  const response = await fetch(endpoints.chat.fileDetail(fileId), {
    method: 'DELETE',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!response.ok) {
    let detail = `删除失败(${response.status})`;
    try {
      const resp = await response.json();
      detail = resp.detail || resp.message || detail;
    } catch {
      // 忽略解析失败
    }
    throw new Error(detail);
  }
}

/**
 * 获取附件鉴权预览 URL
 *
 * <img>/<video> 标签无法携带 Authorization Header，
 * 拼 ?token= 短时效 access token 作为回显兜底（仅用于当次回显）。
 *
 * @param fileId - 附件 ID
 * @returns 带 token 的预览 URL
 */
export function getAttachmentUrl(fileId: string): string {
  const token = localStorage.getItem('jwt_token') || '';
  const sep = endpoints.chat.fileDetail(fileId).includes('?') ? '&' : '?';
  return `${endpoints.chat.fileDetail(fileId)}${sep}token=${encodeURIComponent(token)}`;
}
