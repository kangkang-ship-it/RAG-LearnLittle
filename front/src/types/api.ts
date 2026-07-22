/**
 * 全局 API 类型定义
 * 
 * 与后端 Pydantic Schema 一一对应，确保前后端数据结构一致。
 */

// ========== 通用响应 ==========

/** 后端统一响应格式 */
export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
  request_id: string;
}

// ========== 用户 & 认证 ==========

/** 用户注册请求 */
export interface UserRegister {
  username: string;
  password: string;
  email?: string;
}

/** 用户登录请求 */
export interface UserLogin {
  username: string;
  password: string;
  /** 设备唯一标识（前端生成并持久化） */
  device_id?: string;
  /** 设备可读名称，如 Chrome on Windows */
  device_name?: string;
}

/** Token 响应 */
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  /** 回传设备标识，前端应持久化存储 */
  device_id?: string;
}

/** 用户信息 */
export interface UserInfo {
  uuid: string;
  username: string;
  email: string | null;
  avatar: string | null;
  bio: string | null;
  status: string;
  created_at: string;
}

/** 用户信息更新 */
export interface UserUpdate {
  bio?: string;
  email?: string;
}

/** 密码修改 */
export interface PasswordChange {
  old_password: string;
  new_password: string;
}

/** 设备会话信息 */
export interface SessionInfo {
  device_id: string;
  device_name?: string;
  ip?: string;
  created_at?: string;
  last_used?: string;
  is_current: boolean;
}

// ========== 笔记 ==========

/** 笔记响应 */
export interface Note {
  id: string;
  user_id: string;
  title: string;
  content: string;
  tags: string[] | null;
  category: string | null;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
}

/** 创建笔记请求 */
export interface NoteCreate {
  title: string;
  content: string;
  tags?: string[];
  category?: string;
  is_pinned?: boolean;
}

/** 更新笔记请求 */
export interface NoteUpdate {
  title?: string;
  content?: string;
  tags?: string[];
  category?: string;
  is_pinned?: boolean;
}

/** 笔记列表响应 */
export interface NoteListResponse {
  notes: Note[];
  total: number;
  page: number;
  page_size: number;
}

/** 语义搜索请求 */
export interface NoteSearchRequest {
  query: string;
  top_k?: number;
}

/** 语义搜索结果项 */
export interface NoteSearchResult {
  title: string;
  content: string;
  score: number;
}

/** 批量操作请求 */
export interface BatchOperation {
  note_ids: string[];
  operation: 'delete' | 'pin' | 'unpin' | 'move';
  target_category?: string;
}

// ========== 聊天 ==========

/** 聊天消息 */
export interface ChatMessage {
  id: number;
  session_id: string;
  role: string;
  content: string;
  token_count?: number;
  created_at: string;
}

/** 聊天会话 */
export interface ChatSession {
  id: string;
  title: string;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  message_count?: number;
}

/** 消息列表响应（游标分页） */
export interface MessageListResponse {
  messages: ChatMessage[];
  has_more: boolean;
  next_cursor: string | null;
}

/** 对话请求 */
export interface QueryRequest {
  session_id?: string;
  message: string;
  idempotency_key?: string;
}

/** 会话标题修改 */
export interface SessionTitleUpdate {
  title: string;
}

// ========== 知识库 ==========

/** 知识库文档 */
export interface KnowledgeDocument {
  id: number;
  user_id: string;
  filename: string;
  file_size: number;
  file_type: string;
  md5_hash: string;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

/** 文档列表响应 */
export interface KnowledgeDocumentListResponse {
  documents: KnowledgeDocument[];
  total: number;
}

// ========== 回顾 ==========

/** 回顾记录 */
export interface ReviewRecord {
  id: number;
  note_id: string;
  note_title: string;
  next_review_at: string;
  interval_days: number;
  review_count: number;
}

/** 回顾统计 */
export interface ReviewStats {
  total_reviews: number;
  completed_today: number;
  pending_today: number;
  streak_days: number;
}

// ========== 模板 ==========

/** 笔记模板 */
export interface NoteTemplate {
  id: number;
  user_id: string;
  name: string;
  content_structure: Record<string, unknown> | null;
  category: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

/** 创建模板请求 */
export interface NoteTemplateCreate {
  name: string;
  content_structure?: Record<string, unknown>;
  category?: string;
  sort_order?: number;
}

/** 更新模板请求 */
export interface NoteTemplateUpdate {
  name?: string;
  content_structure?: Record<string, unknown>;
  category?: string;
  sort_order?: number;
}

// ========== SSE 消息类型 ==========

/** 聊天 SSE 消息 */
export interface ChatSSEMessage {
  type: 'thinking' | 'response' | 'done' | 'error';
  stage?: string;
  content?: string;
  details?: Record<string, unknown>;
  session_id?: string;
}

/** 知识库 SSE 消息 */
export interface KnowledgeSSEMessage {
  event_type: 'processing' | 'completed' | 'finish' | 'error';
  filename?: string;
  progress?: number;
  stage?: string;
  message?: string;
  document_id?: number;
}
