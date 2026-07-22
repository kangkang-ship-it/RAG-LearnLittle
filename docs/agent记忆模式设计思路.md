# Agent 上下文记忆架构设计

## 概述

整个 Agent 的上下文记忆架构由 **四条记忆管线** 组成，按请求生命周期串联起来：

```
请求入口 → 路由决策 → RAG前置检索 → Agent执行 → 记忆持久化
```

核心是"**对话记忆（chat_history）+ 知识记忆（RAG上下文）**"的双通道上下文模型，以 MySQL 全量持久化 + LangChain PromptTemplate 拼装为骨架。

---

## 一、记忆的存储层：MySQL 关系型持久化

### 数据模型

实现文件：[`backend/app/services/database_session_manager.py`](../backend/app/services/database_session_manager.py)、[`backend/app/models/chat_history.py`](../backend/app/models/chat_history.py)

```
┌──────────────────────────────────────────┐
│  chat_sessions 表                        │
│  ──────────────                          │
│  id (String, PK)    ← 前端传入 / 服务端生成 │
│  user_id (String)   ← JWT 解码获得         │
│  title (String)     ← 首条消息截取前30字     │
│  metadata_ (JSON)                        │
│  created_at / updated_at (DateTime)      │
│                                          │
│  1 : N  (cascade delete)                 │
│  ┌──────────────────────────────────────┐│
│  │ chat_messages 表                     ││
│  │ ──────────────                      ││
│  │ id (Integer, PK, 自增)              ││
│  │ session_id (FK → chat_sessions.id)  ││
│  │ role: "user" | "assistant"          ││
│  │ content (Text)                      ││
│  │ metadata_ (JSON)                    ││
│  │ created_at (DateTime)               ││
│  └──────────────────────────────────────┘│
└──────────────────────────────────────────┘
```

### 关键设计决策

| 决策 | 说明 |
|------|------|
| **不做物理外键约束**到用户微服务 | 只存 `user_id` 字符串做逻辑隔离，服务间解耦 |
| **权限校验** | 每次加载历史时验证 `session.user_id == current_user_id`，不匹配则抛 `403` |
| **级联删除** | 删除 Session 时自动删除其下所有 Message |
| **会话标题自动生成** | 首条消息前 30 字符作为标题，"新的对话" → 自动替换 |
| **历史上限** | **无长度截断，全量保留** |

### 为什么用 MySQL 而不是 Redis？

- Redis 在项目中仅用于缓存（默认 3600s 过期），不适合持久化对话历史
- MySQL 提供持久化保证和关系查询能力（按用户查会话列表、按时间排序等）
- `AsyncSessionLocal` 是 SQLAlchemy 异步 Session，每次读写都 `async with` 获取新连接

---

## 二、记忆的加载：每次请求完整加载全量历史

### 加载流程


```python
# 1. 从数据库加载该会话的全部历史
history = await sm.session_manager.get_history(session_id, user_id)

# 2. 转换为 LangChain 消息格式
chat_history: list[BaseMessage] = []
for user_msg, assistant_msg in history:
    chat_history.append(HumanMessage(content=user_msg))
    chat_history.append(AIMessage(content=assistant_msg))
```

### 历史数据转换规则

```python
i = 0
while i < len(messages):
    if messages[i].role == "user" and i+1 < len(messages) and messages[i+1].role == "assistant":
        history.append((messages[i].content, messages[i+1].content))
        i += 2
    else:
        i += 1  # 不成对的消息被跳过
```

**⚠️ 注意：全量加载，无滑动窗口截断。** 对话越长，prompt token 持续膨胀。当前没有：
- 摘要压缩（summarization）
- 滑动窗口（sliding window）
- Token 计数保护

---

## 三、记忆注入 LLM 的方式：LangChain PromptTemplate 拼装

### 模板结构


```python
ChatPromptTemplate.from_messages([
    ("system", "{system_prompt}"),                             # ①
    MessagesPlaceholder(variable_name="chat_history"),         # ②
    ("human", "{input}"),                                      # ③
    MessagesPlaceholder(variable_name="agent_scratchpad")      # ④
])
```

### 最终发给 LLM 的消息序列

```
[system]     → ① 主提示词 (main_prompt.txt) 或 RAG 上下文提示词
[human]      ┐
[ai]         │ ② 全量历史（按时间升序）
[human]      │   每轮 = HumanMessage + AIMessage 成对
[ai]         ┘
[human]      → ③ 当前用户问题
[ai]         ┐
[tool]       │ ④ agent_scratchpad（LangChain 运行时自动填充）
[ai]         │   工具调用的思考→调用→结果→思考→...→最终回复
[tool]       │   最多 5 轮迭代 (max_iterations=5)
[ai]         ┘
```

四个占位符的职责：

| 占位符 | 内容来源 | 生命周期 |
|--------|---------|---------|
| `{system_prompt}` | `main_prompt.txt` 或 RAG 上下文拼接文本 | 单次请求 |
| `{chat_history}` | MySQL `chat_messages` 表全量加载 | 跨请求持久化 |
| `{input}` | 当前用户 query | 单次请求 |
| `{agent_scratchpad}` | LangChain AgentExecutor 运行时管理 | Agent 单次执行 |

