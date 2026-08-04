<div align="center">

# ☁️ 云尚 · RAG LearnLittle

**AI 驱动的个人知识管理助手 —— 让笔记拥有记忆，让对话理解一切**

`RAG` `Agent` `多模态` `FastAPI` `LangGraph` `React`

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-LangChain-1C3C3C)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)
![ChromaDB](https://img.shields.io/badge/ChromaDB-1.0%2B-FC60A8)
![Redis](https://img.shields.io/badge/Redis-5%2B-DC382D?logo=redis&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-8%2B-4479A1?logo=mysql&logoColor=white)

</div>

---

## 📖 项目简介

**云尚** 是一款基于 **RAG（检索增强生成）** 的 AI 智能笔记助手。它以你的笔记为知识库，支持 **ReAct / Plan-and-Execute 双 Agent 运行模式**、**深度思考**、**图片 / 视频多模态理解**，并提供笔记模板、回收站、邮件发送、Token 用量追踪等完整工具链 —— 从记录知识到提取知识，一站式完成。

> 🎯 定位：本地优先的私人知识助手。支持 DashScope（阿里云百炼）与 Ollama（完全本地）双模型提供商一键切换。

---

## 🖼️ 界面预览

<!-- ================================================================
     截图区（预留空间，请手动补充）
     👉 将运行截图放入 docs/screenshots/ 目录，然后复制下面的 <img>
        标签替换对应的占位单元格即可。
     示例：
     <img src="docs/screenshots/chat.png" alt="AI 对话" width="48%"/>
     <img src="docs/screenshots/notes.png" alt="笔记管理" width="48%"/>
     <img src="docs/screenshots/login.png" alt="登录注册" width="48%"/>
     <img src="docs/screenshots/plan.png" alt="Plan-and-Execute" width="48%"/>
================================================================= -->

<div align="center">
<table>
  <tr>
    <td width="50%" align="center"><b>🗨️ AI 对话</b><br/><sub>（截图待补充）</sub></td>
    <td width="50%" align="center"><b>🧠 深度思考 / 多模态</b><br/><sub>（截图待补充）</sub></td>
  </tr>
  <tr>
    <td width="50%" align="center"><b>📓 笔记管理</b><br/><sub>（截图待补充）</sub></td>
    <td width="50%" align="center"><b>🗺️ Plan-and-Execute</b><br/><sub>（截图待补充）</sub></td>
  </tr>
</table>
</div>

---

## ⭐ 核心功能

| 模块 | 能力 |
| :--- | :--- |
| 🤖 **双 Agent 模式** | **ReAct**（逐步推理 + 工具调用）与 **Plan-and-Execute**（L1 规则 + L2 LLM 分类器混合路由） |
| 🧠 **深度思考** | 前端开关控制思考模式，质量与延迟可权衡 |
| 🖼️ **多模态理解** | 图片 / 视频附件上传（视频抽帧），视觉模型解答 |
| 📚 **RAG 知识库** | ChromaDB 向量检索 + BM25 混合召回 + bge-reranker 重排序 + LLM 摘要 |
| 🛠️ **Agent 工具层** | 笔记查询、发送邮件（安全校验 + 限流）等，支持审计 |
| 📓 **笔记系统** | 富文本编辑（TipTap）、模板、AI 自动补全 / 打标签 |
| 🗑️ **回收站** | 笔记删除进入回收站，14 天自动彻底清除（定时任务） |
| ✉️ **邮件功能** | QQ 邮箱注册验证，笔记以 Markdown / PDF 导出发送 |
| 💰 **Token 用量追踪** | model_trace 输出总线（log / db / langfuse），成本账单 |
| 🌐 **前端体验** | React 19 + Vite + Tailwind，i18n 国际化，暗 / 亮主题 |
| ✅ **黄金评测器** | tests/eval 自动化评测 AI 对话质量（含安全用例） |

---

## 🏗️ 系统架构

<!-- ================================================================
     架构图预留区（请手动补充）
     👉 将架构图放入 docs/ 目录后，复制下面的 <img> 标签替换占位块即可：
     <img src="docs/系统架构图.png" alt="系统架构图" width="85%"/>
================================================================= -->

<div align="center">
  <b>（架构图待补充）</b>
</div>

- **后端**：FastAPI + SQLAlchemy(async) + MySQL + Redis（会话缓存 / 流式缓冲）
- **Agent 编排**：LangChain / LangGraph，ReAct 与 Plan-and-Execute 双模式
- **检索**：ChromaDB 向量库 + BM25 + CrossEncoder 重排序（BAAI/bge-reranker-v2-m3）
- **模型层**：DashScope（百炼）⇄ Ollama（本地）一键切换；Chat / Thinking / Vision / Classifier / Plan 多模型组合
- **基础设施**：APScheduler 定时任务（回收站清理、孤儿附件清理）、Langfuse 可观测性

---

## 🧰 技术栈

| 层 | 技术 |
| :--- | :--- |
| 前端 | React 19 · TypeScript · Vite · TailwindCSS · TipTap · Zustand · i18next |
| 后端 | Python 3.10+ · FastAPI · uvicorn · APScheduler |
| Agent | LangChain · LangGraph · Langfuse |
| 数据库 | MySQL 8 · Redis · ChromaDB |
| 模型 | DashScope（qwen 系列）/ Ollama（本地）· sentence-transformers · tiktoken |

---

## 🚀 快速开始

### 环境要求

| 依赖 | 版本要求 |
| :--- | :--- |
| Python | ≥ 3.10 |
| Node.js | ≥ 18 |
| MySQL | 8.x（创建数据库 `raglearn`） |
| Redis | 6.x |
| 模型 | 二选一：① 阿里云百炼 `DASHSCOPE_API_KEY` ② Ollama（本地模型） |

### 1️⃣ 配置后端

```bash
# 克隆项目
git clone https://github.com/qiaojoin586-droid/RAG_LearnLittleCode.git && cd RagLearnCode

# 创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt

# 配置环境变量
copy .env.example .env        # Windows
cp .env.example .env          # macOS / Linux
```

编辑 `.env`，至少填写：

```ini
# 模型提供商：dashscope（云）/ ollama（本地）
MODEL_PROVIDER=dashscope
DASHSCOPE_API_KEY=sk-xxxxxx

# 数据库
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=raglearn

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# 邮件（可选，QQ 邮箱授权码，非登录密码）
SMTP_USERNAME=you_qq_email@qq.com
SMTP_PASSWORD=your_smtp_auth_code
```

### 2️⃣ 启动后端

```bash
python main.py
# 或 uvicorn main:app --reload
```

服务启动后：API 文档 → `http://localhost:8000/docs`（默认端口 8000）

### 3️⃣ 启动前端

```bash
cd front
npm install
npm run dev
```

浏览器访问 → `http://localhost:5173`

### 🧪 默认测试账号

| 用户名 | 密码 | 说明 |
| :--- | :--- | :--- |
| `admin` | `admin1234` | 本地开发自动创建 |

> 💡 切换 Embedding 提供商后需**删除并重建 ChromaDB 向量库**；切换模型提供商后需重启服务。

---

## 📁 项目结构

```
RagLearnCode/
├── main.py                  # FastAPI 入口（生命周期 / 中间件 / 路由注册）
├── app/
│   ├── core/                # 日志、异常处理、model_trace、scheduler
│   ├── db/                  # SQLAlchemy、Redis 客户端
│   ├── models/              # ORM 模型（用户 / 笔记 / 知识库 / 模板）
│   ├── rag/                 # RAG 核心（向量库、检索、RagService、任务队列）
│   ├── routers/             # API 路由（chat / note / user / knowledge ...）
│   ├── services/            # 业务服务（笔记、邮件、用量、模板）
│   ├── ai_service/          # Agent 编排（ReAct / Plan-and-Execute / 多模态）
│   ├── utils/               # 模型工厂、Prompt 加载、Token 估算
│   └── schemas/             # Pydantic 模型
├── front/                   # React 19 + Vite 前端
├── prompts/                 # Agent 系统提示词（可配置）
├── tests/eval/              # AI 对话黄金评测器
├── docs/                    # 架构图与升级设计方案
└── requirements.txt
```

---

## ✅ 测试与评测

内置 **AI 对话黄金评测器**：读取 `golden_cases.json`，逐条调用 `/chat/query`（SSE 流式），按关键词判定 PASS/FAIL，覆盖对话、RAG、笔记、安全注入等分类：

```bash
.venv/Scripts/python.exe -X utf8 tests/eval/eval_runner.py [--base-url URL] [--interval 7] [--keep]
```

报告输出至 `tests/eval/results/report_*.json`。

---

## 📚 文档

- [系统架构图](docs/系统架构图.png)
- [ReAct 与 Plan-Execute 混合路由方案](docs/ReAct与Plan-Execute混合路由方案.md)
- [AI 对话栏文件上传功能设计方案](docs/AI对话栏文件上传功能设计方案.md)
- [邮箱验证与笔记回收站功能设计方案](docs/邮箱验证与笔记回收站功能设计方案.md)
- [更多升级设计方案](docs/)

---

## 📄 License

[MIT](LICENSE) © 2026

<!--
TODO 清单：
- [x] 添加 LICENSE 文件（MIT）
- [x] 填写仓库地址
- [ ] 补充界面截图（docs/screenshots/）
- [ ] 补充系统架构图（docs/）
-->
