<div align="center">

# ☁️ 云尚 · RAG LearnLittle

**AI 驱动的个人知识管理助手 —— 让笔记拥有记忆，让对话理解一切**

`RAG` `Agent` `多模态` `FastAPI` `LangGraph` `React`

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-LangChain-1C3C3C)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)
![ChromaDB](https://img.shields.io/badge/ChromaDB-1.0%2B-FC60A8)
![Redis](https://img.shields.io/badge/redis--py-5%2B-DC382D?logo=redis&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-8%2B-4479A1?logo=mysql&logoColor=white)

</div>

---

## 1. 项目解决什么问题

云尚解决的是**个人知识管理碎片化**的痛点：笔记记了就忘、知识散落在不同平台、查找依靠关键词匹配而非语义理解。

传统笔记工具只能"存"，云尚能"理解"——

| 痛点 | 云尚的解决方案 |
|:---|:---|
| 笔记记完就忘 | 艾宾浩斯回顾系统，自动推送待复习笔记 |
| 知识散落各处 | 知识库 + 笔记双源 RAG 检索，一次搜索覆盖全部知识 |
| 搜索只能查关键词 | 向量语义搜索 + BM25 混合召回 + CrossEncoder 重排序 |
| 笔记内容不关联 | AI 自动推荐关联笔记，发现知识之间的联系 |
| 长文档难以消化 | 上传 PDF/Markdown/TXT 后 AI 帮你总结和问答 |

> 🎯 定位：本地优先的私人知识助手，你的"第二大脑"。

---

## 2. 主要功能

### 🤖 AI 对话

| 功能 | 说明 |
|:---|:---|
| 基础问答 | 自然语言对话，支持知识问答、代码生成、数学计算 |
| 深度思考 | 🧠 开关控制，开启后模型先内部推理再输出答案（qwen3 thinking 模式） |
| 多模态理解 | 📎 上传图片/视频附件，视觉模型（qwen-vl-max）理解内容 |
| 流式输出 | SSE 实时逐 token 输出，思考过程可见 |

### 🛠️ Agent 工具层

AI 可以主动调用工具完成复杂任务（15 个内置工具）：

| 工具组 | 能力 |
|:---|:---|
| 笔记读写 | 创建笔记、更新笔记、搜索笔记、获取内容、统计、关联推荐 |
| 回顾管理 | 获取今日待回顾列表、标记已完成回顾 |
| PPT 生成 | 关键词触发的讲解 PPT 自动生成（python-pptx 本地渲染） |
| 邮件发送 | 笔记以 Markdown/PDF 导出到邮箱 |
| 翻译 | DeepL 高质量翻译（需配置 API Key） |
| 计算 | Wolfram Alpha 精确计算、解方程、单位换算 |
| 语音合成 | Edge TTS 文本朗读（对话中说"读给我听"触发） |
| MCP 联网 | Tavily 联网搜索 + URL 内容提取 |

### 📚 RAG 知识库

| 功能 | 实现 |
|:---|:---|
| 文档上传 | 支持 PDF、Markdown、TXT，SSE 实时进度推送 |
| 向量检索 | ChromaDB 持久化，cosine 相似度 |
| 混合召回 | 向量检索 + BM25 关键词匹配 |
| 重排序 | BAAI/bge-reranker-v2-m3 CrossEncoder 精排 |
| 双源检索 | 知识库文档 + 笔记内容同时检索 |
| HyDE | LLM 生成假设性回答提升检索准确率 |

### 📓 笔记系统

| 功能 | 说明 |
|:---|:---|
| 富文本编辑 | TipTap 编辑器，支持 Markdown 格式 |
| 语义搜索 | 基于向量相似度的语义搜索 |
| AI 辅助 | 自动补全、打标签（开发中） |
| 回收站 | 删除笔记进入回收站，14 天自动清除 |
| 模板 | 笔记模板创建与管理 |

### 🔧 其他功能

| 功能 | 说明 |
|:---|:---|
| 会话管理 | 多会话、自动标题生成、历史消息游标分页 |
| Token 用量追踪 | 模型调用统计、费用计算、Langfuse 可观测 |
| 定时任务 | 回收站清理、孤儿附件清理、TTS 文件清理 |
| 国际化 | 中/英文界面切换，暗色/亮色主题 |
| 账户安全 | JWT 双 Token 认证、设备管理、频率限制 |

---

## 3. 安装方法

### 环境要求

| 依赖 | 版本 |
|:---|:---|
| Python | ≥ 3.10 |
| Node.js | ≥ 18 |
| MySQL | 8.x |
| Redis | ≥ 6.x |

### 3.1 克隆项目

```bash
git clone https://github.com/qiaojoin586-droid/RAG_LearnLittleCode.git
cd RAG_LearnLittleCode
```

### 3.2 配置后端

```bash
# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate     # Windows
# source .venv/bin/activate  # macOS / Linux

# 安装依赖
pip install -r requirements.txt

# 创建配置文件
cp .env.example .env
```

编辑 `.env`，填写以下必填项：

```ini
# 模型提供商
MODEL_PROVIDER=dashscope
DASHSCOPE_API_KEY=sk-你的百炼API密钥

# 数据库
MYSQL_USER=root
MYSQL_PASSWORD=你的密码
MYSQL_DATABASE=raglearn

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# JWT 签名密钥（生成命令: python -c "import secrets; print(secrets.token_hex(32))"）
JWT_SECRET=你的随机密钥
```

> 💡 获取 DashScope API Key：访问 [阿里云百炼控制台](https://bailian.console.aliyun.com/)，新用户有免费额度。

### 3.3 创建数据库

```sql
CREATE DATABASE raglearn CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 3.4 安装前端依赖

```bash
cd front
npm install
```

### 3.5 首次运行注意事项

- **重排序模型下载**：首次启动会从 HuggingFace 镜像下载 `BAAI/bge-reranker-v2-m3`（约 1GB），需 2-5 分钟。如果下载失败，在 `.env` 中设置：
  ```ini
  HF_ENDPOINT=https://hf-mirror.com
  ```
- **视觉模型**（可选）：设置 `VISION_MODEL=qwen-vl-max` 启用图片/视频理解
- **邮件服务**（可选）：配置 `SMTP_USERNAME` / `SMTP_PASSWORD` 启用注册验证码

---

## 4. 使用方法

### 4.1 启动服务

**后端**（先启动）：
```bash
python main.py
# 服务启动在 http://localhost:8001
# API 文档: http://localhost:8001/docs
```

**前端**（另开终端）：
```bash
cd front
npm run dev
# 服务启动在 http://localhost:3000
```

### 4.2 登录

浏览器访问 `http://localhost:3000`，使用测试账号登录：

| 用户名 | 密码 |
|:---|:---|
| `admin` | `admin1234` |

> 测试账号仅在 `APP_ENV=development` 时自动创建

### 4.3 开始使用

1. **对话**：直接在聊天框输入问题，AI 会回答
2. **深度思考**：点击输入框旁的 🧠 按钮开启，复杂问题回答更深入（响应稍慢）
3. **创建笔记**：对 AI 说"帮我创建一条笔记，标题是..."，AI 自动调用笔记工具
4. **上传文档**：点击 📎 上传 PDF/Markdown/TXT，上传后对话中 AI 可基于文档内容回答
5. **搜索知识**：对 AI 说"搜索关于 XX 的笔记"，或直接使用笔记页面的搜索功能
6. **上传图片**：点击 📎 上传图片，视觉模型会描述和分析图片内容

---

## 5. 输入输出示例

### 5.1 基础对话

**输入**：
```
你好，请用三句话介绍人工智能
```

**SSE 流式输出**（`POST /api/v1/chat/query`）：
```
data: {"type":"thinking","stage":"processing","content":"正在思考..."}
data: {"type":"response","content":"人工智能（AI）是计算机科学的一个分支"}
data: {"type":"response","content":"，旨在创建能够模拟人类智能的系统"}
data: {"type":"response","content":"..."}
data: {"type":"done","session_id":"c3e2db06-def5-4267-bc0d"}
```

**最终回复**：
```
人工智能（AI）是计算机科学的一个分支，旨在创建能够模拟人类智能的系统。
它涵盖机器学习、自然语言处理、计算机视觉等领域。
现代AI已广泛应用于医疗诊断、自动驾驶、智能助手等场景。
```

### 5.2 Agent 工具调用 — 创建笔记

**输入**：
```
帮我创建一条笔记，标题是"RAG学习笔记"，内容包含RAG的定义、核心流程和三个优势
```

**SSE 流式输出**：
```
data: {"type":"thinking","stage":"processing","content":"正在思考..."}
data: {"type":"tool_start","tool":"create_note_tool","args":"{"title":"RAG学习笔记",...}"}
data: {"type":"thinking","stage":"processing","content":"正在创建笔记..."}
data: {"type":"tool_end","tool":"create_note_tool","result":"笔记创建成功","duration_ms":156}
data: {"type":"response","content":"已为你创建笔记「RAG学习笔记」，包含RAG的定义、核心流程和优势说明。"}
data: {"type":"done","session_id":"c3e2db06-def5-4267-bc0d"}
```

### 5.3 知识库文档上传与 RAG 检索

**Step 1 — 上传文档**（`POST /api/v1/knowledge/upload`）：

**输入**：上传 `test.txt`（内容："RAG stands for Retrieval-Augmented Generation..."）

**SSE 进度输出**：
```
data: {"event_type":"processing","stage":"saving","message":"正在保存文件..."}
data: {"event_type":"processing","stage":"parsing","message":"正在解析文档内容..."}
data: {"event_type":"processing","stage":"splitting","message":"文本切片完成，共 1 个片段"}
data: {"event_type":"processing","stage":"vectorizing","message":"正在向量化..."}
data: {"event_type":"completed","progress":100,"message":"文档处理完成"}
data: {"event_type":"finish"}
```

**Step 2 — RAG 检索**（`POST /api/v1/chat/rag`）：

**输入**：
```json
{"query": "什么是RAG", "top_k": 3}
```

**输出**：
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "answer": "RAG stands for Retrieval-Augmented Generation, a technique that combines information retrieval with language generation.",
    "sources": [
      {
        "content": "RAG stands for Retrieval-Augmented Generation...",
        "source": "knowledge",
        "score": 0.6343,
        "metadata": {"filename": "test.txt", "document_id": "1"}
      }
    ]
  }
}
```

### 5.4 笔记 CRUD

**创建笔记**（`POST /api/v1/note`）：

请求：
```json
{"title": "Python学习路线", "content": "基础语法 → 面向对象 → Web框架 → 数据科学", "tags": ["Python", "学习"]}
```

响应：
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "id": "7ef28a2c-7bf4-46e2-99c2-8f983336312b",
    "title": "Python学习路线",
    "content": "基础语法 → 面向对象 → Web框架 → 数据科学",
    "tags": ["Python", "学习"],
    "category": null,
    "created_at": "2026-08-11T10:15:04",
    "updated_at": "2026-08-11T10:15:04"
  }
}
```

**搜索笔记**（`POST /api/v1/note/search`）：

请求：
```json
{"query": "Python", "top_k": 5}
```

响应：
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "query": "Python",
    "results": [
      {"content": "基础语法 → 面向对象 → Web框架 → 数据科学", "score": 0.82, "note_id": "7ef28a2c-..."}
    ]
  }
}
```

### 5.5 深度思考对比

| | 关闭深度思考 | 开启深度思考 🧠 |
|:---|:---|:---|
| 响应速度 | 2-5 秒 | 10-30 秒 |
| 推理过程 | 不展示 | 实时展示思考链 |
| 回答质量 | 直接给答案 | 分步推导，更严谨 |

**示例**："有3个盒子，1个有奖。你选1号，主持人开3号是空的。该不该换？"

关闭深度思考 → "应该换，换的中奖概率是 2/3。"

开启深度思考 → "这是蒙提霍尔问题。让我逐步分析：初始每盒 1/3 概率。若奖品在1号(1/3)→换则输；奖品在2号(1/3)→主持人必开3号→换则赢；奖品在3号(1/3)→主持人必开2号→换则赢。结论：换的中奖概率 2/3，坚持 1/3，应该换。"

### 5.6 登录认证

**请求**（`POST /api/v1/auth/login`）：
```json
{"username": "admin", "password": "admin1234"}
```

**响应**：
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 1800
  }
}
```