---

## 四、RAG 上下文注入：路由层前置管线

这是架构中的**第二条记忆通道**——将外部知识库内容注入 system prompt。

### 完整流程

```
用户查询
   │
   ▼
┌──────────────────────────────────────────┐
│  路由决策 compute_route_score(query, uid) │
│  对用户知识库做向量相似度打分              │
│                                          │
│  score > 0.5  → 走 RAG 前置管线          │
│  score ≤ 0.5  → 跳过，仅用对话记忆        │
└──────────────┬───────────────────────────┘
               │
    ┌──────────▼──────────┐
    │ score > 0.5: RAG管线 │
    │                      │
    │ ① HyDE 生成假设文档   │  ← 用 LLM 把短查询"扩写"成伪文档
    │ ② 混合检索            │  ← 向量检索 + BM25 关键词检索，动态权重
    │ ③ 双源检索            │  ← 知识库 (ChromaDB) + 笔记库 (ChromaDB)
    │ ④ LLM 重排序          │  ← 对候选文档做语义重排，取 Top-3
    │                      │
    │ → rag_context        │
    └──────────┬───────────┘
               │
    ┌──────────▼───────────────────────────┐
    │  动态拼接 system_prompt               │
    │                                       │
    │  "你是用户的智能助手。                  │
    │   以下是与用户问题相关的参考资料：        │
    │   {rag_context}                       │
    │   请基于以上资料回答用户的问题。          │
    │   如果资料中没有相关信息，请如实告知。"    │
    └──────────┬───────────────────────────┘
               │
               ▼
         Agent 执行
```

### 两条记忆通道对比

| 维度 | 对话记忆 (chat_history) | 知识记忆 (RAG context) |
|------|------------------------|----------------------|
| **注入位置** | `chat_history` 占位符 → HumanMessage/AIMessage | `system_prompt` 文本拼接 → SystemMessage |
| **存储** | MySQL 持久化 | 按需从 ChromaDB 实时检索 |
| **生命周期** | 跨会话持久 | 单次请求 |
| **控制方式** | 前端传 session_id | 后端路由打分自动决策 |
| **内容** | 人与助手的对话记录 | 知识库/笔记库中的文档片段 |

---

## 五、记忆的写入：响应完成后异步持久化

### 写入时机


```
Agent 生成完整回复
       │
       ▼
await session_manager.add_message(session_id, user_id, query, response)
       │
       ├── 若会话不存在 → 自动创建 ChatSession
       ├── 若标题为"新的对话" → 自动替换为首条消息前 30 字
       ├── 写入 ChatMessage(role="user", content=query)
       └── 写入 ChatMessage(role="assistant", content=response)
       │
       ▼
SSE 流结束 (发送 "done" 事件)
```

写入发生在 Agent 回复完整生成之后、SSE 流 `done` 事件之前，保证响应先被用户看到，再存入历史。但如果存库失败，用户已看到回复——存在微小的不一致风险。

### 会话创建策略

- `session_id` 由前端传入，或服务端生成 UUID
- 同一个 `session_id` 跨请求复用，消息持续追加
- 前端可以随时换一个新的 `session_id` 开新对话

---

## 六、上下文记忆的实时可见性：SSE 思考过程推送


Agent 执行时采用**双协程并发**模式：

```
┌─────────────────────┐      ┌─────────────────────────┐
│  run_agent()        │      │  SSE 主循环              │
│  (独立 asyncio.Task)│      │                         │
│                     │      │  while not agent_done:   │
│  执行 Agent         │      │    event = await queue   │
│  中间件钩子触发      │──→──│    yield SSE event       │
│  thinking_callback  │ 队列 │                         │
│  将事件 put 到队列   │      │  Agent 完成后 drain 队列 │
│                     │      │  再逐 chunk 发送最终回复  │
│  agent_done.set()   │──→──│  yield "done"            │
└─────────────────────┘      └─────────────────────────┘
```

上下文事件类型（通过中间件和工具内部回调产生）：

| stage | 说明 | 来源 |
|-------|------|------|
| `hyde` | 正在生成假设性文档 | `RagService` |
| `retrieval` | 正在检索向量数据库 | `RagService` |
| `reorder` | 正在对文档重排序 | `ReoderService` |
| `summarize` | 正在总结文档 | `RagService` |
| 工具调用 | `xxx工具调用了` | `agent_middleware.wrap_tool_call` |

---

## 七、中间件层：Agent 生命周期的观察者

LangChain 的 middleware 机制提供 6 个钩子，当前全部用于**日志记录**（不做记忆修改）：

```
before_agent  → Agent 启动前，记录输入消息数量
after_agent   → Agent 结束后，记录输出
before_model  → 每次 LLM 调用前，记录输入消息数量
after_model   → 每次 LLM 调用后，记录输出
wrap_model_call  → 包裹模型调用，日志记录
wrap_tool_call   → 包裹工具调用，日志记录工具名和参数
```

这些钩子**没有修改 context memory**，仅做观测。架构上预留了在此处做记忆压缩/截断的扩展点。

---

