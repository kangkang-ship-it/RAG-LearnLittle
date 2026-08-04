# AI 对话栏文件上传（图片/视频）功能设计方案

> 版本：v1.2 ｜ 日期：2026-08-04 ｜ 状态：待实施

**v1.2 修订记录**（按 2026-08-04 代码现状核实修订，4 项）：
- 🔴 §5.3 `QueryRequest` 改写保留现有 `enable_thinking` 字段（现定义 [schemas/chat.py:18](app/schemas/chat.py#L18)，前端正在发送、后端正在消费，漏掉会静默破坏深度思考功能）；
- 🔴 §5.1 ② 修正 Range 方案：已装 Starlette 1.3.1（fastapi 0.139.2）的 `FileResponse` 原生支持 Range（206/416/byteranges），删除自写 `chat_file_stream_response()` 方案与"拖动进度条为已知限制"；
- 🟡 §4.3/§5.3 前端发送链路修正：实际为 AIChat `handleSend` 直调 `useSSE().start()`，body 为 `{session_id, message, enable_thinking}`；`sendChatSSE` 为无调用方的死代码，改动落点在 AIChat.tsx + useSSE.ts；
- 🟡 §2.2/§8.2 配额修正：`USER_STORAGE_QUOTA_MB` 仅存在于 `.env`、全代码库零消费——配额校验为**新增实现**而非复用。

**v1.1 修订记录**（按代码审查意见修订，15 项）：
- 🔴 高（3）：① §5.3 `QueryRequest` 标注为 breaking change 并补充空消息校验；② 新增 §6.6 记忆压缩管线多模态改造（MemoryCompressor / TokenCounter / 降级截断路径）；③ §5.4 明确 Redis 缓存三处补 `attachments_json`（首页热缓存回显丢附件）
- 🟡 中（7）：函数签名变更表（§5.2）；`ChatMessageResponse` 补字段（§5.4）；视频 base64 上限与"默认抽帧"策略矛盾修正（§6.3）；会话删除集成点明确在路由层（§8.5）；`vision_model` 初始化插入位置（§6.1）；Range 请求实现方案明确（§5.1）；独立校验函数 `validate_chat_attachment`（§8.1）
- 🟢 低（5）：前端上传统一原生 fetch（§4.2）；`sendChatSSE`/`endpoints.ts` 具体类型与端点（§4.3）；标题兜底代码（§5.3）；缩略图缓存配额与生命周期（§6.2）；plan_model 附件可见性（§6.4）

## 1. 需求概述

### 1.1 目标

在 AI 对话输入栏增加**图片 / 视频上传**能力，使用户可以：

1. 在输入框附近点击附件按钮，选择本地图片或视频；
2. 上传后输入框上方出现附件预览（缩略图 / 视频卡片），可删除；
3. 发送消息时附件随消息一起发出，气泡内展示缩略图；
4. 用户可以基于附件提问，例如："**根据这张图片，总结一下图表内容**"、"**分析这个视频里出现了哪些物体**"；
5. 刷新页面 / 重新进入会话后，历史消息中的附件可正常回显、预览、继续追问。

### 1.2 范围

| 范围 | 说明 |
|---|---|
| 支持类型 | 图片：png / jpg / jpeg / webp / gif；视频：mp4 / webm / mov / avi |
| 图片大小上限 | 10 MB / 张（上传后自动压缩，送模型前 ≤ ~1.5 MB） |
| 视频大小上限 | 50 MB / 个（沿用现有 `MAX_UPLOAD_SIZE_MB=50` 上限） |
| 单条消息附件数 | 图片 ≤ 6 张，且最多 1 个视频（视频 + 最多 4 张图片） |
| 不在范围 | 音频、PDF/TXT 等文档类型（沿用现有"引用笔记"能力，后续可扩展） |

### 1.3 核心用户场景

```
用户：点击 📎 → 选择 cat.png → 预览显示缩略图
用户：输入"根据这张图片，判断猫的品种" → 发送
AI：识别图片内容，流式回复"这只猫看起来是……"
```

## 2. 现状分析

### 2.1 现有对话链路

**后端**（FastAPI + LangChain Agent）：

```
POST /api/v1/chat/query (SSE)
  ├─ 1. 获取/创建会话（DatabaseSessionManager）
  ├─ 2. 保存用户消息（save_message_with_commit）
  ├─ 3. 并行：RAG 检索 + 记忆压缩（TokenBudget）
  ├─ 4. 查询复杂度分类（QueryClassifier）
  │      ├─ simple  → ReAct Agent（execute_agent）
  │      └─ complex → Plan-and-Execute（execute_plan_agent，失败降级 ReAct）
  └─ 5. SSE 流式推送 thinking / response / done
```

关键代码位置：

| 模块 | 文件 | 说明 |
|---|---|---|
| 对话路由 | [app/routers/chat.py](app/routers/chat.py) | `chat_query` 主流程 |
| 请求 Schema | [app/schemas/chat.py](app/schemas/chat.py) | `QueryRequest`（session_id/message/enable_thinking/idempotency_key） |
| 消息持久化 | [app/services/chat_service.py](app/services/chat_service.py)、[database_session_manager.py](app/services/database_session_manager.py) | `save_message_with_commit` / `add_message` |
| Agent 输入组装 | [app/ai_service/agent_runner.py](app/ai_service/agent_runner.py) | `execute_agent` 中 `HumanMessage(content=user_message)` 仅支持纯文本 |
| Plan 执行 | [app/ai_service/plan_execute_agent.py](app/ai_service/plan_execute_agent.py) | 同上，文本输入 |
| 数据模型 | [app/models/chat.py](app/models/chat.py) | `ChatMessage` 无附件字段 |
| 前端输入栏 | [front/src/pages/AIChat.tsx](front/src/pages/AIChat.tsx) | 引用笔记按钮 + 单行输入框 + 发送 |
| SSE Hook | [front/src/hooks/useSSE.ts](front/src/hooks/useSSE.ts) | 流式事件解析 |
| 消息类型 | [front/src/types/api.ts](front/src/types/api.ts) | `ChatMessage` 无附件字段 |

### 2.2 已有可复用的基础

1. **文件上传基建**：[app/utils/file_handler.py](app/utils/file_handler.py) 已有大小校验、MD5、禁止扩展名、安全文件名等工具；
2. **上传端点范式**：[app/routers/knowledge_router.py](app/routers/knowledge_router.py) 提供了 multipart 上传 + SSE 进度推送的完整模式；
3. **配额配置**：`.env` 已有 `MAX_UPLOAD_SIZE_MB=50`（已被 [knowledge_router.py](app/routers/knowledge_router.py) 消费）；`USER_STORAGE_QUOTA_MB=500` ⚠️ **仅存在于 .env、全代码库零消费**——用户附件配额校验属**新增实现**而非复用（见 §8.2）；
4. **视觉模型占位**：`main.py` 的 `BackgroundInitManager` 第 58 行已有 `self.vision_model = None` 字段，但 `_init_models()` 从未初始化它——本次设计正好补齐；
5. **轻量迁移机制**：`init_db()` 使用 `create_all`（建新表）+ `_migrate_columns()`（自动补列），新增表与新增列无需 Alembic。

### 2.3 现状缺口

| # | 缺口 | 影响 |
|---|---|---|
| 1 | `QueryRequest` 无附件字段，上传文件无法随消息传递 | 功能不可用 |
| 2 | 消息模型/消息列表无附件元数据 | 历史消息无法回显 |
| 3 | Agent 输入只支持 `content: str`，无多模态 content block | 模型看不到图片 |
| 4 | 无视觉模型配置与初始化 | 无法理解图片/视频 |
| 5 | 前端输入栏无上传入口，消息气泡无附件渲染 | 功能不可用 |
| 6 | 无附件存储目录与清理策略 | 磁盘与配额失控 |

## 3. 总体架构设计

### 3.1 架构图

```
┌────────────────────────────── 前端 (React) ──────────────────────────────┐
│  AIChat 输入栏                                                        │
│  [📎 上传] [📄引用笔记] [ 输入框                ] [发送]                │
│       │                                                                  │
│       ▼  multipart FormData (JWT)                                        │
│  ┌──────────────────────── 附件上传交互 ────────────────────────┐        │
│  │ 选择文件 → 前端校验(类型/大小) → 上传 → 返回 file_id          │        │
│  │ → 预览条(缩略图/视频卡片, 可删除) → 随消息发送                │        │
│  └──────────────────────────────────────────────────────────────┘        │
│  消息气泡: 用户消息渲染附件缩略图 / <video> 播放器（历史回显走鉴权预览）  │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ POST /api/v1/chat/query
                                   │ { message, attachment_ids: [...] }
┌──────────────────────────────────▼───────────────────────────────────────┐
│  后端 (FastAPI)                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ 上传端点: POST /chat/files          预览端点: GET /chat/files/{id}│   │
│  │   └ 校验(magic bytes/大小/配额)         └ JWT 鉴权 + 归属校验 +   │   │
│  │   └ 落盘 data/chat_files/{user_id}/      Range 支持(视频拖动)     │   │
│  │   └ 写 chat_attachments 表                                        │   │
│  ├──────────────────────────────────────────────────────────────────┤   │
│  │ chat_query 主流程（新增步骤）                                     │   │
│  │   ① 加载附件元数据 + 文件                                         │   │
│  │   ② 图片: Pillow 压缩 → base64; 视频: 抽帧/原生视频理解          │   │
│  │   ③ 组装多模态 content blocks                                    │   │
│  │   ④ 注入 ReAct / Plan-Execute 的 HumanMessage                    │   │
│  │   ⑤ 消息落库时写入 attachments_json（含缩略图/预览信息）          │   │
│  ├──────────────────────────────────────────────────────────────────┤   │
│  │ 视觉模型: init_manager.vision_model (VISION_MODEL 可配置)         │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   ▼
                     DashScope (qwen3-vl 系列视觉模型) / Ollama(可选)
```

### 3.2 核心设计决策

| 决策点 | 方案 | 理由 |
|---|---|---|
| 附件与消息的绑定 | 独立表 `chat_attachments`（权威数据）+ `chat_messages.attachments_json`（冗余元数据） | 消息列表/SSE 无需联表即可回显；权威表负责存储、配额、清理 |
| 上传与发送分离 | 先上传拿 `file_id`，发送时只传 ID | SSE 接口保持 JSON 体；断线重发无需重复上传；可做孤儿清理 |
| 图片送模型方式 | 压缩后 base64 内联（OpenAI 兼容 `image_url`） | DashScope 兼容模式标准做法，Ollama 亦可兼容 |
| 视频理解方式 | 双策略：默认抽帧（兼容所有模型），小视频（≤20MB）可选原生视频输入，失败自动降级为抽帧（详见 §6.3） | 兼容不同模型能力 |
| 预览端点鉴权 | 新增 `GET /chat/files/{id}` 走 JWT，不挂公开静态目录 | 附件属于用户隐私数据，必须鉴权 |

## 4. 前端设计

### 4.1 UI 设计

**输入栏**（与现有引用笔记按钮并列，左侧新增 📎 按钮）：

```
┌────────────────────────────────────────────────────────────────────┐
│ [📎] [📄引用笔记] │ 输入消息...                          [发送]     │
│ ┌──────────┐ ┌──────────┐ ┌────────────────────────────┐          │
│ │🖼 cat.png│ │▶ video.mp4│ │ （更多缩略图…）              │          │
│ │    ✕     │ │   ✕      │ │                            │          │
│ └──────────┘ └──────────┘ └────────────────────────────┘          │
└────────────────────────────────────────────────────────────────────┘
        ↑ 附件预览条（上传成功后出现，随消息发送后清空）
```

- 图片：显示 64×64 缩略图 + 文件名 + 删除按钮；
- 视频：显示 ▶ 图标卡片 + 文件名 + 时长（可选）；
- 超出单条消息附件上限时禁用 📎 并 toast 提示。

**消息气泡**（用户消息）：

```
┌──────────────────────────────────────┐
│ 根据这张图片判断猫的品种              │
│ ┌───────────┐  ┌───────────┐         │
│ │  cat.png  │  │  dog.png  │         │
│ │  (点击放大)│  │  (点击放大)│         │
│ └───────────┘  └───────────┘         │
└──────────────────────────────────────┘
```

- 图片：缩略图网格（最多 6 个，点击打开大图灯箱）；
- 视频：内嵌 `<video controls preload="metadata">`，可播放；
- AI 消息不受影响。

### 4.2 上传交互流程（前端状态机）

```
idle ──点击📎──▶ picking ──选择文件──▶ uploading（每个文件独立进度）
                                              │
                             成功（返回 file_id）▼
                                     preview（预览条展示，可 ✕ 删除）
                                              │
                                    点击发送 ──▶ sent（预览条清空，附件随消息发出）
```

实现要点：

1. 隐藏 `<input type="file" accept="image/*,video/*" multiple>`，点击 📎 触发；
2. 前端预校验：类型（`image/*` / `video/*`）、大小（图片 ≤10MB、视频 ≤50MB）、数量上限；
3. 上传使用**原生 `fetch` + `FormData`**（与知识库上传 [knowledge.ts](front/src/api/knowledge.ts) 模式保持一致，不走 axios）；逐文件上传进度用 `XMLHttpRequest.upload.onprogress` 封装（fetch 无上传进度事件，如需进度条则用 XHR 实现，API 层对组件透明）；失败显示错误并允许重试；
4. 上传接口返回 `{ file_id, file_type, preview_url, thumb_url? }`，加入 `attachments` state；
5. 发送时 `handleSend` 把 `attachment_ids` 拼进 SSE body；发送成功后将 `file_id` 绑定到会话（见 §5.2）；
6. 若消息在发送前删除附件：调用删除接口（后端标记为孤儿，见 §8.5）。

### 4.3 涉及的前端文件

| 文件 | 改动 |
|---|---|
| [front/src/pages/AIChat.tsx](front/src/pages/AIChat.tsx) | 新增附件 state、上传逻辑、预览条、消息附件渲染；`handleSend`（[L230-232](front/src/pages/AIChat.tsx#L230-L232)）body 由 `{ session_id, message, enable_thinking }` 改为 `{ session_id, message?, enable_thinking, attachment_ids }`（`message` 改可选、**`enable_thinking` 保留**） |
| [front/src/hooks/useSSE.ts](front/src/hooks/useSSE.ts) | **真实发送链路的改动落点**（AIChat 经 `useSSE().start()` 直接 fetch，不经 `sendChatSSE`）：请求体类型支持 `message?` + `attachment_ids` |
| [front/src/types/api.ts](front/src/types/api.ts) | `ChatMessage` 增加 `attachments?: AttachmentMeta[]`；新增 `AttachmentMeta` / `QueryRequest.attachment_ids`；`QueryRequest.message` 改可选 |
| [front/src/api/chat.ts](front/src/api/chat.ts) | ⚠️ `sendChatSSE`（[L22-25](front/src/api/chat.ts#L22-L25)）为**无调用方的死代码**，本次不依赖它，如需保留需同步改类型，否则删除；新增 `uploadChatFile(file): Promise<UploadResponse>`（fetch + FormData） |
| [front/src/api/endpoints.ts](front/src/api/endpoints.ts) | `chat` 对象新增：`fileUpload: ${API_PREFIX}/chat/files`、`fileDetail: (fileId: string) => ${API_PREFIX}/chat/files/${fileId}` |
| [front/src/components/chat/AttachmentBar.tsx](front/src/components/chat/AttachmentBar.tsx) | **新增**：预览条组件 |
| [front/src/components/chat/AttachmentViewer.tsx](front/src/components/chat/AttachmentViewer.tsx) | **新增**：气泡内附件渲染（缩略图网格 / 视频播放 / 灯箱） |
| [front/src/i18n/locales/zh-CN.ts](front/src/i18n/locales/zh-CN.ts)（及 en-US） | 上传相关文案 |

## 5. 后端设计

### 5.1 新端点

统一挂在 `chat.router` 下，前缀 `/api/v1`。

**① POST /api/v1/chat/files — 上传附件**

```
Request:  multipart/form-data
  - file: UploadFile（必填）

Response:
{
  "code": 0,
  "data": {
    "file_id": "3f2a...",          // 32 位 uuid4 hex
    "file_type": "image" | "video",
    "mime_type": "image/png",
    "original_name": "cat.png",
    "file_size": 234567,
    "width": 1200, "height": 800,  // 图片才有
    "duration_sec": null,          // 视频时长（可选，抽帧时返回）
    "created_at": "..."
  }
}
```

处理流程：

```
接收文件 → 大小校验（≤ MAX_UPLOAD_SIZE_MB）→ 类型校验（magic bytes + 扩展名）
→ 用户配额校验（USER_STORAGE_QUOTA_MB，含已有附件）
→ 落盘 data/chat_files/{user_id}/{file_id}.{ext}
→ 写入 chat_attachments（session_id/message_id 为空 → 孤儿状态）
→ 返回 file_id
```

限制：`rate_limit(endpoint_limit=...)`；视频上传可放宽并发限制，避免大文件占满连接。

**② GET /api/v1/chat/files/{file_id} — 预览/下载（鉴权）**

```
Request:  Header Authorization: Bearer <JWT>
Response: 文件流（Content-Type + Content-Length + Cache-Control）
```

- 校验附件 `user_id == 当前用户`，否则 404；
- **HTTP Range 支持（视频拖动进度条必需）**：直接用 Starlette `FileResponse(path)`——项目已装 **Starlette 1.3.1**（fastapi 0.139.2），其 `FileResponse` **原生支持 Range**（单段 206 + `Content-Range`、多段 byteranges、416、If-Range/ETag，见 .venv starlette/responses.py L361-379），**无需自写** `chat_file_stream_response()`；实现时先做 JWT 归属校验，再构造 FileResponse 返回；
- 图片可附带 `?size=thumb` 参数返回后端生成的缩略图（可选，避免前端加载原图）。

**③ DELETE /api/v1/chat/files/{file_id} — 删除附件（可选实现）**

- 仅允许删除**未绑定消息**（message_id 为空）的附件；
- 已绑定的附件随会话删除级联清理（见 §8.5）。

### 5.2 附件与消息的绑定

**上传时**（未绑定）：`session_id = NULL, message_id = NULL` → 孤儿附件，超时（建议 24h）清理。

**发送时**（chat_query 主流程新增步骤）：

```
① 校验 attachment_ids 归属：SELECT * FROM chat_attachments WHERE file_id IN (...) AND user_id = ?
② 将 session_id 回填到附件行（绑定会话）
③ 组装多模态输入（见 §6）
④ 保存用户消息时，把附件元数据写入 chat_messages.attachments_json：
   [{"file_id","file_type","original_name","file_size","mime_type","width","height"}]
⑤ 保存 assistant 回复成功后，把 message_id 回填到附件行（绑定消息）
```

消息列表接口（`GET /chat/{session_id}/messages`）直接读取 `attachments_json` 即可回显，无需联表；`chat_attachments` 是存储层的权威数据。

**消息持久化函数签名变更**（调用链三处同步改，含 `attachments_json` 透传）：

```python
# ① 调用方 [chat.py:74-76](app/routers/chat.py#L74-L76)
await chat_service.save_message_with_commit(
    session_id, user_id, "user",
    data.message or "[图片]",                  # 空文本+附件 → 占位内容
    data.idempotency_key,
    attachments_json=attachment_meta_json,     # 新增参数
)

# ② [chat_service.py:63-65](app/services/chat_service.py#L63-L65)
async def save_message_with_commit(
    self, session_id: str, user_id: str, role: str, content: str,
    idempotency_key: Optional[str] = None,
    attachments_json: Optional[str] = None,    # 新增：JSON 字符串或 None
) -> None: ...

# ③ [database_session_manager.py:174-177](app/services/database_session_manager.py#L174-L177)
async def add_message(
    self, db: AsyncSession, session_id: str, user_id: str,
    role: str, content: str, idempotency_key: Optional[str] = None,
    attachments_json: Optional[str] = None,    # 新增
) -> ChatMessage:
    # 构造 ChatMessage 时：attachments_json=attachments_json（该处当前为 L211-217 的构造逻辑）
```

### 5.3 QueryRequest 扩展

> ⚠️ **Breaking change**：现定义 [schemas/chat.py:16](app/schemas/chat.py#L16) 为 `message: str = Field(..., min_length=1, max_length=10000)`——`...` 必填且 `min_length=1` 禁止空串。改为可选后必须**同时去掉 `...`（改为默认值 `""`）并移除 `min_length=1`**，两者缺一不可；否则空文本请求会被 Pydantic 直接 422 拦截，无法到达业务层。

```python
class QueryRequest(BaseModel):
    session_id: Optional[str] = None
    message: str = Field("", max_length=10000)   # 允许空文本（仅发附件时）
    enable_thinking: bool = Field(False, ...)    # ⚠️ 必须保留现有字段（schemas/chat.py:18）
    idempotency_key: Optional[str] = None
    attachment_ids: List[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _require_message_or_attachment(self):
        # 空消息 + 无附件 → 拒绝（替代原 min_length=1 的兜底，防止纯空提交）
        if not self.message.strip() and not self.attachment_ids:
            raise ValueError("message 为空时必须附带 attachment_ids")
        return self
```

> ⚠️ **v1.2 修正**：原方案改写仅列 4 个字段，会**静默删掉现有 `enable_thinking`**（[chat.py:95-96](app/routers/chat.py#L95-L96) 依赖它切换 `chat_model_thinking`），导致深度思考功能失效。完整改写 = 现有 4 字段 + `enable_thinking` + 新增 `attachment_ids`，**不得用新类替换式覆盖现有字段**。

边界处理：

- `message` 为空但 `attachment_ids` 非空 → 视为"分析/描述附件"，保存消息时内容写 `[图片]` / `[视频]` 占位；
- 前端 TS 类型 `message: string` 需同步改为 `message?: string`（否则 TS 编译报错），**真实改动落点在 [AIChat.tsx](front/src/pages/AIChat.tsx) `handleSend` 的 body 构造与 [useSSE.ts](front/src/hooks/useSSE.ts) 的请求体类型**——AIChat 经 `useSSE().start()` 直接 fetch，`sendChatSSE` 是无调用方的死代码、无需改动（见 §4.3）；
- 会话标题生成兜底（[chat_service.py:129-130](app/services/chat_service.py#L129-L130) 现为 `user_message[:20].strip()`，空消息会得到空标题）：

```python
# generate_and_update_title 签名新增 attachment_names 参数
async def generate_and_update_title(
    self, session_id: str, user_message: str, chat_model=None,
    attachment_names: Optional[List[str]] = None,
) -> None:
    ...
    # 原兜底逻辑替换为：
    if not user_message.strip():
        title = f"附件分析（{', '.join(attachment_names[:2])}）" if attachment_names else "新对话"
    else:
        title = user_message[:20].strip()
```

### 5.4 涉及的后端文件

| 文件 | 改动 |
|---|---|
| [app/models/chat.py](app/models/chat.py) | 新增 `ChatAttachment` 模型；`ChatMessage` 增加 `attachments_json` 列（`_migrate_columns` 自动补列） |
| [app/routers/chat.py](app/routers/chat.py) | 新增 3 个附件端点；`chat_query` 增加附件加载/绑定逻辑 |
| [app/schemas/chat.py](app/schemas/chat.py) | `QueryRequest` 扩展（breaking change，§5.3）；**`ChatMessageResponse` 新增 `attachments: Optional[List[AttachmentMeta]]`**（现定义 [schemas/chat.py:27-36](app/schemas/chat.py#L27-L36) 只有 6 个字段，缺了它前端即使加类型也无法渲染）；新增 `AttachmentMeta`/`UploadResponse` Schema |
| [app/services/chat_attachment_service.py](app/services/chat_attachment_service.py) | **新增**：上传/校验/绑定/清理/读取服务 |
| [app/services/chat_service.py](app/services/chat_service.py) | `save_message_with_commit` 新增 `attachments_json` 参数（签名见 §5.2）；`generate_and_update_title` 新增 `attachment_names` 空消息兜底（§5.3） |
| [app/services/database_session_manager.py](app/services/database_session_manager.py) | `add_message` 新增 `attachments_json` 参数；**Redis 缓存三处补字段**：`_push_to_redis_cache`（[L368-373](app/services/database_session_manager.py#L368-L373) 仅序列化 4 个字段）、`_rebuild_redis_cache`、`get_messages` 的 Redis 反序列化分支（[L268-276](app/services/database_session_manager.py#L268-L276)）——三处都要带 `attachments_json`，否则首页热缓存回显丢附件、只有翻页走 MySQL 才看得到；`get_all_messages` 透出附件字段 |
| [app/services/memory_compressor.py](app/services/memory_compressor.py) | `build_context` 多模态支持；`generate_incremental_summary` 附件占位（§6.6） |
| [app/services/token_budget.py](app/services/token_budget.py) | `TokenCounter` 新增 `count_image()`，`count_messages` 支持多模态 content 列表（§6.5/§6.6） |
| [app/utils/file_handler.py](app/utils/file_handler.py) | 新增独立 `validate_chat_attachment()`（magic bytes + 扩展名 + 大小，**不动**现有 `validate_upload_file`，避免影响知识库上传）+ 用户附件配额统计函数 |
| [app/utils/factory.py](app/utils/factory.py) | 新增 `create_vision_model()`（§6.1） |
| [main.py](main.py) | `_init_models()` 初始化 `self.vision_model`；静态挂载目录（若需要） |
| [app/ai_service/agent_runner.py](app/ai_service/agent_runner.py) | `execute_agent` 支持多模态 content blocks 参数 |
| [app/ai_service/plan_execute_agent.py](app/ai_service/plan_execute_agent.py) | 同上 |
| [app/core/rate_limit.py](app/core/rate_limit.py) | 视需要增加上传端点限流配置 |

## 6. 多模态模型接入（核心）

### 6.1 视觉模型选型与配置

**决策**：新增独立的视觉模型 `VISION_MODEL`，与聊天主模型分离。

理由：

1. 当前主模型 `qwen3.8-max`（`DASHSCOPE_CHAT_MODEL`）为文本模型，不保证多模态；
2. 视觉模型按图计费、上下文按分辨率计费，与文本模型解耦便于成本控制；
3. 复用现有 `ChatOpenAI` + DashScope 兼容端点模式，改动最小。

```python
# app/utils/factory.py 新增
def create_vision_model():
    # dashscope: ChatOpenAI(model=VISION_MODEL, base_url=DASHSCOPE_BASE_URL, ...)
    # ollama:   ChatOllama(model=OLLAMA_VISION_MODEL)   # 如 qwen3-vl / llava
```

```dotenv
# .env 新增
# 视觉模型（图片/视频理解），dashscope 建议 qwen-vl-max 或 qwen3-vl 系列
VISION_MODEL=qwen-vl-max
# Ollama 本地视觉模型（MODEL_PROVIDER=ollama 时生效）
OLLAMA_VISION_MODEL=
```

`main.py` 的 `_init_models()` 补上（**插入位置：紧跟 `self.embed_model = create_embed_model()` 之后、classifier_model 之前**；同时把方法 docstring 从"初始化 AI 模型（Chat + Embedding + Classifier + Plan）"更新为"Chat + Embedding + Vision + Classifier + Plan"）：

```python
try:
    self.vision_model = create_vision_model()
except Exception as e:
    logger.warning(f"视觉模型初始化失败，图片/视频理解不可用: {e}")
    self.vision_model = None   # 降级：附件仍可上传/展示，但 AI 无法理解
```

> 视觉模型未就绪时优雅降级：上传与展示照常，发送带附件的消息时 SSE 提示"视觉模型未就绪，当前只能基于文字回复"。

### 6.2 图片处理管线（后端，发送前）

```
读取文件 (Pillow) → 校验/转码 → 压缩 → base64 → 组装 content block
```

具体规则：

1. **格式归一**：png/jpg/webp 保留；gif 取首帧转 jpg；HEIC 等不支持格式直接拒绝；
2. **尺寸上限**：长边 > 1568px 按比例缩放（DashScope VL 系列推荐上限，避免按分辨率计费过贵）；
3. **压缩**：质量 85 的 JPEG，目标 ≤ 1.5 MB（超出继续降质）；
4. **结果缓存**：压缩结果以 `{file_id}_thumb.jpg` 落盘缓存（仅图片），后续追问复用，避免重复压缩；缓存文件**计入用户配额**（按压缩后实际字节统计，§8.2），生命周期与附件绑定：附件删除/会话清理时一并删除（缓存可再生，删除无风险）；
5. **base64 组装**（OpenAI 兼容格式，LangChain `HumanMessage` 原生支持）：

```python
HumanMessage(content=[
    {"type": "text", "text": user_message},
    {"type": "image_url", "image_url": {
        "url": f"data:image/jpeg;base64,{b64}"}},
    # 多张图片重复该 block，最多 6 张
])
```

### 6.3 视频理解策略（**默认抽帧** + 小视频可选原生）

> **策略修正（v1.1）**：为避免文档与配置矛盾，明确 **方案 B（抽帧）为默认与首选**（与 §9 `VIDEO_MODE=frames` 一致）；方案 A（原生视频）仅在视频 **≤ 20MB** 且模型支持时启用。

**方案 A：原生视频输入（仅 ≤ 20MB 的小视频，可选启用）**

- DashScope 兼容模式：qwen3-vl / qwen2.5-vl 系列支持 `video_url` 内容块：

```python
{"type": "video_url", "video_url": {
    "url": f"data:video/mp4;base64,{b64}"}}   # 或可访问的 URL
```

- **风险量化**：50MB 视频 base64 后 ≈ 67MB，编码是同步 CPU 操作（需 `asyncio.to_thread`），且可能触发 DashScope 请求体限制/超时——因此原生模式设硬上限 **≤ 20MB**（base64 ≈ 27MB），超过一律走抽帧；
- 优点：模型直接理解时序信息；缺点：仅部分模型支持、仅小视频可用。

**方案 B：视频抽帧（默认，兼容所有视觉模型与任意大小）**

- 用 **imageio-ffmpeg**（纯 pip、离线友好，与项目离线部署策略一致）均匀抽取 N 帧（默认 8 帧：首帧、尾帧 + 中间均匀采样）；
- 每帧按 §6.2 压缩为 JPEG（单帧 ≤ 1.5MB），作为多张图片传入；
- 系统提示词注明"以下图片序列来自同一视频，按时间顺序排列"；
- 优点：任意视觉模型可用、token 可控；缺点：丢失音频与部分动态细节。

**降级策略**：

```
启动时探测 vision_model 能力（模型名含 vl / 配置项 VIDEO_MODE=native|frames）
→ 默认 frames；native 模式仅当视频 ≤ 20MB 且模型支持视频输入时尝试
→ native 调用失败（4xx 不支持视频）→ 自动切换 frames 重试
→ 前端 SSE 推送 thinking 事件 "正在解析视频（抽帧）..." 让用户感知等待
```

### 6.4 与 Agent 链路的集成点

两条执行链路均需透传多模态内容：

| 链路 | 集成点 | 改动 |
|---|---|---|
| ReAct | [app/ai_service/agent_runner.py](app/ai_service/agent_runner.py) `execute_agent()` | 新增参数 `attachment_content: Optional[List[dict]] = None`，构造 `HumanMessage` 时若存在则用 `content=[{type:text}, ...图片块]` 替代纯文本 |
| Plan-Execute | [app/ai_service/plan_execute_agent.py](app/ai_service/plan_execute_agent.py) `execute_plan_agent()` | 执行阶段同 ReAct；**计划生成阶段（plan_model）无多模态能力，需注入附件摘要**：`_generate_plan`（[plan_execute_agent.py:50](app/ai_service/plan_execute_agent.py#L50) 接收纯文本 `user_message`）的 prompt 中追加"用户附带 N 张图片/视频：cat.png、video.mp4"，使 plan_model 感知附件存在、能制定正确计划；`_execute_step`（[plan_execute_agent.py:193](app/ai_service/plan_execute_agent.py#L193)）同样在步骤消息中保留附件摘要 |
| 历史回放 | [app/routers/chat.py](app/routers/chat.py) `_run_memory_compression()` | 从 `get_all_messages` 读 attachments_json，把**最近 1~2 条用户消息的附件**（受 Token 预算约束）以图片块形式拼进压缩后的上下文，支持"上一张图里……"的追问（完整改造见 §6.6） |

**混合上下文兼容性**：改造后 `compressed_messages` 是纯文本与多模态 `HumanMessage` 的混合列表，LangChain `ChatOpenAI`（OpenAI 兼容格式）原生支持混排，但需在 P2 单测覆盖验证；若某 provider 不支持，则降级为该条消息回退为纯文本 + `[图片]` 占位（降级开关配置化）。

**注意**：`compressed_messages` 中的历史消息目前是 `HumanMessage(content=str)`；改造后对带附件的历史消息使用多模态 content。`TokenBudget` 需为图片新增估算（见 §6.5）。

### 6.5 Token 预算与上下文管理

图片 token 估算（DashScope VL 系列按分辨率计价，简化公式）：

| 长边分辨率 | 估算 token/张 |
|---|---|
| ≤ 1024px | ~1000 |
| 1024 ~ 1568px | ~2000 |

处理策略：

1. `TokenBudget` 新增 `image_tokens_per_msg`（默认 3000）与 `max_history_images`（默认 4）；
2. 当前消息附件图片 ≤ 6 张 × 2000 ≈ 1.2w token，**优先保证当前消息**，预算从"当前输入预留"中扣除；
3. 历史回放的图片在 RAG 上下文之后、摘要之前分配，超预算时只保留最近 1 张或丢弃并记录日志；
4. 视频抽帧 8 张按图片同规则估算；原生视频输入按模型文档估算（或固定预留 1.5w token）。

### 6.6 记忆压缩管线多模态改造（与主链路同级的改动）

**问题**：现有压缩管线完全基于纯文本——`MemoryCompressor.build_context` 逐条 `TokenCounter.count(content)` 并构造 `HumanMessage(content=str)`；[chat.py:197-201](app/routers/chat.py#L197-L201) 只取 `role/content` 两字段；降级截断路径（[chat.py:246-257](app/routers/chat.py#L246-L257)）同样纯文本。若不改造，历史消息的附件在压缩后全部丢失，"上一张图里……"的追问无从谈起。

**改造点清单**：

| 位置 | 现状 | 改动 |
|---|---|---|
| [chat.py](app/routers/chat.py) `_run_memory_compression` | `all_messages = [{"role","content"}]` | `get_all_messages` 返回 ORM 对象后改读 `attachments_json`，构造 dict 时附带 `attachments` 元数据 |
| [memory_compressor.py](app/services/memory_compressor.py) `build_context` | 纯文本计数 + `HumanMessage(content=content)`（L102-117） | 消息含附件时：按 §6.5 公式将图片 token 计入 `msg_tokens`（配额判断同步生效）；构造 `HumanMessage(content=[text_block, *image_blocks])`；超过 `max_history_images`（默认 4）时只保留最近 N 张，其余以 `[图片×N]` 文本占位 |
| [token_budget.py](app/services/token_budget.py) `TokenCounter` | `count()` 仅文本编码；`count_messages` 对 `content` 按 str 处理（L56-65） | 新增 `count_image(width, height)`；`count_messages` 对 content 为 list（多模态）的消息逐块累加（text 走 `count`，image 走 `count_image`） |
| [chat.py](app/routers/chat.py) 降级截断路径（L246-257） | `get_recent_messages` 纯文本 | 同步读取附件元数据，构造多模态消息 |
| [memory_compressor.py](app/services/memory_compressor.py) `generate_incremental_summary` | 摘要 prompt 纯文本 | 附件消息在摘要 prompt 中描述为 `[图片: cat.png]`（不展开图片——摘要只关心文字语义，避免多模态进摘要调用） |

**兼容性验证**：`compressed_messages` 将变成纯文本与多模态 `HumanMessage` 的混合列表；LangChain `ChatOpenAI` 支持混排，P2 需单测覆盖"带附件历史 + 纯文本历史"组合，失败则按 §6.4 的降级开关回退。

**v1 裁剪选项**：若首版只想支持"当前消息附件"，可将历史回放降级为"仅保留最近 1 条用户消息的附件"，文档记录为已知限制，P3 再完整实现。

## 7. 数据库设计

新增表（`create_all` 自动建表）：

```sql
CREATE TABLE chat_attachments (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    file_id       CHAR(32) NOT NULL UNIQUE,        -- uuid4 hex
    user_id       VARCHAR(36) NOT NULL,            -- 归属用户
    session_id    VARCHAR(36) NULL,                -- 发送后回填（绑定会话）
    message_id    BIGINT NULL,                     -- 回复成功后回填（绑定消息）
    file_type     VARCHAR(10) NOT NULL,            -- image / video
    mime_type     VARCHAR(50) NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    stored_path   VARCHAR(500) NOT NULL,           -- data/chat_files/{user_id}/{file_id}.{ext}
    file_size     BIGINT NOT NULL,                 -- 原始字节数
    width         INT NULL,                        -- 图片宽 / 视频首帧宽
    height        INT NULL,
    duration_sec  FLOAT NULL,                      -- 视频时长（可选）
    md5           CHAR(32) NOT NULL,               -- 去重 + 完整性
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_time (user_id, created_at),
    INDEX idx_session (session_id),
    INDEX idx_message (message_id)
);
```

修改表（`_migrate_columns` 自动补列）：

```sql
ALTER TABLE chat_messages
    ADD COLUMN attachments_json JSON NULL;   -- 冗余附件元数据，供历史回显
```

SQLAlchemy 模型位于 [app/models/chat.py](app/models/chat.py)，新增：

```python
class ChatAttachment(Base):
    __tablename__ = "chat_attachments"
    # 字段见上表 DDL，关系：多对一 → User（会话删除时不依赖外键级联，见 §8.5）
```

## 8. 安全设计

### 8.1 文件类型校验（纵深防御）

1. **扩展名白名单**：图片 png/jpg/jpeg/webp/gif，视频 mp4/webm/mov/avi；
2. **magic bytes 校验**（必须）：用文件头签名验证真实类型，杜绝伪装扩展名（如改名 `.mp4` 的 exe）；
3. **双重校验**：扩展名 + magic bytes 一致才接受；
4. 禁止扩展名列表（`FORBIDDEN_EXTENSIONS`）继续生效；
5. **独立校验函数**：新增 `validate_chat_attachment(filename, file_size, max_size_mb) -> AttachmentInfo`，与现有 [validate_upload_file](app/utils/file_handler.py#L74)（硬编码 PDF/MD/TXT 白名单）和 `validate_avatar_file` 并列，**不复用、不修改**现有函数——避免改动影响知识库上传路径。

### 8.2 大小与配额

- 单文件：图片 ≤ 10 MB、视频 ≤ 50 MB（沿用 `MAX_UPLOAD_SIZE_MB`）；
- 用户配额：`USER_STORAGE_QUOTA_MB=500`（⚠️ 仅存在于 .env、现代码零消费），**配额校验为新增实现**：上传前 `SELECT SUM(file_size) FROM chat_attachments WHERE user_id=?` 统计该用户已用字节（含本次），超限返回 413 及明确错误提示；
- 请求体限制：FastAPI/中间件配置 `Content-Length` 预检，超限直接 413。

### 8.3 访问控制

- 预览/下载端点必须 JWT 鉴权 + `user_id` 归属校验（防越权访问他人附件）；
- **不**将附件目录挂到公开静态路径（现有 avatars 用 StaticFiles 是历史行为，附件不沿用）；
- SSE 鉴权沿用现有 `sse-token` 机制。

### 8.4 内容安全（可选增强）

- 对接 DashScope 内容安全检测（`ContentModeration`）或图片审核接口，发现违规立即删除并记录日志；
- 本期可先不做，预留接口位。

### 8.5 生命周期与清理策略

| 场景 | 策略 |
|---|---|
| 上传后未发送 | 孤儿附件，`session_id IS NULL` 且 `created_at < now()-24h` → 定时任务（复用现有 asyncio 任务模式）删除文件 + 行 |
| 会话删除 | **集成点：路由层**（`DELETE /chat/sessions/{session_id}`，[chat.py](app/routers/chat.py#L573) 删除端点处理函数）：① 查附件列表 → ② 调现有 `delete_session`（DB 删会话/消息 + 清 Redis）→ ③ 删文件 + 删附件行。`DatabaseSessionManager.delete_session`（[database_session_manager.py:149](app/services/database_session_manager.py#L149)）保持纯 DB 职责、不注入文件系统逻辑 |
| 用户注销 | 按 `user_id` 批量清理（预留，当前无注销功能） |
| 发送失败/附件被删除 | 前端删除按钮调 DELETE 端点（仅未绑定可删）；已绑定的不可单独删 |

## 9. 配置项（.env 新增）

```dotenv
# ========== Chat Attachment ==========
# 视觉模型（图片/视频理解）
VISION_MODEL=qwen3.7-max-2026-06-08
OLLAMA_VISION_MODEL=
# 视频理解模式: native=原生视频输入 / frames=抽帧（默认，兼容性最好）
VIDEO_MODE=frames
# 视频抽帧数量
VIDEO_FRAME_COUNT=8
# 图片压缩参数
CHAT_IMAGE_MAX_LONG_EDGE=1568
CHAT_IMAGE_QUALITY=85
# 附件限制
CHAT_IMAGE_MAX_MB=10
CHAT_VIDEO_MAX_MB=50
CHAT_MAX_IMAGES_PER_MSG=6
CHAT_MAX_VIDEOS_PER_MSG=1
# 孤儿附件清理时间（小时）
CHAT_ATTACHMENT_ORPHAN_TTL_HOURS=24
```

## 10. 实施计划

| 阶段 | 内容 | 交付物 | 验证方式 |
|---|---|---|---|
| **P1 存储与端点** | `ChatAttachment` 表 + `attachments_json` 列；上传/预览/删除端点；配额与 magic bytes 校验；孤儿清理任务 | 后端 API | curl 上传图片/视频；越权访问返回 404；超配额报错 |
| **P2 模型接入** | `create_vision_model` + `_init_models`（插入位置见 §6.1）；图片压缩管线；视频抽帧（imageio-ffmpeg）；`execute_agent`/`execute_plan_agent` 多模态注入（含 plan_model 附件摘要，§6.4）；**记忆压缩管线多模态改造（§6.6）**；**Redis 缓存三处补 `attachments_json`** | 后端能力 | 单测：带图发送"描述这张图"；视频抽帧结果；token 预算日志；**带附件消息后刷新页面首页回显**；混合多模态/纯文本上下文兼容性 |
| **P3 前端 UI** | 📎 上传入口 + 预览条 + 进度；消息气泡附件渲染（缩略图/视频/灯箱）；历史回显；i18n | 前端功能 | 手测完整流程（上传→追问→刷新→继续追问） |
| **P4 加固与测试** | 并发上传、断网重试、孤儿清理、会话删除级联、视觉模型降级、SSE 取消；性能（压缩耗时）与日志 | 稳定版 | pytest（后端）+ 手测清单（前端） |

## 11. 风险与注意事项

| 风险 | 等级 | 说明与对策 |
|---|---|---|
| 视觉模型不可用/未开通 | 高 | 已做优雅降级（§6.1）；建议在 P2 开始前确认账号可用的 VL 模型（`qwen-vl-max` 或 qwen3-vl 系列） |
| 视频理解成本高 | 中 | 默认抽帧模式 token 可控（8 帧 ≈ 1.6w）；原生视频模式需评估按分钟计费 |
| 大文件上传占用连接 | 中 | 上传端点独立限流；视频上传与 SSE 并发互不影响（上传走普通 HTTP） |
| 附件泄漏 | 高 | 鉴权预览 + magic bytes + 归属校验（§8）；不挂公开静态目录 |
| 历史消息多模态回放撑爆上下文 | 中 | TokenBudget 增加图片估算与上限（§6.5），超限只保留最近 1 张 |
| Ollama 本地模式 | 低 | 本地 VL 模型（qwen3-vl/llava）能力弱、抽帧为唯一路径；文档注明推荐 DashScope |
| 磁盘增长 | 中 | 配额 + 孤儿清理 + 会话级联删除，缺一不可 |

## 12. 验收标准（摘要）

1. 图片（png/jpg/webp）上传 → 预览 → 发送 → AI 能正确描述图片内容（流式回复）；
2. 视频（mp4）上传 → 发送 → AI 能描述视频主要内容（基于抽帧）；
3. 刷新/重进会话后历史消息附件正常回显并可再次追问；
4. 未登录/越权访问预览接口返回 401/404；
5. 超大小、伪装类型、超数量均被拒绝且有明确错误提示；
6. 删除会话后附件文件与记录全部清理，无残留。
