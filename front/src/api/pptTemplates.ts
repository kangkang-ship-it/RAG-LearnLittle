/**
 * PPT 模板 API
 *
 * 对应后端路由：/api/v1/ppt-template*（设计方案 §6.5）
 * 上传与聊天附件一致：原生 XHR + FormData + 手动注入 JWT。
 */

import client from './client';
import { endpoints } from './endpoints';
import type { ApiResponse } from '../types/api';

/** PPT 模板信息（后端 /ppt-template 返回结构） */
export interface PptTemplateInfo {
  id: number;
  name: string;
  file_size: number;
  created_at: string | null;
}

export const pptTemplatesApi = {
  /**
   * 上传 PPT 模板（.pptx，魔数/大小/数量校验由后端完成）
   *
   * @param file - 本地 .pptx 文件
   * @param name - 模板名称（可选，默认取文件名）
   */
  upload: (file: File, name: string = '') =>
    new Promise<ApiResponse<PptTemplateInfo>>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const token = localStorage.getItem('jwt_token');

      xhr.open('POST', endpoints.ppt.templateUpload);
      if (token) {
        xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      }

      xhr.onload = () => {
        try {
          const resp = JSON.parse(xhr.responseText);
          if (xhr.status >= 200 && xhr.status < 300 && resp.code === 0) {
            resolve(resp);
          } else {
            reject(new Error(resp.detail || resp.message || `上传失败(${xhr.status})`));
          }
        } catch {
          reject(new Error(`上传失败(${xhr.status})`));
        }
      };
      xhr.onerror = () => reject(new Error('网络错误，上传失败'));

      const formData = new FormData();
      formData.append('file', file);
      if (name) formData.append('name', name);
      xhr.send(formData);
    }),

  /** 模板列表（按创建时间倒序） */
  list: () =>
    client.get<ApiResponse<{ templates: PptTemplateInfo[] }>>(endpoints.ppt.templateBase),

  /** 删除模板 */
  remove: (id: number) =>
    client.delete<ApiResponse<null>>(endpoints.ppt.templateDetail(id)),
};