## 八、工具层：ContextVar 实现的请求级上下文传递


Agent 的 8 个 Tool 在运行时需要知道"当前是谁在调用"，但 Tool 函数签名与 Agent 框架解耦，无法通过参数传递。当前使用 Python `ContextVar` 实现：

```python
current_user_id_var: ContextVar[str] = ContextVar('current_user_id')
thinking_callback_var: ContextVar[Callable] = ContextVar('thinking_callback')

# 请求入口设置
set_current_user_id(user_id)
set_thinking_callback(thinking_callback)

# Tool 内部读取
user_id = get_current_user_id_from_context()
```

每个 Tool 首行都会检查 `user_id`，若为空则返回错误。这是一种**请求级线程局部存储**，在 asyncio 环境下由 `ContextVar` 保证协程隔离。

### 8 个可用 Tool

| Tool | 功能 | 访问的记忆 |
|------|------|-----------|
| `what_time_is_now` | 获取当前时间 | 无（系统时间） |
| `get_user_info_tools` | 从 JWT 解析用户信息 | JWT Token |
| `search_notes_tool` | 语义搜索笔记 | ChromaDB 笔记向量库 |
| `get_note_stats_tool` | 笔记分类统计 | MySQL 笔记表 |
| `get_today_reviews_tool` | 今日待回顾列表 | MySQL 复习计划表 |
| `mark_reviewed_tool` | 标记已回顾 | MySQL 复习记录表 |
| `create_note_tool` | 创建新笔记 | MySQL + ChromaDB |
| `get_related_notes_tool` | 关联推荐 | ChromaDB 相似度检索 |

---

## 九、架构全景图

```
┌──────────────────────────────────────────────────────────────────┐
│                       请求入口 (chat.py)                          │
│   user_id (JWT)  +  session_id (UUID)  +  query                  │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                  ┌──────────▼──────────┐
                  │   路由决策 (score)    │
                  │   compute_route_     │
                  │   score(query, uid)  │
                  └──────┬──────┬───────┘
                         │      │
                  score>0.5    score≤0.5
                         │      │
             ┌───────────▼──┐   │
             │  RAG 前置管线  │   │
             │               │   │
             │ ① HyDE 扩写   │   │
             │ ② 混合检索    │   │
             │   向量+BM25   │   │
             │ ③ 双源检索    │   │
             │   笔记+知识库  │   │
             │ ④ LLM 重排序  │   │
             │   → Top-3     │   │
             └──────┬───────┘   │
                    │           │
              rag_context    rag_context=""
                    │           │
                    └─────┬─────┘
                          │
                ┌─────────▼──────────┐
                │  DatabaseSession    │
                │  Manager            │
                │  .get_history()     │
                │                     │
                │  MySQL →            │
                │  [(user, asst),     │
                │   (user, asst),     │
                │   ...全量无截断]     │
                └─────────┬──────────┘
                          │
                ┌─────────▼──────────┐
                │   AgentFactory      │
                │   .create_agent_    │
                │   executor()        │
                │                     │
                │  PromptTemplate:    │
                │  ┌──────────────┐   │
                │  │ system_prompt│   │
                │  │ chat_history │   │
                │  │ human input  │   │
                │  │ scratchpad   │   │
                │  └──────────────┘   │
                └─────────┬──────────┘
                          │
                ┌─────────▼──────────┐
                │   AgentExecutor     │
                │   max_iterations=5  │
                │                     │
                │   8 个 Tool 可调用   │
                │   ContextVar 传参   │
                │   中间件日志观测    │
                └─────────┬──────────┘
                          │
                ┌─────────▼──────────┐
                │   SSE 流式输出      │
                │                     │
                │  thinking_queue     │
                │  → 实时思考过程推送  │
                │  → chunked 最终回复 │
                │  → "done" 结束标记  │
                └─────────┬──────────┘
                          │
                ┌─────────▼──────────┐
                │  DatabaseSession    │
                │  Manager            │
                │  .add_message()     │
                │                     │
                │  → MySQL 持久化     │
                │  → 自动标题生成     │
                └────────────────────┘
```

---

## 十、设计特征总结

| 维度 | 当前设计 |
|------|---------|
| **历史长度** | 无限制，全量加载 |
| **历史截断** | 无滑动窗口、无摘要压缩 |
| **存储介质** | MySQL（`chat_sessions` + `chat_messages` 表） |
| **缓存层** | Redis（仅用于业务缓存，不参与对话记忆） |
| **用户隔离** | `user_id` 过滤 + JWT 鉴权 + 会话归属校验 |
| **Agent 迭代保护** | `max_iterations=5`（防止工具调用死循环） |
| **工具上下文传递** | Python `ContextVar`（协程安全） |
| **System Prompt** | 双模式：默认 `main_prompt.txt` / RAG 注入提示词 |
| **agent_scratchpad** | LangChain 自动管理，不持久化 |
| **会话生命周期** | 允许前端任意切换 session_id，老会话永久保留 |
| **中间件扩展点** | 6 个钩子，当前仅用于日志（可扩展记忆压缩） |
| **Token 预算管理** | 无 |
| **长对话降级策略** | 无 |

---
