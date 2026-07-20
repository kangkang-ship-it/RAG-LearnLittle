/**
 * 笔记模板 API
 * 
 * 对应后端路由：/api/v1/note-template*
 */

import client from './client';
import { endpoints } from './endpoints';
import type { ApiResponse, NoteTemplate, NoteTemplateCreate, NoteTemplateUpdate } from '../types/api';

export const noteTemplatesApi = {
  /** 创建模板 */
  create: (data: NoteTemplateCreate) =>
    client.post<ApiResponse<NoteTemplate>>(endpoints.template.base, data),

  /** 获取模板列表 */
  list: () =>
    client.get<ApiResponse<{ templates: NoteTemplate[] }>>(endpoints.template.base),

  /** 获取模板详情 */
  detail: (templateId: number) =>
    client.get<ApiResponse<NoteTemplate>>(endpoints.template.detail(templateId)),

  /** 更新模板 */
  update: (templateId: number, data: NoteTemplateUpdate) =>
    client.put<ApiResponse<NoteTemplate>>(endpoints.template.detail(templateId), data),

  /** 删除模板 */
  delete: (templateId: number) =>
    client.delete<ApiResponse<null>>(endpoints.template.detail(templateId)),
};