> 所有 API 请求需携带 `Authorization: Bearer <access_token>`，详细文档见 `http://localhost:8001/docs`

---

## 📁 项目结构

```
RAG_LearnLittleCode/
├── main.py                  # FastAPI 入口
├── app/
│   ├── ai_service/          # Agent 编排（ReAct / Plan-Execute / 工具注册 / MCP / 流式）
│   ├── core/                # 日志、异常处理、限流、metrics、model_trace
│   ├── db/                  # SQLAlchemy 异步引擎 + Redis 客户端
│   ├── models/              # ORM 模型（用户 / 笔记 / 知识库 / 会话 / 审计）
│   ├── rag/                 # RAG 核心（向量库、检索、RagService、重排序）
│   ├── routers/             # API 路由（15 个模块，46 个端点）
│   ├── schemas/             # Pydantic 请求/响应模型
│   ├── services/            # 业务服务（笔记、邮件、PPT、用量、记忆压缩）
│   └── utils/               # 模型工厂、认证工具、配置加载、SSRF 守卫
├── config/                  # YAML 配置（agent / chroma / prompt / pricing）
├── front/                   # React 19 + Vite + TailwindCSS 前端
├── prompts/                 # Agent 系统提示词（12 个）
├── templates/               # 邮件 HTML 模板
├── alembic/                 # 数据库迁移脚本
├── tests/                   # 测试
├── .env.example             # 环境变量模板
└── requirements.txt
```

