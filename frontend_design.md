# RAG Learn Little — 前端设计思路

---

## 目录

- [一、整体概览](#一整体概览)
- [二、技术选型依据](#二技术选型依据)
- [三、项目目录结构](#三项目目录结构)
- [四、分层架构](#四分-层-架-构)
- [五、路由设计](#五路由设计)
- [六、状态管理](#六状态管理)
- [七、API 层设计](#七api-层设计)
- [八、SSE 流式通信](#八sse-流式通信)
- [九、主题与样式系统](#九主题与样式系统)
- [十、国际化（i18n）](#十国际化i18n)
- [十一、组件体系](#十一组件体系)
- [十二、核心页面设计](#十二核心页面设计)
- [十三、关键交互流程](#十三关键交互流程)
- [十四、性能优化策略](#十四性能优化策略)
- [十五、设计模式总结](#十五设计模式总结)
- [十六、可复刻清单（Checklist）](#十六可复刻清单checklist)

---

## 一、整体概览

### 1.1 一句话定位

> 一个**单页应用（SPA）**，左侧可折叠导航 + 右侧内容区，以"笔记管理 + AI 对话 + 知识库"三条主线构建的 AI 知识管理工具。

### 1.2 架构总图

```
┌────────────────────────────────────────────────────┐
│                   Browser (SPA)                     │
├──────────┬─────────────────────────────────────────┤
│          │         React Router (useRoutes)         │
│  Zustand │─────────────────────────────────────────┤
│  Stores  │  AuthLayout          MainLayout          │
│  ┌─────┐ │  ┌──────┐   ┌──────────┬────────────┐  │
│  │User │ │  │Login │   │ Sidebar  │  <Outlet>  │  │
│  │Sess │ │  │Regis │   │ (可折叠)  │            │  │
│  │Theme│ │  └──────┘   │          │  NoteList  │  │
│  │Lang │ │             │  导航项   │  NoteEditor│  │
│  └─────┘ │             │  5 功能   │  AIChat    │  │
│          │             │  3 设置   │  Knowledge │  │
│          │             │  登出     │  ...       │  │
│          │             └──────────┴────────────┘  │
├──────────┴─────────────────────────────────────────┤
│                    API Layer                        │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────┐ │
│  │ Axios (REST)│  │ fetch (SSE)  │  │ i18next   │ │
│  │ JWT 拦截    │  │ ReadableStrm │  │ 中/英     │ │
│  └─────────────┘  └──────────────┘  └───────────┘ │
└────────────────────────────────────────────────────┘
         │                  │
         ▼                  ▼
    Backend REST       Backend SSE
    (FastAPI)          (text/event-stream)
```

### 1.3 技术栈速览

| 类别 | 技术 | 版本 | 角色 |
|------|------|------|------|
| 框架 | React | 19.x | UI 框架 |
| 语言 | TypeScript | ~5.6 | 类型安全 |
| 构建 | Vite | 6.x | 开发/打包 |
| 样式 | Tailwind CSS | 3.x | 原子化样式 |
| UI 基座 | Radix UI | ^2.x | 无头组件（Dialog/Dropdown/Select/Tabs/Tooltip/Popover） |
| 编辑器 | Tiptap | 2.11.x | 富文本 Markdown 编辑器 |
| 状态 | Zustand | 5.x | 轻量状态管理 |
| 路由 | React Router DOM | 6.x | 声明式路由 |
| HTTP | Axios | 1.x | REST 客户端 |
| 流式 | 原生 fetch | — | SSE 流式通信 |
| 国际化 | i18next | 26.x | 中/英双语 |
| 渲染 | react-markdown + rehype-highlight | 10.x / 7.x | AI 回答渲染+代码高亮 |
| 通知 | sonner | 2.x | Toast 通知 |
| 图标 | lucide-react | — | 图标库 |

---

## 二、技术选型依据

以下逐条解释**为什么选这个、不选那个**，帮你做同样的决策：

### 2.1 React 19 + Vite 6

- **为什么 React**：生态最成熟、AI/编辑器相关三方库支持最全（Tiptap、react-markdown 等）。
- **为什么 Vite**：开发服务器毫秒级冷启动，HMR 极快，构建产物体积小。相比之下 CRA 已停止维护，Next.js 对纯 SPA 来说过重。
- **为什么不是 Next.js**：本项目为前后端分离架构，前端不涉及 SEO/SSR，不需要 Next.js 的服务端能力。

### 2.2 Tailwind CSS + Radix UI

- **Tailwind**：原子化 CSS 配合 CSS 变量（`--color-*`）实现亮/暗双主题，无需维护独立的 CSS 文件，类名即文档。
- **Radix UI**：提供高质量的无头（headless）UI 原语——Dialog、Dropdown、Select、Tabs、Tooltip、Popover 等，完全控制样式，不引入任何默认视觉。比 Ant Design/MUI 更灵活，比纯手写更稳。
- **为什么不直接用组件库（Antd/MUI）**：本项目追求**独特的设计风格**（纸质书卷气质），组件库的统一视觉会限制定制空间。

### 2.3 Zustand（而非 Redux / Jotai）

- **体积小**（< 1KB），API 简洁。
- 原生支持 `persist` 中间件（一键持久化到 localStorage）。
- 4 个 Store 各司其职，结构清晰，不需要 Redux Toolkit 的样板代码。

### 2.4 Tiptap（而非 Monaco / Quill / 纯 textarea）

- 基于 ProseMirror，底层稳。
- 输出 Markdown 格式，与后端 Agent 无缝对接。
- 插件体系丰富，未来可扩展 AI 内联补全、@ 提及等。

### 2.5 原生 fetch SSE（而非 EventSource / WebSocket）

- `EventSource` 不支持 POST 请求和自定义 Header（无法发 JWT）。
- WebSocket 对单向流来说过重，且需要后端额外部署 WS 支持。
- 原生 `fetch` + `ReadableStream` + `AbortController` 完美覆盖需求。

---

## 三、项目目录结构

```
front/src/
├── api/                        # API 层
│   ├── client.ts               # Axios 实例 + 拦截器
│   ├── endpoints.ts            # 所有 API 路径集中管理（~70 个端点）
│   ├── auth.ts                 # 认证 API
│   ├── chat.ts                 # 聊天 API
│   ├── knowledge.ts            # 知识库 API
│   ├── notes.ts                # 笔记 API
│   ├── sessions.ts             # 会话 API
│   ├── review.ts               # 回顾 API
│   └── noteTemplates.ts        # 笔记模板 API
│
├── components/                 # 组件
│   ├── common/                 # 通用组件
│   │   ├── AuthImage.tsx       # 认证页插图
│   │   ├── ConfirmDialog.tsx   # 确认弹窗
│   │   ├── EmptyState.tsx      # 空状态占位
│   │   ├── LoadingSkeleton.tsx # 骨架屏
│   │   ├── TagBadge.tsx        # 标签徽章
│   │   └── TagInput.tsx        # 标签输入框
│   ├── knowledge/              # 知识库组件
│   │   └── DocumentDetailDrawer.tsx  # 文档详情抽屉
│   ├── layout/                 # 布局组件
│   │   └── Sidebar.tsx         # 侧边导航栏
│   ├── note/                   # 笔记组件
│   │   ├── BatchActionBar.tsx  # 批量操作栏
│   │   ├── CategoryManageDialog.tsx  # 分类管理弹窗
│   │   ├── OutlinePanel.tsx    # 大纲面板
│   │   └── RelatedFragments.tsx # 关联推荐
│   └── TiptapEditor.tsx        # 富文本编辑器（核心组件）
│
├── hooks/                      # 自定义 Hook
│   ├── useDebounce.ts          # 防抖 Hook
│   └── useSSE.ts               # SSE 流式通信 Hook ⭐
│
├── i18n/                       # 国际化
│   ├── index.ts                # i18next 初始化
│   └── locales/
│       ├── zh-CN.ts            # 中文词条
│       └── en-US.ts            # 英文词条
│
├── layouts/                    # 页面布局
│   ├── AuthLayout.tsx          # 认证布局（居中卡片式）
│   └── MainLayout.tsx          # 主布局（侧边栏 + 内容区）
│
├── pages/                      # 页面组件（11 个）
│   ├── Login.tsx               # 登录
│   ├── Register.tsx            # 注册
│   ├── NoteList.tsx            # 笔记列表 ⭐
│   ├── NoteEditor.tsx          # 笔记编辑器 ⭐
│   ├── AIChat.tsx              # AI 对话 ⭐
│   ├── Sessions.tsx            # 对话历史
│   ├── KnowledgeBase.tsx       # 知识库管理 ⭐
│   ├── DailyReview.tsx         # 每日回顾
│   ├── Profile.tsx             # 个人资料
│   ├── Settings.tsx            # 设置
│   └── AboutUs.tsx             # 关于
│
├── router/
│   └── index.tsx               # 路由配置（Routes 对象数组）
│
├── stores/                     # Zustand 状态管理
│   ├── useUserStore.ts         # 用户 + Token
│   ├── useSessionStore.ts      # 聊天会话
│   ├── useThemeStore.ts        # 主题（亮/暗）
│   └── useLanguageStore.ts     # 语言（中/英）
│
├── types/
│   └── api.ts                  # 所有 TypeScript 类型定义
│
├── App.tsx                     # 根组件（useRoutes + 主题切换）
├── main.tsx                    # 入口（BrowserRouter + Toaster 挂载）
└── index.css                   # Tailwind 指令 + CSS 变量 + 全局样式
```

---

## 四、分 层 架 构

前端采用**五层架构**，每层职责明确，上层依赖下层：

```
┌──────────────────────────────────┐
│  Pages（页面层）                   │  ← 组合组件 + Hook + API，处理页面级状态
├──────────────────────────────────┤
│  Components（组件层）              │  ← 可复用的 UI 单元，通过 props 通信
├──────────────────────────────────┤
│  Hooks（逻辑层）                   │  ← 封装可复用逻辑（SSE 连接、防抖等）
├──────────────────────────────────┤
│  Stores + API（数据层）            │  ← Zustand 管理全局状态，API 模块管理请求
├──────────────────────────────────┤
│  CSS Variables + Tailwind（样式层） │  ← 主题变量 + 原子化类名
└──────────────────────────────────┘
```

### 各层原则

**页面层：**
- 一个页面 = 一个文件，`export default`
- 使用 React 16.8+ Hook（`useState` / `useEffect` / `useRef`）管理页面级状态
- 通过 `useTranslation()` 获取国际化文案
- 不直接操作 DOM，不直接调 `fetch`

**组件层：**
- 按领域分目录：`common/`（通用）、`note/`（笔记）、`knowledge/`（知识库）、`layout/`（布局）
- 纯展示组件尽可能无状态，通过 props 驱动
- 与后端无直接耦合——数据由调用方传入

**数据层：**
- API 模块不包含 UI 逻辑，只负责 "发请求 → 返回数据或抛异常"
- Store 模块不包含网络逻辑，只负责 "状态读写"

---

## 五、路由设计

### 5.1 路由结构

```
/ (MainLayout）                      # 需要登录
├── /                    → NoteList  # 默认首页
├── /notes               → NoteList
├── /notes/new           → NoteEditor（新建）
├── /notes/:id           → NoteEditor（编辑）
├── /chat                → AIChat（新对话）
├── /chat/:sessionId     → AIChat（历史对话）
├── /sessions            → Sessions（对话历史列表）
├── /knowledge           → KnowledgeBase
├── /review              → DailyReview
├── /profile             → Profile
├── /settings            → Settings
└── /about               → AboutUs

/auth（AuthLayout）                 # 不需要登录
├── /login               → Login
└── /register            → Register
```

### 5.2 关键设计

**两种布局（Layout）：**

```
AuthLayout          MainLayout
┌──────────┐       ┌────┬──────────┐
│          │       │    │          │
│  居中卡片  │       │ S  │ <Outlet> │
│  (Login/  │       │ i  │          │
│  Register)│       │ d  │ 页面内容   │
│          │       │ e  │          │
│          │       │ b  │          │
│          │       │ a  │          │
└──────────┘       │ r  │          │
                   └────┴──────────┘
```

**实现方式（`MainLayout.tsx`）：**

```tsx
// 路由守卫：未登录 → 重定向到 /login
if (!isLogin) return <Navigate to="/login" replace />

// 已登录 → 渲染侧边栏 + 子路由
return (
  <div className="flex h-screen">
    <Sidebar collapsed={sidebarCollapsed} onToggle={...} />
    <main className="flex-1 overflow-y-auto">
      <Outlet />   {/* ← 子路由在此渲染 */}
    </main>
  </div>
)
```

**页面懒加载：**

每个页面组件都用 `React.lazy()` 包裹 + `Suspense` 做加载态，首次访问时才加载 JS bundle：

```tsx
const NoteList = lazy(() => import('../pages/NoteList'))

// 路由中：
<Suspense fallback={<LoadingSkeleton />}>
  <NoteList />
</Suspense>
```

---

## 六、状态管理

### 6.1 四个 Store

| Store | 持久化 | 核心字段 | 职责 |
|-------|--------|----------|------|
| `useUserStore` | ✅ localStorage | `token`, `userInfo`, `isLogin` | 用户身份 + JWT 管理 |
| `useSessionStore` | ❌ | `sessions[]`, `currentSession` | 当前对话上下文 |
| `useThemeStore` | ✅ localStorage | `theme: 'light' \| 'dark'` | 主题切换 |
| `useLanguageStore` | ✅ localStorage | `lang: 'zh-CN' \| 'en-US'` | 语言切换 |

### 6.2 设计原则

**什么放 Store（全局状态）：**
- 跨页面/跨组件共享的数据（用户信息、主题、语言）
- 需要持久化的数据（Token、用户偏好）

**什么不放 Store（页面局部状态）：**
- 表单输入值（`useState`）
- 列表数据、搜索框内容（`useState`）
- 对话框显隐状态（`useState`）
- 这些用页面级 `useState` 即可，不需要全局化

### 6.3 持久化实现

三个需要持久化的 Store 使用 Zustand 的 `persist` 中间件：

```tsx
// 一行持久化，自动同步到 localStorage
export const useUserStore = create<UserState>()(
  persist(
    (set) => ({
      token: '',
      login: (token, user) => {
        localStorage.setItem('jwt_token', token)  // 双写：axios 拦截器也读这里
        set({ token, userInfo: user, isLogin: true })
      },
      logout: () => {
        localStorage.removeItem('jwt_token')
        set({ token: '', userInfo: null, isLogin: false })
      },
    }),
    { name: 'user-store' }  // ← localStorage key
  )
)
```

> **为什么 Token 双写？** Zustand persist 存了一份，又手动 `localStorage.setItem('jwt_token', token)` 存了一份。原因是 Axios 请求拦截器需要从 `localStorage` 读取——拦截器是普通模块，不在 React 组件树内，无法访问 Zustand Store。

---

## 七、API 层设计

### 7.1 三层结构

```
endpoints.ts          →  路径字典（纯字符串/函数，集中管理）
client.ts             →  Axios 实例（拦截器、超时配置）
业务 API 模块           →  调用 client + endpoints，每个函数对应一个后端接口
  ├── auth.ts
  ├── notes.ts
  ├── chat.ts
  ├── knowledge.ts
  ├── sessions.ts
  ├── review.ts
  └── noteTemplates.ts
```

### 7.2 Axios 实例配置

```tsx
// client.ts
const client = axios.create({
  baseURL: '',           // 空 = 相对路径，开发时走 Vite proxy
  timeout: 30000,        // 30 秒超时
  headers: { 'Content-Type': 'application/json' },
})

// 请求拦截：自动注入 JWT
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('jwt_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截：401 自动登出
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('jwt_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)
```

### 7.3 端点管理

```tsx
// endpoints.ts — 集中管理所有路径，方便后端路由变更时统一修改
export const endpoints = {
  // 静态路径
  login: '/user/login/',
  noteList: '/note/list',
  // 动态路径（函数生成）
  noteDetail: (id: string) => `/note/${id}`,
  noteUpdate: (id: string) => `/note/${id}`,
  // ...
} as const
```

### 7.4 业务 API 模块示例

```tsx
// api/notes.ts
import client from './client'
import { endpoints } from './endpoints'

export const notesApi = {
  list: (params)      => client.get(endpoints.noteList, { params }),
  detail: (id)        => client.get(endpoints.noteDetail(id)),
  create: (data)      => client.post(endpoints.noteCreate, data),
  update: (id, data)  => client.put(endpoints.noteUpdate(id), data),
  delete: (id)        => client.delete(endpoints.noteDelete(id)),
  // ...
}
```

---

## 八、SSE 流式通信

这是 AI 对话和知识库上传进度的核心技术方案。

### 8.1 设计思路

```
┌──────────────────────────────────────────────────┐
│  useSSE Hook                                      │
│                                                    │
│  start(url, body, {                                │
│    onThinking:  (stage, content) => {...}          │
│    onResponse:  (text) => {...}     ← 缓冲批量刷新 │
│    onDone:      (sessionId) => {...}              │
│    onError:     (msg) => {...}                     │
│    onKnowledgeProgress: (data) => {...}            │
│  })                                                │
│                                                    │
│  内部：                                             │
│  fetch() → response.body.getReader()              │
│  → ReadableStream 逐行解析                         │
│  → 按消息类型分发到不同回调                          │
│  → AbortController 支持取消                         │
└──────────────────────────────────────────────────┘
```

### 8.2 四种消息类型

```
data: {"type": "thinking", "stage": "retrieval", "content": "...", "details": {...}}
data: {"type": "response", "content": "回答内容chunk", "session_id": "xxx"}
data: {"type": "done", "session_id": "xxx"}
data: {"type": "error", "content": "错误信息"}
```

### 8.3 响应缓冲机制

SSE 推送的 chunk 频率很高（每 15 字符一次），如果每个 chunk 都触发 React `setState`，会导致频繁渲染。解决方案：

```tsx
const responseBuffer: string[] = []
const RESPONSE_FLUSH_THRESHOLD = 3   // 攒 3 个 chunk 再刷

// 收到 response chunk 时：
responseBuffer.push(data.content)
if (responseBuffer.length >= RESPONSE_FLUSH_THRESHOLD) {
  flushResponse()  // 批量更新状态
}

// 收到 thinking/done/error 时也触发 flush，保证不丢数据
```

### 8.5 知识库上传进度（SSE 双协议）

同一个 `useSSE` Hook 同时支持两种 SSE 格式：
- **聊天 SSE**：`{type: "thinking"|"response"|"done"|"error"}`
- **知识库 SSE**：`{event_type: "processing"|"completed"|"finish", filename, progress}`

通过 `data.event_type` 字段自动区分路由。

---

## 九、主题与样式系统

### 9.1 设计理念

采用 **CSS 变量 + Tailwind 原子化类名** 的双层样式方案：

- **CSS 变量**：定义颜色、间距、圆角、字体、阴影等设计 Token
- **Tailwind 类名**：在 JSX 中直接使用，通过 `[var(--color-xxx)]` 引用 CSS 变量

### 9.2 CSS 变量体系

```css
:root {
  /* 字体体系 */
  --font-heading: 'Noto Serif SC', serif;   /* 标题：宋体/衬线 */
  --font-body: 'Noto Sans SC', sans-serif;   /* 正文：黑体/无衬线 */
  --font-mono: 'JetBrains Mono', monospace;  /* 代码：等宽 */

  /* 颜色体系（亮色主题） */
  --color-bg: #F7F6F3;              /* 页面背景 — 暖白 */
  --color-card: #FFFFFF;            /* 卡片背景 */
  --color-text: #111111;            /* 正文文字 */
  --color-text-secondary: #787774;  /* 次要文字 */
  --color-border: #EAEAEA;          /* 边框 */
  --color-accent: #1F6C9F;          /* 强调色 — 蓝 */
  --color-accent-bg: #E1F3FE;       /* 强调色背景 */
  --color-danger: #9F2F2D;          /* 危险色 — 红 */
  --color-success: #346538;         /* 成功色 — 绿 */

  /* 间距 */
  --space-xs: 4px;  --space-sm: 8px;  --space-md: 16px;
  --space-lg: 24px; --space-xl: 32px; --space-2xl: 48px;

  /* 圆角 */
  --radius-sm: 4px; --radius-md: 8px; --radius-lg: 12px;
}

.dark {
  --color-bg: #1A1A1A;              /* 暗色背景 */
  --color-card: #2A2A2A;
  --color-text: #E8E8E8;
  --color-accent: #4A9ED6;          /* 暗色下提高亮度 */
  /* ... 其他变量覆写 */
}
```

### 9.3 使用方式

```tsx
// 在 Tailwind 中通过任意值语法引用 CSS 变量
<div className="bg-[var(--color-bg)] text-[var(--color-text)] border border-[var(--color-border)]">
  <h2 className="font-heading text-lg text-[var(--color-accent)]">
    标题文字
  </h2>
</div>
```

### 9.4 主题切换实现

```tsx
// App.tsx
const theme = useThemeStore((s) => s.theme)
useEffect(() => {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}, [theme])
// 一个 class 切换，所有 CSS 变量自动切换
```

### 9.5 设计风格关键词

- **纸质书卷气质**：暖白底色、衬线标题、宽松间距
- **柔和边框**：`#EAEAEA`（亮）/ `#3A3A3A`（暗），避免生硬分割线
- **轻阴影**：`rgba(0,0,0,0.04)` 极轻阴影，卡片有微微浮起感
- **明确的信息层级**：text / text-secondary / text-tertiary 三级文字色

---

## 十、国际化（i18n）

### 10.1 技术实现

```tsx
// i18n/index.ts
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import zh from './locales/zh-CN'
import en from './locales/en-US'

i18n.use(initReactI18next).init({
  resources: { 'zh-CN': { translation: zh }, 'en-US': { translation: en } },
  lng: 'zh-CN',       // 默认中文
  fallbackLng: 'zh-CN',
  interpolation: { escapeValue: false },
})
```

### 10.2 使用方式

```tsx
const { t } = useTranslation()

// 简单文本
<span>{t('nav.notes')}</span>

// 带插值
<span>{t('note.totalCount', { count: 42 })}</span>
```

### 10.3 语言切换

在设置页面调用 `useLanguageStore` 的 `setLang('en-US')`，同时调用 `i18n.changeLanguage('en-US')`，整个应用即时切换。

---

## 十一、组件体系

### 11.1 组件清单（共 14 个组件）

```
组件层级：
├── TiptapEditor           ← 富文本编辑器（笔记编辑的核心）
├── layout/
│   └── Sidebar            ← 侧边导航栏（可折叠，5 功能 + 3 设置 + 登出）
├── common/                ← 6 个通用组件
│   ├── LoadingSkeleton    ← 懒加载/数据加载骨架屏
│   ├── EmptyState         ← 空数据占位（图标 + 文案）
│   ├── ConfirmDialog      ← 确认弹窗（Radix AlertDialog 封装）
│   ├── TagBadge           ← 彩色标签徽章
│   ├── TagInput           ← 标签输入组件（回车添加、点击删除）
│   └── AuthImage          ← 认证页装饰插图
├── note/                  ← 4 个笔记相关组件
│   ├── BatchActionBar     ← 批量操作浮层（删除/分类/导出/置顶）
│   ├── CategoryManageDialog ← 分类管理弹窗（拖拽排序）
│   ├── OutlinePanel       ← 笔记大纲（解析标题层级）
│   └── RelatedFragments   ← 关联推荐侧边栏
└── knowledge/             ← 1 个知识库组件
    └── DocumentDetailDrawer ← 文档详情抽屉（分块查看）
```

### 11.2 Sidebar（侧边导航栏）

```
┌──────────────┐
│  App Logo    │  ← RAG NoteBook
│  [折叠按钮]   │
├──────────────┤
│  📄 笔记     │  ← NavLink，当前路由自动高亮
│  💬 AI 对话  │
│  📋 对话历史  │
│  📖 每日回顾  │
│  📚 知识库   │
├──────────────┤
│  👤 个人信息  │  ← 底部区域
│  ⚙️ 设置     │
│  ℹ️ 关于     │
├──────────────┤
│  🚪 退出登录  │
└──────────────┘

折叠态：54px 宽，只显示图标 + Tooltip
展开态：240px 宽，显示图标 + 文字
```

**折叠逻辑：** `MainLayout` 中维护 `sidebarCollapsed` 状态，`Sidebar` 组件通过 `collapsed` prop 切换宽度（`w-60` ↔ `w-16`）+ 隐藏文字。

### 11.3 通用组件设计原则

**EmptyState：**
```tsx
<EmptyState
  icon={<FileText />}
  title="还没有笔记"
  description="点击上方按钮创建第一篇笔记"
  action={<Button>立即创建</Button>}
/>
```

**ConfirmDialog（基于 Radix AlertDialog）：**
```tsx
<ConfirmDialog
  open={showDelete}
  title="确认删除？"
  description="删除后不可恢复"
  confirmLabel="删除"
  variant="danger"
  onConfirm={handleDelete}
  onCancel={() => setShowDelete(false)}
/>
```

**LoadingSkeleton：**
- 懒加载页面时：整页骨架屏（模拟笔记列表 / 对话界面的骨架形状）
- 数据加载中时：卡片级骨架屏（标题条 + 内容行）

### 11.4 Tiptap 编辑器（核心复杂组件）

```
TiptapEditor 组件结构：
┌─────────────────────────────┐
│  工具栏                      │
│  [B] [I] [H1] [H2] [H3]    │  ← Bold/Italic/Heading
│  [Code] [Quote] [Bullet]    │  ← 代码块/引用/列表
│  [Table] [Image] [Link]     │  ← 表格/图片/链接
│  [📋 模板]                   │  ← 模板下拉选择
│  [🤖 AI 辅助]                │  ← AI 续写/扩写/摘要
├─────────────────────────────┤
│                              │
│  Tiptap EditorContent       │
│  (基于 ProseMirror)         │
│                               │
├─────────────────────────────┤
│  [大纲面板]  [关联推荐]       │  ← 侧边面板
└─────────────────────────────┘
```

---

## 十二、核心页面设计

### 12.1 NoteList（笔记列表）— 首页

```
┌──────────────────────────────────────────────┐
│  [🔍 搜索笔记...]         [+ 新建笔记]         │
│                                                │
│  [全部] [工作] [学习] [生活] [技术] [其他]      │  ← 分类筛选
│  [⚙ 分类管理]                                 │
│                                                │
│  ┌──────────────────┐ ┌──────────────────┐   │
│  │ 📌 笔记标题        │ │ 笔记标题          │   │
│  │ 内容预览文字...     │ │ 内容预览...        │   │
│  │ 🏷标签1 🏷标签2    │ │ 🏷标签            │   │
│  │ 2小时前 · 技术     │ │ 昨天 · 学习       │   │
│  └──────────────────┘ └──────────────────┘   │
│  ┌──────────────────┐ ┌──────────────────┐   │
│  │ ...              │ │ ...              │   │
│  └──────────────────┘ └──────────────────┘   │
│                                                │
│  ← 无限滚动（IntersectionObserver）             │
│                                                │
│  [批量操作栏] ← 勾选笔记后出现                  │
└──────────────────────────────────────────────┘
```

**核心交互：**
- **卡片网格**：笔记以卡片形式展示，置顶笔记带 📌 标记
- **分类筛选**：横向选项卡，支持自定义分类和拖拽排序
- **搜索**：输入后 300ms 防抖调后端语义搜索
- **无限滚动**：`IntersectionObserver` 监听 sentinel 元素，触底自动加载下一页
- **批量模式**：勾选笔记 → 底部弹出 `BatchActionBar`（批量删除/分类/导出/置顶）
- **右键菜单**：每条笔记支持快速操作

### 12.2 NoteEditor（笔记编辑器）

```
┌──────────────────────────────────────────────┐
│  [← 返回]  [标题: ___________]  [💾 保存]    │
│  [🏷 标签]  [📂 分类]                        │
├──────────────┬───────────────────────────────┤
│  大纲面板      │  Tiptap 编辑器                │
│  (可收起)     │                               │
│              │  # 一级标题                    │
│  ├ 一级标题   │  正文内容...                   │
│  │ ├ 二级标题 │                               │
│  │ │ └ 三级   │  ## 二级标题                  │
│  │ └ 二级     │  更多内容...                   │
│  └ 一级       │                               │
│              │                               │
│              │  [🤖 AI 辅助]  <-- 续写/扩写/摘要│
├──────────────┴───────────────────────────────┤
│  关联推荐面板（可展开）                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐        │
│  │ 相关笔记  │ │ 知识库   │ │ 相似度  │        │
│  │ 标题...  │ │ 文档...  │ │ 92%    │        │
│  └─────────┘ └─────────┘ └─────────┘        │
└──────────────────────────────────────────────┘
```

**核心流程：**
1. 进入页面 → 如果有 `id` 参数则加载笔记详情，否则为空白新建
2. 编辑器内容变化 → 自动保存草稿到 localStorage
3. 点击保存 → 调 API → 后端异步生成标签和分类 → 返回后自动刷新
4. 大纲面板：解析 Markdown 标题（`#` / `##` / `###`），点击标题跳转到对应位置
5. AI 辅助（SSE）：选中文字 → 选择操作（续写/扩写/摘要/翻译）→ 流式显示结果

### 12.3 AIChat（AI 对话）

```
┌──────────────────────────────────────────────┐
│  [🤖 AI 对话]                      [对话历史]  │
├──────────────────────────────────────────────┤
│                                               │
│  💡 快捷问题：                                 │
│  [帮我解释量子计算] [写一首春天的诗] [推荐书籍]  │
│                                               │
│  ┌────────────────────────────────────┐      │
│  │ 👤 用户消息                          │      │
│  │ 帮我总结一下最近的学习笔记            │      │
│  └────────────────────────────────────┘      │
│                                               │
│  ┌────────────────────────────────────┐      │
│  │ 🤖 AI                               │      │
│  │                                    │      │
│  │ ▼ 思考过程（可折叠）                 │      │
│  │   1. 检索中...                      │      │
│  │   2. 生成假设性回答...               │      │
│  │   3. 重排序中...                    │      │
│  │   4. 总结中...                      │      │
│  │                                    │      │
│  │ 根据你的学习笔记，近期主要关注的      │      │
│  │ 领域包括... （Markdown 渲染）        │      │
│  └────────────────────────────────────┘      │
│                                               │
├──────────────────────────────────────────────┤
│  [📝 输入你的问题...]              [发送 →]    │
└──────────────────────────────────────────────┘
```

**核心交互：**
- **思考过程实时展示**：SSE `thinking` 事件实时显示 RAG 管线各阶段进展，可折叠
- **Markdown 渲染**：AI 回答用 `react-markdown` + `rehype-highlight` 渲染，支持代码块、表格、公式
- **对话持久化**：消息存入后端 MySQL，刷新页面不丢
- **自动滚动**：新消息到达时自动滚到底部
- **会话管理**：可从左侧导航切换到历史对话

### 12.4 KnowledgeBase（知识库管理）

```
┌──────────────────────────────────────────────┐
│  [📚 知识库管理]                              │
├──────────────────────────────────────────────┤
│                                               │
│  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐      │
│  │  📁 拖拽文件到此处或点击上传         │      │  ← 拖拽上传区
│  │  支持 PDF / TXT / Markdown / DOCX  │      │
│  │  单文件 ≤ 20MB，多文件 ≤ 200MB      │      │
│  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘      │
│                                               │
│  上传进度：                                    │
│  📄 论文.pdf  ████████████░░  85%  uploading   │
│  📄 笔记.txt  ██████████████ 100%  ✅ 完成     │
│                                               │
│  文档列表：                                    │
│  ┌──────────────────────────────────┐        │
│  │ 📄 论文.pdf   12 chunks  2天前   │ 🗑     │  ← 点击打开详情抽屉
│  │ 📄 手册.txt   8 chunks   1周前   │ 🗑     │
│  │ 📄 报告.docx  20 chunks  1月前   │ 🗑     │
│  └──────────────────────────────────┘        │
│                                               │
│  [🧹 清理全部向量]                             │
└──────────────────────────────────────────────┘
│
├─ 文档详情抽屉（DocumentDetailDrawer）
│  ┌──────────────────────────┐
│  │ 文件名、MD5、创建时间      │
│  │ ──────────────────────── │
│  │ Chunk 1 (Page 1)         │
│  │ 内容文本...               │
│  │ [图片1] [图片2]           │
│  │ ──────────────────────── │
│  │ Chunk 2 (Page 2)         │
│  │ ...                      │
│  └──────────────────────────┘
```

**核心交互：**
- **拖拽上传**：拖入文件 → 预览列表 → 调 SSE 接口开始上传
- **实时进度**：SSE `processing` 事件驱动进度条更新
- **文档详情**：点击文档 → 右侧滑出抽屉（Drawer），展示所有 chunk 和图片
- **MD5 去重**：后端通过 MD5 自动去重，重复文件不会重复向量化
- **向量清理**：一键清除所有向量数据

### 12.5 DailyReview（每日回顾）

基于**艾宾浩斯遗忘曲线**的去重回顾机制。后台按 1/2/4/7/15/30 天的间隔创建回顾记录，前端只需展示今日待回顾的笔记列表，支持标记完成和 AI 生成回顾问题。

### 12.6 其他页面

| 页面 | 说明 |
|------|------|
| Profile | 个人信息展示 + 编辑头像/简介 |
| Settings | 主题切换 / 语言切换 / 修改密码 |
| Sessions | 对话历史列表，支持搜索和删除 |
| AboutUs | 关于页面，技术栈展示 |
| Login/Register | 邮箱+密码登录，注册含验证 |

---

## 十三、关键交互流程

### 13.1 用户登录 → 访问受保护页面

```
1. Login 页面输入邮箱+密码 → POST /user/login/
2. 后端返回 {token, user}
3. useUserStore.login(token, user)
   ├── localStorage.setItem('jwt_token', token) ← 双写
   └── Zustand set({ token, userInfo, isLogin: true })
4. navigate('/') 跳转首页
5. MainLayout 检测 isLogin=true → 渲染 Sidebar + 内容区
6. 所有后续请求 → Axios 拦截器自动注入 Bearer Token
```

### 13.2 AI 对话完整流程（含 RAG）

```
1. 用户输入问题 → 点击发送
2. UI 上添加 user message 气泡
3. 调 useSSE.start(POST /chat/agent/query/stream, {query, session_id})
4. 后端执行 RAG 管线 → 通过 SSE 推送进度：
   ├── thinking: {stage: "retrieval", content: "正在检索..."}
   ├── thinking: {stage: "hyde", content: "正在生成假设回答..."}
   ├── thinking: {stage: "reorder", content: "正在重排序..."}
   ├── thinking: {stage: "summarize", content: "正在总结..."}
   ├── response: {content: "根据"}   ← 回答内容 chunk
   ├── response: {content: "你的"}
   ├── ... (缓冲 3 个 chunk 后批量刷新 UI)
   └── done: {session_id: "xxx"}
5. 前端收到 done → 刷新会话列表
6. 如果是新对话 → 更新 URL 为 /chat/{sessionId}
```

### 13.3 笔记保存 → 自动标签流程

```
1. 用户在 NoteEditor 中编辑内容 → 点击保存
2. 前端调 notesApi.update(id, {title, content, tags, category})
3. 后端保存 MySQL + ChromaDB 向量双写
4. 后端 asyncio.create_task 异步生成标签（LLM）
5. 前端收到保存成功 → 显示 toast "保存成功"
6. 标签生成完成后 → 前端下次加载笔记时可看到新标签
   （异步不阻塞用户，标签可能延迟几秒出现）
```

### 13.4 Token 过期 / 401 处理

```
1. 任何 API 请求返回 401
2. Axios 响应拦截器捕获：
   ├── localStorage.removeItem('jwt_token')
   └── window.location.href = '/login'
3. 登录页加载 → 用户重新登录 → 回到之前的页面
```

---

## 十四、性能优化策略

### 14.1 加载性能

| 优化项 | 实现方式 | 效果 |
|--------|----------|------|
| **路由懒加载** | `React.lazy()` + `Suspense` | 首次只加载当前页面 JS，其他页面按需加载 |
| **原子化 CSS** | Tailwind 按需生成 | 生产包中只包含实际使用的样式（通常 < 10KB） |
| **Tree Shaking** | Vite + ES Module | 三方库中未使用的模块自动剔除 |

### 14.2 渲染性能

| 优化项 | 实现方式 |
|--------|----------|
| **SSE 缓冲刷新** | 3 chunk 阈值批量更新，减少 React 渲染次数 |
| **requestAnimationFrame** | AIChat 中用 RAF 合并高频内容更新 |
| **useCallback/useMemo** | 稳定的回调引用，避免子组件不必要的重渲染 |
| **IntersectionObserver** | 笔记列表无限滚动，不一次性渲染所有数据 |

### 14.3 用户体验优化

| 优化项 | 实现方式 |
|--------|----------|
| **骨架屏** | Loading 时展示内容骨架而非空白/spinner |
| **防抖搜索** | `useDebounce(300ms)` 减少搜索 API 调用 |
| **乐观更新** | 保存笔记后立即更新列表，不等待刷新 |
| **SSE 取消** | `AbortController` 支持中途停止生成 |
| **草稿保存** | 笔记编辑器自动保存草稿到 localStorage |

---

## 十五、设计模式总结

### 15.1 架构模式

| 模式 | 应用 |
|------|------|
| **分层架构** | Pages → Components → Hooks → Stores/API → Styles |
| **单例路径字典** | `endpoints.ts` 集中管理所有 API 路径 |
| **Provider 模式** | `i18next` 的 `I18nextProvider`、路由的 `BrowserRouter` |
| **布局嵌套** | `MainLayout` + `AuthLayout` 通过 `<Outlet />` 嵌套子路由 |
| **Hook 封装** | `useSSE` 封装 SSE 连接、`useDebounce` 封装防抖 |

### 15.2 状态管理模式

| 模式 | 应用 |
|------|------|
| **全局状态** | Zustand Store（用户/主题/语言/会话） |
| **持久化状态** | Zustand `persist` 中间件（用户偏好不丢失） |
| **页面状态** | `useState` / `useReducer`（表单、列表、弹窗） |
| **URL 状态** | React Router URL 参数（当前笔记 ID、会话 ID） |

### 15.3 组件设计模式

| 模式 | 示例 |
|------|------|
| **容器/展示分离** | API 调用在页面层，组件通过 props 接收数据 |
| **受控组件** | Tiptap 编辑器通过 `content` + `onChange` 受控 |
| **Render Props / children** | `LazyLoad`、`ConfirmDialog` 通过 children 组合 |
| **Compound Components** | Radix UI 的 `Dialog.Trigger` / `Dialog.Content` 等 |

---

## 十六、可复刻清单（Checklist）

如果你想从零搭建一个相同架构的前端项目，按以下步骤操作：

### 阶段一：项目脚手架

- [ ] `npm create vite@latest` → React + TypeScript
- [ ] 安装 Tailwind CSS 并配置 `content` 路径
- [ ] 在 `index.css` 中定义亮/暗两套 CSS 变量
- [ ] 配置 `tailwind.config.js` 扩展字体族（font-heading / font-body / font-mono）
- [ ] 安装 `zustand`、`react-router-dom`、`axios`、`i18next`、`react-i18next`
- [ ] 安装 `lucide-react`（图标）、`sonner`（Toast）

### 阶段二：基础设施

- [ ] 创建 `api/client.ts`（Axios 实例 + 请求/响应拦截器）
- [ ] 创建 `api/endpoints.ts`（所有 API 路径字典）
- [ ] 创建 `stores/useUserStore.ts`（Token + 用户信息，persist）
- [ ] 创建 `stores/useThemeStore.ts`（主题切换，persist）
- [ ] 创建 `stores/useLanguageStore.ts`（语言切换，persist）
- [ ] 初始化 `i18n/index.ts` 并准备 `zh-CN.ts` / `en-US.ts` 词条文件
- [ ] 创建 `hooks/useSSE.ts`（SSE 流式通信 Hook）
- [ ] 创建 `hooks/useDebounce.ts`（防抖 Hook）

### 阶段三：布局与路由

- [ ] 创建 `layouts/AuthLayout.tsx`（居中卡片式布局）
- [ ] 创建 `layouts/MainLayout.tsx`（侧边栏 + 内容区，含登录守卫）
- [ ] 创建 `components/layout/Sidebar.tsx`（可折叠导航栏）
- [ ] 创建 `router/index.tsx`（Routes 配置 + 懒加载）
- [ ] 在 `App.tsx` 中组合 `useRoutes(routes)` + 主题 `useEffect`
- [ ] 在 `main.tsx` 中挂载 `BrowserRouter` + `App` + `Toaster`

### 阶段四：通用组件

- [ ] `LoadingSkeleton`（骨架屏）
- [ ] `EmptyState`（空状态占位）
- [ ] `ConfirmDialog`（确认弹窗，基于 Radix AlertDialog）
- [ ] `TagBadge`（标签徽章）
- [ ] `TagInput`（标签输入）

### 阶段五：页面开发

- [ ] `Login.tsx` + `Register.tsx`（认证页面）
- [ ] `NoteList.tsx`（笔记列表：搜索、分类筛选、无限滚动、批量操作）
- [ ] `NoteEditor.tsx`（笔记编辑器：Tiptap + 大纲 + 关联推荐 + AI 辅助）
- [ ] `AIChat.tsx`（AI 对话：流式消息、思考过程、Markdown 渲染）
- [ ] `KnowledgeBase.tsx`（知识库：拖拽上传、进度条、文档列表、详情抽屉）
- [ ] `DailyReview.tsx`（每日回顾）
- [ ] `Sessions.tsx`（对话历史列表）
- [ ] `Profile.tsx` + `Settings.tsx`（个人设置）
- [ ] `AboutUs.tsx`（关于页面）

### 阶段六：业务 API 模块

- [ ] `api/auth.ts`
- [ ] `api/notes.ts`
- [ ] `api/chat.ts`
- [ ] `api/knowledge.ts`
- [ ] `api/sessions.ts`
- [ ] `api/review.ts`
- [ ] `api/noteTemplates.ts`

### 阶段七：TypeScript 类型

- [ ] 在 `types/api.ts` 中定义所有实体类型（Note、User、Session、Knowledge 等）
- [ ] 定义 SSE 消息类型（SSEMessage、KnowledgeSSEMessage）

### 阶段八：Vite 配置

- [ ] 配置 `server.proxy`：将 `/chat/`、`/note/`、`/knowledge/`、`/user/` 等路径代理到后端
- [ ] 配置 `server.port: 3000`

---

## 附录：关键文件速查

| 想了解什么 | 去看哪个文件 |
|-----------|-------------|
| 路由有哪些 | [router/index.tsx](../front/src/router/index.tsx) |
| API 路径全集 | [api/endpoints.ts](../front/src/api/endpoints.ts) |
| 登录状态怎么管 | [stores/useUserStore.ts](../front/src/stores/useUserStore.ts) |
| SSE 怎么实现 | [hooks/useSSE.ts](../front/src/hooks/useSSE.ts) |
| AI 对话页面逻辑 | [pages/AIChat.tsx](../front/src/pages/AIChat.tsx) |
| 笔记列表逻辑 | [pages/NoteList.tsx](../front/src/pages/NoteList.tsx) |
| CSS 变量有哪些 | [index.css](../front/src/index.css) |
| 类型怎么定义 | [types/api.ts](../front/src/types/api.ts) |
| 侧边栏结构 | [components/layout/Sidebar.tsx](../front/src/components/layout/Sidebar.tsx) |