---

## ⚙️ 配置说明

| 配置文件 | 作用 |
|:---|:---|
| `config/agent.yaml` | Agent 行为中枢：迭代上限、工具分组、关键词路由、超时、MCP Server 配置 |
| `config/chroma.yaml` | 向量库：持久化目录、切片参数、重排序模型 |
| `config/prompt.yaml` | 提示词模板配置 |
| `config/pricing.yaml` | 模型定价种子（按 token 计价） |
| `prompts/*.txt` | 12 个 Agent 提示词，可直接编辑调优 |

系统行为通过 YAML 文件调优，无需改代码，修改后重启服务生效。

---

## 🔌 API 端点概览

所有业务路由统一前缀 `/api/v1`，完整交互文档见 `http://localhost:8001/docs`

| 模块 | 端点 | 说明 |
|:---|:---|:---|
| 认证 | `POST /auth/register` `POST /auth/login` `POST /auth/send-code` | 注册 / 登录 / 发送验证码 |
| 认证 | `POST /auth/refresh` `POST /auth/logout` | Token 刷新 / 登出 |
| 认证 | `GET /auth/sessions` `DELETE /auth/sessions/{id}` | 设备会话管理 |
| 对话 | `POST /chat/query` | **Agent 流式对话（SSE）** |
| 对话 | `POST /chat/rag` | RAG 检索问答 |
| 对话 | `POST /chat/files` `GET /chat/files/{id}` | 附件上传 / 预览 |
| 会话 | `GET /chat/sessions` `DELETE /chat/sessions/{id}` | 会话列表 / 删除 |
| 会话 | `GET /chat/{id}/messages` `PUT /chat/{id}/title` | 历史消息 / 改标题 |
| 笔记 | `GET/POST /note` `GET/PUT/DELETE /note/{id}` | 笔记 CRUD |
| 笔记 | `POST /note/search` | 语义搜索 |
| 笔记 | `GET /note/recycle-bin` `POST /note/{id}/restore` | 回收站 |
| 知识库 | `POST /knowledge/upload` `GET /knowledge/documents` | 文档上传 / 列表 |
| 回顾 | `GET /review/today` `POST /review/{id}/complete` | 艾宾浩斯回顾 |
| 其他 | `GET /note-template` `GET /usage/summary` | 模板 / 用量统计 |

### SSE 事件协议（`POST /chat/query`）

| 事件 | 说明 |
|:---|:---|
| `thinking` | 思考阶段（stage: rag / processing / attachment / thinking） |
| `response` | 逐 token 回复内容 |
| `tool_start` / `tool_end` | 工具调用开始 / 完成（含耗时） |
| `tool_file` | 工具产出文件（PPT / TTS），含 `file_id` 与下载地址 |
| `done` | 流结束，含 `session_id`；RAG 命中时附 `sources` |
| `error` | 错误信息 |

---

## 🧪 测试

```bash
# 后端测试
pip install -r requirements-dev.txt
python -m pytest tests/ -v

# 前端测试
cd front
npm test
npm run lint
npm run build
```

---

## 📄 License

[MIT](LICENSE) © 2026 [Qoin](https://github.com/qiaojoin586-droid)
