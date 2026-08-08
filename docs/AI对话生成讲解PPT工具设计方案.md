# AI 对话「选中笔记生成讲解 PPT」工具设计方案

> 版本：v1.6（Phase 1 已实施（2026-08-06），本版同步实施偏差并定稿 Phase 1.5 模板库，修订记录见 §12）  
> 日期：2026-08-06  
> 状态：待评审  
> **代码基准：commit c6f5f81（2026-08-06）**。全文行号已对该 commit 逐一校验；后续重构可能导致行号偏移，引用前请以 commit 为准核对。

---

## 1. 背景与目标

当前 AI 对话已支持在输入框选择**单个/多个笔记**（前端以 `<referenced_notes>` 结构化块附带笔记 ID 与全文），Agent 可基于这些笔记回答、总结、修改。但用户无法直接得到一份**可下载、可讲解的 PPT 文件**。

本方案在现有 Agent 工具体系中新增一个 `generate_ppt_tool` 工具，使 LLM（当前为通义千问 qwen3-max，见 [app/utils/factory.py:344](app/utils/factory.py#L344) `DASHSCOPE_CHAT_MODEL` 默认值；`.env.example` 实际配置为 `qwen3.7-plus`，已覆盖默认值）在用户说「把这几个笔记做成 PPT / 生成讲解幻灯片」时（**v1.4 起可同时指定用户自己上传的 PPT 模板**）：

1. 从数据库按 ID 读取所选笔记（**以 DB 为准，不依赖消息中可能被截断的笔记正文**）；
2. 调用 LLM 生成**结构化 PPT 大纲**（JSON）；
3. 由渲染引擎生成 `.pptx` 文件并落盘；
4. 通过 SSE 推送「PPT 已生成」事件，前端渲染下载按钮，用户点击下载。

目标：

| 维度 | 目标 |
|---|---|
| 交互 | 沿用现有「选择笔记 → 发送」交互，零新增学习成本；v1.4 起支持同时选择用户自己的 PPT 模板 |
| 输出 | 16:9 `.pptx` 文件，含封面、目录、章节页、内容页、演讲者备注 |
| 质量 | 大纲由 qwen3-max 结构化生成，内容忠于笔记原文 |
| 成本 | v1 用免费开源的 python-pptx 渲染；Aspose.Slides Cloud 作为可插拔的高保真引擎（Phase 3） |
| 安全 | PPT 只能访问本人笔记；下载端点走 JWT 鉴权，不挂公开静态目录 |

---

## 2. 现状分析（改造基础）

### 2.1 相关代码路径

> ⚠️ v1.2 定稿后对话链路已重构为三层架构（chat.py 直调 → LangGraph StateGraph），本表为重构后的实际结构。

| 模块 | 位置 | 说明 |
|---|---|---|
| 聊天路由层 | [app/routers/chat.py](app/routers/chat.py) | `/chat/query` SSE 入口：RAG/记忆压缩/引用笔记解析 → 构造 `ChatRouteContext` → 调 `stream_chat_graph` **统一转发全部事件（无白名单）**，仅负责 SSE 格式化 |
| 对话编排层 | [app/ai_service/chat_graph.py](app/ai_service/chat_graph.py) | LangGraph StateGraph（`classify → react\|plan → END`），节点把事件推入 `asyncio.Queue` 事件总线，`stream_chat_graph()` 产出事件流 |
| 执行路由层 | [app/ai_service/chat_route.py](app/ai_service/chat_route.py) | `ChatRouteContext` 执行上下文 + `decide_route` 路由决策 + `react_events()` / `plan_events()` 事件流，**SSE 转发白名单的实际所在处** |
| Agent 工具工厂 | [app/ai_service/agent_tools.py](app/ai_service/agent_tools.py) | `create_agent_tools()`（L58-65）用 `@tool` 定义异步工具，`all_tools` 注册表（L403-415，11 个工具） |
| 工具分组/路由 | [config/agent.yaml](config/agent.yaml) | `tool_groups` 定义分组；`tool_routing.keyword_rules` 关键词命中后追加工具组 |
| 引用笔记解析 | [app/routers/chat.py:425-438](app/routers/chat.py#L425-L438) | 解析 `<referenced_notes>`，把 `- ID: xxx \| 标题: yyy` 注入 system_prompt |
| 流式事件 | [app/ai_service/stream.py](app/ai_service/stream.py) | 产出 `response / tool_start / tool_end / error / stream_done` 事件（`on_tool_end` 处理在 L112-127；`stream_done` 在 chat_route 层被过滤，不达前端） |
| 笔记模型 | [app/models/note.py](app/models/note.py) | `id / user_id / title / content(Markdown) / tags / category / deleted_at` |
| 笔记服务 | [app/services/note_service.py](app/services/note_service.py) | 已有 `get_note`（L102，单条），**缺批量查询，需补充** |
| 模型初始化 | [main.py:50-71](main.py#L50-L71) | `BackgroundInitManager.__init__`：阶段事件 + 轻量服务（`email_service` 的 try/except 初始化先例在 L66-70） |
| 前端 SSE | [front/src/hooks/useSSE.ts](front/src/hooks/useSSE.ts) | 事件分发（`tool_start` 分支 L163 / `tool_end` 分支 L167），需新增 `tool_file` 分支 |
| 笔记选择 UI | [front/src/pages/AIChat.tsx:140-182](front/src/pages/AIChat.tsx#L140-L182) | 已支持多选笔记并拼装 `<referenced_notes>`（拼装逻辑在 L311），**无需改动** |
| 模板 CRUD 先例 | [app/services/note_template_service.py](app/services/note_template_service.py)（`create_template` L25 / `list_templates` L52 / `get_template` L72 / `delete_template` L123）+ [app/routers/note_template_router.py](app/routers/note_template_router.py)（`/note-template` 单数 + `success_response` 风格） | 已有 DB 模板的创建/列表/删除/排序（`NoteTemplate` 模型，`user_id` 外键级联）——**v1.4 克隆为 `PptTemplate` 的现成骨架** |
| 文件存储先例 | [app/services/chat_attachment_service.py](app/services/chat_attachment_service.py) | 二进制文件上传（魔数/大小/配额校验）→ 落盘 `data/.../{user_id}/` → DB 记元数据 → JWT 鉴权——**v1.4 模板文件照搬此模式** |
| 侧边导航 | [front/src/components/layout/Sidebar.tsx:31-38](front/src/components/layout/Sidebar.tsx#L31-L38) | `navItems` 数组，新增「PPT 模板」项 = 加一行 + 新建页面 |
| 静态文件 | [main.py:373-377](main.py#L373-L377) | 仅 `/static/avatars` 公开挂载；PPT 属敏感数据，**不可复用此模式** |

### 2.2 三层架构下的事件链路（含转发白名单差异）

对话链路在 v1.2 定稿后已重构为三层架构（基线 commit c6f5f81），`tool_file` 事件链路必须按下述三层理解：

**第 1 层 — 路由层 [chat.py](app/routers/chat.py) `generate_stream()`**（L461-542）：并行完成 RAG + 记忆压缩 + 附件预处理 → 解析引用笔记（L425-438；v1.4 起同段解析 `<ppt_template>` 块，见 §6.5）→ 构造 `ChatRouteContext`（L512-528）→ 调用 `stream_chat_graph(ctx)` 并**统一转发所有事件**（L533-538），**无任何白名单过滤**，仅做 SSE 格式化。

**第 2 层 — 编排层 [chat_graph.py](app/ai_service/chat_graph.py)**：LangGraph StateGraph `classify → react|plan → END`（`build_chat_graph` L103-123）。节点把事件推入 `asyncio.Queue` 事件总线（`react_node` L78-85 / `plan_node` L88-95），`stream_chat_graph`（L126-180）从队列产出事件流（error 后停止产出）。

**第 3 层 — 执行路由层 [chat_route.py](app/ai_service/chat_route.py)**：`decide_route` 纯函数（L46-59）做路由决策；**SSE 转发白名单的实际所在处**：

- `react_events()`（L62-87）：仅转发 `response / error`（L83），`tool_*` 一律丢弃；
- `plan_events()`（L90-139）：`forwarded` 集合（L108-111）= `plan_*` + `tool_start / tool_end`；另转发 `response / error` 与 `plan_fallback`（降级后接 ReAct 重跑，L128-134）。

| 调用路径 | 事件转发现状 |
|---|---|
| 简单 ReAct（`chat_route.react_events` L82-87） | **只转发 `response / error`**，`tool_start / tool_end` 一律丢弃 |
| Plan 路径（`chat_route.plan_events` L108-111 + L135-139） | 转发 `plan_*` + `tool_start / tool_end` + `response / error` + `plan_fallback`，**不在 `forwarded` 集合的新事件类型同样被丢弃** |

因此 `tool_file` 事件必须 **在 stream.py 产出 + chat_route.py 两处白名单显式加入**（详见 §6.3），否则前端永远收不到。

**Agent 工具路径兼容性**（新增 `ppt` 组后两条路径自动可用）：

- **ReAct（简单查询）**：[agent_runner.py:70](app/ai_service/agent_runner.py#L70) `execute_agent` 走 `resolve_tool_groups(user_message)` 关键词路由（[agent_runner.py:24-67](app/ai_service/agent_runner.py#L24-L67)）→ 在 `agent.yaml` 加 `ppt` 组 + 路由关键词即可自动生效；
- **Plan-and-Execute（复杂查询）**：执行阶段 [plan_execute_agent.py:195-207](app/ai_service/plan_execute_agent.py#L195-L207) `_resolve_step_tool_groups()` 从同一个 `tool_groups` 配置构建「工具名 → 组名」反向映射，新增 `ppt` 组后自动可用；**规划阶段**的工具清单 v1.6 起由 `_build_plan_tool_list()` 从 `tool_groups` 配置**动态构建**注入 `plan_generation.txt` 的 `{tool_list}` 占位（原 prompt 硬编码工具清单，新增工具不被规划 LLM 感知——实施中发现的实际故障，已修复），新工具自动同步；
- **`_execute_step` 事件透传**：对 `execute_agent` 的事件是 **if/elif 之后的 fallthrough `yield event`**（[plan_execute_agent.py:280-281](app/ai_service/plan_execute_agent.py#L280-L281)），`response` / `error` 之外的所有事件（含 `tool_start` / `tool_end`，以及新增的 `tool_file`）都会原样透传，**此层无需改动**。

### 2.3 为什么工具读取笔记而不是靠 LLM 记忆

消息里虽然带笔记全文，但：
- 消息内容可能被截断/过长，直接进 LLM 上下文浪费 token；
- LLM 可能「回忆」错笔记内容（幻觉）。

因此工具内按 ID 从 DB 批量读取（校验 `user_id` + `deleted_at IS NULL`），**内容以数据库为准**。

---

## 3. 总体架构

```
┌─────────────┐ 发送消息(含<referenced_notes>+<ppt_template>) ┌──────────────────────────────┐
│   前端       │ ────────────────────────────────────────────► │ POST /api/v1/chat/query (SSE) │
│ AIChat.tsx  │                                               └──────────────┬───────────────┘
│  笔记多选(已有)│                                                             │ chat.py 路由层
│ PPT模板选择(v1.4新增)│                                                     │ chat_route.py 白名单转发
└─────────────┘                                 │ chat_graph.py 编排层       │
      ▲                                       (classify → react|plan)         │
      │ ① tool_file 事件(下载链接)                                 ▼
      │ ② 渲染下载卡片                              Agent 调用 generate_ppt_tool
      │                                 （chat_route.py 白名单转发）          │
      │                                     ┌────────────▼────────────┐
      │                                     │      PptService         │
      │                                     │  0. 读取用户PPT模板(可选) │
      │                                     │  1. 批量读取笔记(DB)      │
      │                                     │  2. qwen3-max 生成大纲JSON│
      │                                     │  3. 渲染引擎生成 .pptx    │
      │                                     │  4. 落盘 data/ppt/       │
      │                                     └────────────┬────────────┘
      │                                                  │ 返回 {file_id, download_url}
      │              ┌───────────────┐                    │
      └───────────── │ GET /api/v1/  │ ◄───────────────────┘
      (带JWT下载)     │ ppt/{file_id} │
                     └───────────────┘
                     (JWT 鉴权 + 归属校验 + FileResponse)
```

**核心思路**：`生成大纲（LLM 结构化输出）` + `渲染（确定性代码）` 分离 —— LLM 只负责"想内容"，渲染引擎负责"画版式"，避免 LLM 直接输出不可控的 pptx 二进制。

**实现要点**：SSE 事件经 LangGraph StateGraph（[chat_graph.py](app/ai_service/chat_graph.py)，classify → react|plan）编排、[chat_route.py](app/ai_service/chat_route.py) 白名单转发后到达前端（完整链路见 §6.3）。

---

## 4. 工具设计

### 4.1 工具签名

在 [app/ai_service/agent_tools.py](app/ai_service/agent_tools.py) 的 `create_agent_tools()`（L58-65）中新增（工厂注入 `ppt_service` 参数，模式与 `note_service`/`review_service`/`email_service` 一致）：

```python
@tool
async def generate_ppt_tool(
    note_ids: str,       # 必填：笔记 ID，逗号分隔（如 "id1,id2,id3"），须来自用户引用的笔记
    title: str = "",     # 可选：PPT 主题，默认由 LLM 根据笔记内容拟定
    style: str = "business",  # 可选：风格预设 business / academic / minimal
    template_id: str = "",    # 可选（v1.4）：用户选择的 PPT 模板 ID（<ppt_template> 内提供的），为空时用默认版式
) -> str:
    """
    根据用户选中的一篇或多篇笔记，生成一份讲解用 PPT（.pptx 文件）。
    适用场景：用户说「把这几篇笔记做成PPT / 生成讲解幻灯片 / 整理成演示文稿」。
    注意：note_ids 必须是用户引用笔记中的 ID（<referenced_notes> 内提供的），
    逗号分隔，可一次传入多篇，每篇笔记会生成独立的章节。
    template_id 须来自用户消息中的 <ppt_template> 块（见 §6.5），为空时按默认版式生成。
    返回 JSON 字符串，包含 file_id、download_url、slide_count、title。
    """
```

**为什么 `note_ids` 用逗号分隔字符串而不是 `list[str]`（审查问题 5）**：
- 本项目所有工具的参数均为标量类型，且已有先例 —— `create_note_tool` / `update_note_tool` 的 `tags` 参数就是「逗号分隔字符串」（[agent_tools.py:242](app/ai_service/agent_tools.py#L242)、[agent_tools.py:268](app/ai_service/agent_tools.py#L268)）；
- 避免 LangChain `@tool` + 数组类型 JSON Schema 与 qwen3-max function calling 的兼容性不确定性；
- 工具内部 `[i.strip() for i in note_ids.split(",") if i.strip()]` 解析，与 `create_note_tool` 的 tags 解析方式完全一致，LLM 出错率最低。

**为什么 `note_ids` 由 LLM 传参而不是从消息里解析**：与现有 `update_note_tool` 的惯例一致（LLM 从 system_prompt 中 `referenced_notes` 拿到 ID 后填入参数），工具内部再强校验归属，双保险。

**`template_id`（v1.4）同理**：前端把用户选中的模板以 `<ppt_template>` 块拼进消息（见 §6.5），chat.py 解析后注入 system_prompt（与 `referenced_notes` 同段），LLM 填入工具参数；工具内强校验归属（`user_id` 匹配）。**LLM 漏传时静默降级默认版式，不阻断生成**。

### 4.2 注册与路由（config/agent.yaml）

```yaml
tool_groups:
  ppt:
    - generate_ppt_tool

tool_routing:
  keyword_rules:
    ppt:
      - "PPT"
      - "ppt"
      - "幻灯片"
      - "演示文稿"
      - "做个ppt"
      - "生成ppt"
      - "讲解ppt"
      - "整理成ppt"
```

> 注意：`讲解` 单独作为关键词误伤率较高（如「帮我讲解一下这个概念」），建议只用组合词，或加「命中时消息长度 ≥ 10 字符」的守卫。`ppt` 组不加入 `default_groups`（[agent.yaml:133-138](config/agent.yaml#L133-L138) 现为全量加载），保持轻量工具集（qwen3-max 的工具 schema 越少，幻觉率越低）。

### 4.3 工具执行流程（PptService.generate）

```python
async def generate(
    self, db, user_id: str, note_ids: List[str],
    title: str = "", style: str = "business",
    template_id: str = "", note_service=None,
) -> str:
    """生成讲解 PPT（返回 JSON 字符串，供工具直接返回给 LLM）。

    v1.6 实施同步：db（经 db_session_factory 创建）与 note_service
    （工具闭包持有）由 generate_ppt_tool 调用时透传，PptService 不持有两者引用。
    """
    # ① 参数校验与上限
    ids = [i.strip() for i in note_ids.split(",") if i.strip()]
    if not 1 <= len(ids) <= MAX_NOTES(10):
        return error("一次最多选择 10 篇笔记")

    # ①' 读取用户 PPT 模板（可选，v1.4，见 §6.5）
    #     归属校验 + 存在性；模板缺失/损坏/无权限 → 返回 None，降级默认版式（不阻断生成）
    #     self.ppt_template_service 为构造注入（方案 A，见 §6.5），不属于 Agent 工具透传链
    template_path = None
    if template_id:
        template_path = await self.ppt_template_service.resolve_template_path(
            db, user_id, template_id)

    # ② 批量读取笔记（新增 NoteService.get_notes_by_ids，见 §6.4）
    notes = await note_service.get_notes_by_ids(db, note_ids, user_id)   # 过滤已删除，静默忽略无效 ID
    if not notes:
        return error("未找到对应笔记，请确认所选笔记未被删除")

    # ③ 内容截断与组装上下文（每篇 ≤ per_note_chars 字，合计 ≤ total_context_chars）
    context = build_ppt_context(notes)          # 截断规则见 5.4

    # ④ qwen3-max 生成结构化大纲（JSON mode，outline_timeout 超时，解析失败重试 outline_retries 次，
    #    仍失败 → 纯文本大纲按章节模板渲染，§10）
    #    LLM 实例获取方式见下方「LLM 获取路径」
    outline = await llm_generate_outline(context, title, style, notes)

    # ⑤ 渲染引擎生成 .pptx 字节流（同步库，必须进线程池，见 §5.5；template_path 见 §5.6）
    pptx_bytes = await asyncio.to_thread(
        renderer.render, outline, theme=style, template_path=template_path)

    # ⑥ 落盘 + 元数据 + TTL/配额清理 + 返回下载信息
    file_id = save_ppt_file(user_id, title, pptx_bytes)   # data/ppt/{user_id}/{file_id}.pptx
    return json.dumps({
        "file_id": file_id,
        "download_url": f"/api/v1/ppt/{file_id}",
        "slide_count": len(outline.slides),
        "title": outline.title,
        "note_count": len(notes),
    }, ensure_ascii=False)
```

#### LLM 获取路径（审查问题 3）

`PptService` **不持有模型引用**，与模型实例零耦合：

- `PptService.__init__(config, ppt_template_service)` 只保存配置、路径与模板服务引用（均为轻量对象，可在 `BackgroundInitManager.__init__` 中同步创建，见问题 8 / §6.4；模板服务注入见 §6.5 方案 A）；
- `generate()` 内通过**函数内延迟导入**获取模型（与 [chat.py:475](app/routers/chat.py#L475) / [chat.py:499](app/routers/chat.py#L499) 的既有模式一致——`build_attachment_blocks_async`、`ReviewService` 均在函数内导入，避免模块级循环导入）：

```python
# app/services/ppt_service.py 内部
def _get_chat_model(self):
    from main import init_manager   # 延迟导入，复用全局管理器的模型实例
    model = init_manager.chat_model
    if model is None:
        raise PptError("AI 模型未就绪，请稍后重试")
    return model
```

- 大纲生成使用独立的 `ChatOpenAI` 调用（复用 `DASHSCOPE_BASE_URL` / `DASHSCOPE_API_KEY`，见 [factory.py:322](app/utils/factory.py#L322)），`response_format={"type": "json_object"}` + Pydantic 校验；
- 不选择「把 `chat_model` 一路透传到工具工厂」的方案：需要穿透 `chat_route` → `execute_agent` / `execute_plan_agent` → `_execute_batch` → `_execute_step` 多层签名，收益有限。注意 `ppt_service` **则必须**走这条显式注入链路（与 `note_service`/`review_service`/`email_service` 一致，见 §6.4）；而 `ppt_template_service` **不**走此链——它是 `PptService` 的构造依赖（方案 A，§6.5），Agent 工具层无需感知。

### 4.4 大纲 Schema（app/schemas/ppt.py）（审查问题 10）

```python
from typing import List, Optional, Literal
from pydantic import BaseModel, Field

class PPTSlide(BaseModel):
    type: Literal["cover", "agenda", "section", "content", "summary"]
    title: str
    subtitle: Optional[str] = None       # cover / section 用
    items: Optional[List[str]] = None     # agenda 目录项
    bullets: Optional[List[str]] = None   # content 要点
    code: Optional[str] = None            # content 代码块
    notes: Optional[str] = None           # 演讲者备注

class PPTOutline(BaseModel):
    title: str
    subtitle: str = ""
    style: Literal["business", "academic", "minimal"] = "business"
    # v1.6 实施同步：min_length 不放字段层 —— 字段约束先于 after validator 执行，
    # LLM 返回 2 页（content+summary）会被直接拒绝，「自动插封面」修复没有机会运行；
    # 最小页数校验移入 validate_structure 内（修复后再校验）
    slides: List[PPTSlide] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_structure(self):
        """结构约束（审查问题 4）：首页必须封面、必须含内容页、总结页必须在最后、
        修复后页数 ≥3。采用自动修复而非抛错 —— 避免二次调用 LLM，保证确定性；
        仅「缺 content 页」「修复后不足 3 页」抛错走重试/降级。"""
        types = [s.type for s in self.slides]

        # ① 首页不是 cover → 自动在最前面插入封面（用大纲 title/subtitle）
        if not types or types[0] != "cover":
            self.slides.insert(0, PPTSlide(
                type="cover", title=self.title, subtitle=self.subtitle))

        # ② 缺少 content → 抛错走重试/降级（无法自动生成内容）
        if "content" not in [s.type for s in self.slides]:
            raise ValueError("大纲至少需要包含一个内容页")

        # ③ summary 不在最后 → 移到末尾（并移除中间的重复 summary）
        summaries = [s for s in self.slides if s.type == "summary"]
        self.slides = [s for s in self.slides if s.type != "summary"] + summaries

        # ④ 修复后仍不足 3 页（封面 + 内容页 + 总结页的最小结构）→ 抛错
        if len(self.slides) < 3:
            raise ValueError("大纲页数不足（至少需要封面、内容页与总结页）")
        return self
```

- `type ∈ {cover, agenda, section, content, summary}`，渲染引擎按类型走固定版式；
- 每篇笔记默认对应 1 个 `section` + 1~3 个 `content`，总页数上限 20（`max_slides` 可配）；
- 解析失败（`ValidationError` / `JSONDecodeError`）自动重试 1 次，仍失败则降级为纯文本大纲按章节模板渲染（见 §10）；
- 大纲生成 Prompt 强调**忠于笔记内容、不要编造**。

---

## 5. 渲染引擎选型：python-pptx vs Aspose.Slides Cloud

### 5.1 对比

| 维度 | python-pptx（本地开源） | Aspose.Slides Cloud API |
|---|---|---|
| 成本 | 免费，MIT | 商业 SaaS，按 API 调用计费（有试用额度） |
| 依赖 | `pip install python-pptx` | `pip install asposeslidescloud` + 网络 + App SID/Key |
| 保真度 | 基础版式可控，适合文本型讲解稿 | 高，支持设计模板（.pptx 模板填占位符）、图表、公式 |
| 中文 | 直接写字体名（微软雅黑等），打开时本地渲染，无字体问题 | 云端渲染，字体策略需配置 |
| 版式控制 | 手写坐标/尺寸，自由度低但确定性 100% | 模板驱动，版式精美但灵活性受限 |
| 离线可用 | ✅ | ❌ 云端调用，故障时降级 |
| 学习成本 | 低（约 200 行渲染代码） | 中（异步任务 + 下载结果两段式） |
| 适合本需求 | 讲解型 PPT（标题+要点+备注）完全够用 | 需要公司级设计模板/配图时再上 |

### 5.2 抽象接口（为 Aspose 预留）

```python
# app/services/ppt_renderer.py
class PPTRenderer(Protocol):
    def render(self, outline: PPTOutline, theme: str,
               template_path: Optional[str] = None) -> bytes: ...

# 实现一（v1 默认）：PythonPptxRenderer —— 本地 python-pptx（用户模板有限支持，见 §5.6）
# 实现二（Phase 3 可选）：AsposeCloudRenderer —— 用户模板完整支持（模板渲染模式，见 §5.6）
```

通过 `PPT_ENGINE=python_pptx|aspose_cloud` 环境变量切换，业务代码无感知。

### 5.3 python-pptx 版式规则（v1）

- 页面：16:9（13.33 × 7.5 英寸）；
- 风格预设（`business` 蓝白 / `academic` 米白 / `minimal` 黑白）定义在 `config/ppt.yaml`：主色、背景色、正文字体（微软雅黑）、标题字号（32~44pt）、正文（18~24pt）；
- 版式：封面页（大标题+副标题+日期）、目录页（要点列表）、章节页（色带大标题）、内容页（标题栏 + 项目符号，超出自动分页、代码块等宽字体）、总结页；
- **每页写入演讲者备注**（`slide.notes_slide`），讲解场景刚需；
- Markdown 转义：笔记正文里的 `#`/`*`/`` ` `` 等 Markdown 语法在 bullets 里做轻量清洗（去重符号、提取行首要点），不解析为富文本。

### 5.4 内容截断规则

- 单篇笔记内容截断 ≤ 2000 字符：保留标题层级、列表、首段与结论段，代码块超过 40 行折叠为「……（已省略）……详见笔记」；
- 全部笔记合计 ≤ 12000 字符（约 6k~8k tokens），控制在 qwen3-max 上下文（32k）内；
- 截断只影响「生成大纲」这一次调用，不修改笔记本身。

### 5.5 同步渲染不阻塞事件循环（审查问题 4）

`python-pptx` 基于 lxml，是纯同步库，`render()` 直接调用会**阻塞整个 asyncio 事件循环**（同进程所有 SSE 连接和 API 请求都会被卡住）。必须在 `generate()` 中放入线程池：

```python
# 同步渲染 → 线程池执行，异步等待
pptx_bytes = await asyncio.to_thread(renderer.render, outline, theme=style)
```

渲染耗时 <2s，线程池方案代价可忽略；后续若换成 Aspose Cloud（httpx 异步 SDK），`render()` 改为 async 签名，接口层用 `async def` 统一。

### 5.6 用户 PPT 模板支持策略（v1.4 新增，v1.6 扩展为四级降级链）

用户可在侧边栏「PPT 模板」页上传自己的 .pptx 模板，对话时与笔记一起选中（管理链路见 §6.5）。**渲染引擎对模板的支持随引擎升级**，抽象接口（§5.2）不变：

| 阶段 | 引擎 | 模板支持 | 能力边界 |
|---|---|---|---|
| **v1** | `PythonPptxRenderer` | **四级降级链**（见下） | T1 命名页精确 / T2 识别覆盖 / T3 母版优先 / 默认版式 |
| **Phase 3** | `AsposeCloudRenderer` | **完整支持（已实施，2026-08-07）** | 官方 `POST /slides/{name}/fromTemplate` 模板渲染：`{{key}}` 占位符 + **XML 数据**（JSON → 服务器 500）+ `{{agenda}}`/`{{sections}}` 循环容器（变长页数）；模板上传 Aspose 存储（md5 缓存）后按 `templatePath` 渲染。**无占位符模板（纯设计模板）自动降级本地 T2/T3** |

**v1 模板渲染四级降级链（v1.6 实施）**：

```
模板打开成功？
 ├─ T1 命名页+占位符：模板含 cover/agenda/section/content/summary 命名页
 │      → 复制命名页 + {{key}} 替换                  [精确模式]
 ├─ T2 内容覆盖（识别+替换）：无命名页但含可识别文本
 │      → 保留每页布局，识别标题/正文框并覆盖为新内容  [常规模板路径，如用户 4.pptx]
 ├─ T3 母版优先：无文本或识别失败
 │      → 删除内容页（含 part），保留母版/版式，
 │        用模板版式新建标准讲解页                    [设计语言继承兜底]
 └─ 模板损坏（Presentation 打不开）
       → 默认版式（render() 外层兜底）
```

**T2 识别规则（v1.6 实施，spike 校准）**：

- **标题识别**：① 角色优先——标题占位符（`placeholder idx==0`）直接命中；② 无占位符 → 视觉得分 = 字号 + 位置（上 30% 加权）+ Z 序（靠前加权），排除长文本（>60 字）/ 纯数字编号（如「01」章节大编号）/ 小字号（<14pt）/ 底部 10% 区域；
- **副标题**：主标题框下方 0.5 英寸内、字号最大的框；
- **正文框**：剩余文本框 − 页脚（底部 10%）− 短文本（1-5 字，非上半区）− 图注（<10pt）；
- **段落拆分**：段落含项目符号（`buChar`/`buAutoNum`）或短文本 → 拆 bullets；长段落保留结构；
- **复杂布局降级**：content/summary/section 页正文框 ≥ 4（卡片/数据布局，或页序错配）→ 该页降级 T3 标准页（不破坏布局）；
- **目录卡片**：每框填一个 item（保留卡片布局）；
- **覆盖格式**：保留原 run 的字体/颜色/字号（`_set_para_text`），无残留模板示例文本；
- **页映射（顺序对应）**：outline 首页 → 模板第 1 页、末页 → 模板末页、中间按序；模板页不足 → 该页标准版式；精确映射需命名页（T1）或后续交互配置。

**降级兜底（逐级退）**：

1. 模板缺失/无权限（`resolve_template_path` 校验失败）→ 按默认版式生成，不报错；
2. T1 无命名页 → T2；T2 失败/无文本 → T3；T3 失败 → 默认版式；
3. 模板文件损坏/无法打开（`Presentation()` 抛错）→ 默认版式，`logger.warning` 记录。

**v1 能力边界（已知，文档记录）**：表格/图表页仅覆盖标题（数据不重填）；卡片布局页降级标准版式；页序对应非精确映射。

**主题色保留（v1.6 修复）**：T1/T2 采用**原地修改模板**（直接在模板文件上覆盖文本/重排页序/丢弃多余页，含同文件复制命名页），主题/母版/版式/背景**完整保留**——不再「复制到新演示文稿」（跨文件 deepcopy 会把 `schemeClr` 主题色引用解析到默认主题，导致色调改变，实测 4.pptx 首页 7 个色块全部一致）。

---

## 6. 文件存储、下载与 SSE 事件链路

### 6.1 存储

```
data/ppt/
└── {user_id}/
    ├── {file_id}.pptx          # file_id = uuid4().hex
    └── {file_id}.json          # 元数据: {title, slide_count, created_at, size, engine}

data/ppt_templates/             # v1.4 新增：用户 PPT 模板（用户资产，永久保留）
└── {user_id}/
    └── {template_id}.pptx      # 模板文件（元数据存 MySQL ppt_templates 表，见 §6.5）
```

- 元数据用 JSON sidecar，不建新表（**仅限 `data/ppt/` 临时产物**，不进 MySQL；`data/ppt_templates/` 模板元数据走 MySQL，见 §6.5）；
- **TTL 24 小时**：启动时后台任务 + 下载命中时惰性清理，删除过期文件（**模板不参与 TTL**）；
- 配额：每用户最多保留 20 个文件，超限删最旧（防磁盘膨胀）。

### 6.2 下载端点（新增 app/routers/ppt_router.py）

```python
@router.get("/ppt/{file_id}")
async def download_ppt(file_id: str, user_id: str = Depends(get_current_user_id)):
    # ① file_id 必须匹配 ^[0-9a-f]{32}$，防路径穿越
    # ② 读取 {user_id}/{file_id}.json，校验归属（sidecar 不存在 → 404）
    # ③ FileResponse(path, filename=f"{title}.pptx", media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")
```

**只用参数级 `Depends`（审查问题 1）**：`get_current_user_id` 是返回 `user_id` 字符串的依赖（[auth_utils.py:356](app/utils/auth_utils.py#L356) 起），参数级注入即可用于归属校验；若同时写 `dependencies=[...]` 会**重复执行两次 JWT 解码 + 两次 DB 会话**，且装饰器级返回值被丢弃，纯属冗余。项目内所有端点（如 [chat.py:32](app/routers/chat.py#L32) 导入的 `get_current_user_id`）均只用参数级写法，保持一致。

- **不走公开静态目录**（`/static/avatars` 是公开的，PPT 含用户笔记内容，必须 JWT 鉴权）；
- 在 [main.py:346-371](main.py#L346-L371) 路由注册区追加：`app.include_router(ppt_router.router, prefix=API_PREFIX, tags=["PPT"])`。

### 6.3 SSE 事件链路（端到端 —— 实施时最易遗漏的坑）

`tool_file` 事件的完整链路分 **3 段**，每一段都必须打通：

**第 1 段：stream.py 产出**（[app/ai_service/stream.py:112-127](app/ai_service/stream.py#L112-L127)）

langgraph v2 的 `on_tool_end` 事件 `data` 字段带 `output`（工具返回值），当前代码完全没读。在 L127 产出 `tool_end` 之后新增解析。**v1.6 实施同步：解析逻辑实现为独立函数 `parse_tool_file_event(tool_name, tool_output)`（可单测），语义与下方代码一致**：

```python
elif event_type == "on_tool_end":
    tool_name = event.get("name", "unknown")
    # ... 现有 duration 计算与 tool_end 产出不变（L112-127）...
    yield {"type": "tool_end", "name": tool_name, "duration_ms": duration}

    # ★ 新增：检测 PPT 工具输出，额外产出 tool_file 事件
    if tool_name == "generate_ppt_tool":
        tool_output = event.get("data", {}).get("output", "")
        try:
            file_info = json.loads(tool_output)   # 工具返回 JSON 字符串
            if "file_id" in file_info:
                yield {"type": "tool_file", "name": tool_name, **file_info}
        except (json.JSONDecodeError, TypeError):
            pass   # 工具返回了错误提示（非 JSON），跳过，LLM 会在文本里说明
```

**第 2 段：chat_route.py 转发白名单**（两处都要加，见 §2.2）

- **Plan 路径** —— `plan_events()` 的 `forwarded` 集合（[chat_route.py:108-111](app/ai_service/chat_route.py#L108-L111)）加入 `"tool_file"`：

```python
forwarded = {
    "plan_start", "plan_step", "plan_step_start", "plan_step_end",
    "plan_synthesize", "plan_complete", "tool_start", "tool_end",
    "tool_file",   # ★ 新增
}
```

- **简单 ReAct 路径** —— `react_events()`（[chat_route.py:82-87](app/ai_service/chat_route.py#L82-L87)）当前**连 `tool_start/tool_end` 都不转发**，本次顺带补上工具事件转发：

```python
event_type = event.get("type", "")
if event_type in ("response", "error"):
    yield event
    if event_type == "error":
        return
elif event_type in ("tool_start", "tool_end", "tool_file"):   # ★ 新增
    yield event
# stream_done 等其余事件不转发（与现状一致）
```

> ⚠️ **行为变更提示（审查问题 3）**：简单路径此前从不转发工具事件，前端 `onToolStart/onToolEnd` 只在 Plan 路径触发过。补上转发后，简单对话中 `search_notes_tool` 等工具也会显示状态指示。已核实前端实现为**轻量 state 更新**（[AIChat.tsx:460-465](front/src/pages/AIChat.tsx#L460-L465)：`setCurrentTool(name)` / `setCurrentTool('')`，无全屏遮罩），不会闪烁或遮挡；但 UI 上展示的是**原始工具名**（如 `generate_ppt_tool`），需在 `tool_start` 分支做中文名映射（见 §7）。对 PPT 场景这同时是生成中的进度指示（工具运行约 30s 期间状态持续可见，正好补上 §7 的进度反馈）。

- **Plan 分支内层 `_execute_step`** 已是全量透传（if/elif 之后的 fallthrough `yield event`，[plan_execute_agent.py:280-281](app/ai_service/plan_execute_agent.py#L280-L281)），`tool_file` 自动穿过，**无需改**。

**第 3 段：前端 useSSE 消费**（见 §7）

**兜底**：即便 `tool_file` 事件因任何原因丢失，工具的返回串（含 download_url）对 LLM 可见，LLM 的文本回复中也会提到「PPT 已生成」，前端渲染链接仍有兜底。

### 6.4 注入链路（审查问题 6）

`ppt_service` 与现有 `note_service`/`review_service`/`email_service` 走**完全相同的显式参数透传**方式（不引入新的 `agent_kwargs` 模式，保持项目现有风格；待未来工具增多再统一重构为依赖字典）。

**关键通道**：`ChatRouteContext`（[chat_route.py:27-43](app/ai_service/chat_route.py#L27-L43)）是 `ppt_service` 从 chat.py 传递到 `react_events()` / `plan_events()` 的唯一通道，先补字段：

```python
@dataclass
class ChatRouteContext:
    ...
    email_service: Any = None
    ppt_service: Any = None          # ★ 新增（PPT 工具服务）
    attachment_content: list = field(default_factory=list)
    ...
```

**`ppt_service` 完整注入链路（10 处）**——`ppt_template_service` 不在此链（方案 A：构造注入，见 §6.5）：

| 位置 | 当前签名/调用 | 改动 |
|---|---|---|
| [chat_route.py:27-43](app/ai_service/chat_route.py#L27-L43) `ChatRouteContext` | 无 `ppt_service` 字段 | 新增 `ppt_service: Any = None` |
| [chat_route.py:62-87](app/ai_service/chat_route.py#L62-L87) `react_events()` | 调用 `execute_agent`（L69-81） | 补传 `ppt_service=ctx.ppt_service` |
| [chat_route.py:90-139](app/ai_service/chat_route.py#L90-L139) `plan_events()` | 调用 `execute_plan_agent`（L112-126） | 补传 `ppt_service=ctx.ppt_service` |
| [chat.py:512-528](app/routers/chat.py#L512-L528) | 构造 `ChatRouteContext` | 传入 `ppt_service=init_manager.ppt_service` |
| [agent_tools.py:58-65](app/ai_service/agent_tools.py#L58-L65) `create_agent_tools()` | 已有 `note_service=None, review_service=None, email_service=None, db_session_factory=None, groups=None` | 新增 `ppt_service=None`，闭包捕获并注入新工具 |
| [agent_runner.py:70-83](app/ai_service/agent_runner.py#L70-L83) `execute_agent()` | 透传 4 个 service | 新增 `ppt_service=None` 参数并透传给 `create_agent_tools`（L117-124） |
| [plan_execute_agent.py:210-224](app/ai_service/plan_execute_agent.py#L210-L224) `_execute_step()` | 同上 | 新增 `ppt_service=None`，透传给内部 `execute_agent`（L259-272） |
| [plan_execute_agent.py:324-338](app/ai_service/plan_execute_agent.py#L324-L338) `_execute_batch()` | 透传 4 个 service | 新增 `ppt_service=None`，透传给两处 `_execute_step` 调用（L356 并行 / L388 顺序） |
| [plan_execute_agent.py](app/ai_service/plan_execute_agent.py) `execute_plan_agent()` | 接收 4 个 service | 新增 `ppt_service=None`，透传给 `_execute_batch`（L539-553） |
| [main.py:50-71](main.py#L50-L71) `BackgroundInitManager.__init__` | 轻量服务初始化（`email_service` 先例 L66-70） | 同步创建 `self.ppt_template_service = PptTemplateService()` 与 `self.ppt_service = PptService(load_ppt_config(), self.ppt_template_service)`（**均不持有模型**，见问题 3/8；模板服务注入见 §6.5 方案 A） |

**初始化策略（审查问题 8）**：`PptService` 是轻量对象（只读配置 + 目录初始化，不依赖模型），在 `BackgroundInitManager.__init__`（阶段 0）同步创建即可 —— 完全参照 `email_service` 的 try/except 模式（[main.py:66-70](main.py#L66-L70)，失败仅告警、功能降级）；`chat_model` 在阶段 1 才就绪，故 `generate()` 内部延迟从 `init_manager` 获取（§4.3）。**v1.5：`ppt_template_service` 与 `PptService` 同阶段创建、构造注入（方案 A，§6.5），两处均参照 `email_service` 模式包裹 try/except。**

### 6.5 PPT 模板管理（v1.4 新增）

**模型**（新增 `app/models/ppt_template.py`，参照 `NoteTemplate`）：`ppt_templates` 表 —— `id`（自增）+ `user_id`（外键 users.uuid，级联删除）+ `name` + `file_size` + `created_at` + `updated_at` + `deleted_at`（`updated_at` 与 `NoteTemplate` 保持一致，为未来重命名等编辑预留）。**模板是用户资产，永久保留**（不进 TTL，区别于 §6.1 的临时产物）。

**服务**（新增 `app/services/ppt_template_service.py`，参照 `note_template_service` + `chat_attachment_service`）：

- `resolve_template_path(db, user_id, template_id: str)` —— 归属校验 + 返回文件路径（供 `PptService.generate` 调用，§4.3 ①'）。**`template_id` 参数为字符串**（工具参数惯例，§4.1）：DB 主键为自增整数，方法内部 `int(template_id)` 后查询（非法值/越权 → 返回 None）；
- 上传：校验 `.pptx` 魔数（zip 头 `PK\x03\x04`）+ 大小 ≤ `max_template_size_mb`（10MB）+ 每用户 ≤ `max_templates_per_user`（20 个）→ 落盘 `data/ppt_templates/{user_id}/{template_id}.pptx` → 写 DB；
- 列表 / 删除（删文件 + 删记录）。

**注入路径（方案 A，v1.5 明确）**：`ppt_template_service` **不进 §6.4 的 10 处工具透传链**——它是 `PptService` 的**构造依赖**：

```python
# main.py BackgroundInitManager.__init__（阶段 0，参照 email_service 模式）
self.ppt_template_service = PptTemplateService()
self.ppt_service = PptService(load_ppt_config(), self.ppt_template_service)
```

理由：模板解析是 `PptService` 内部行为，Agent 工具层（`react_events` / `plan_events` / `execute_agent` 等）无需感知；两者生命周期相同（阶段 0 轻量创建），构造注入最简洁。

**端点**（新增 `app/routers/ppt_template_router.py`，注册进 [main.py:346-371](main.py#L346-L371) 路由区；**路径与响应风格对齐 [note_template_router.py](app/routers/note_template_router.py) 先例：单数 `/ppt-template` + 统一 `success_response()` 包装**）：

| 端点 | 说明 |
|---|---|
| `POST /api/v1/ppt-template/upload` | multipart 上传（file + name），参数级 `Depends(get_current_user_id)`，`success_response` 返回模板信息 |
| `GET /api/v1/ppt-template` | 列表（id / name / file_size / created_at），`success_response` 包装 |
| `DELETE /api/v1/ppt-template/{template_id}` | 删除（归属校验 + 删文件），`success_response` 返回删除提示 |

**对话链路**（与笔记选择完全平行）：

1. 前端 [AIChat.tsx](front/src/pages/AIChat.tsx) 增加「PPT 模板」单选（仿笔记选择面板 L140-182），发送消息中拼装：

```
<ppt_template>
- ID: 12 | 名称: 公司培训模板
</ppt_template>
```

2. [chat.py:425-438](app/routers/chat.py#L425-L438) 与 `<referenced_notes>` 同段解析 `<ppt_template>` 块，注入 system_prompt（提示 LLM 生成 PPT 时携带该模板 ID）；
3. LLM 将 `template_id` 填入 `generate_ppt_tool`（§4.1），工具内 `resolve_template_path` 强校验归属（双保险）。

**v1 不做**：模板在线预览/缩略图（列表仅展示名称/大小/日期）、模板编辑（上传后只能删除重传）、共享模板（先做个人模板，需要时再扩展）。

---

## 7. 前端改造（front/）

| 文件 | 改动 |
|---|---|
| [front/src/types/api.ts:317-339](front/src/types/api.ts#L317-L339) | `ChatSSEMessage.type` 联合类型（L318-322）追加 `'tool_file'`；扩展字段 `file_id` / `download_url` / `slide_count`；`SSECallbacks` 增 `onToolFile` 回调 |
| [front/src/hooks/useSSE.ts:14-36](front/src/hooks/useSSE.ts#L14-L36) | `SSECallbacks` 增加 `onToolFile?`；`switch` 增加 `case 'tool_file':` → `callbacks.onToolFile?.(data)`；`tool_start` 分支（L163）增加**工具名中文映射**（`generate_ppt_tool` → 「正在生成 PPT」，其他工具 → 显示名），`tool_end`（L167）后清除 |
| [front/src/pages/AIChat.tsx](front/src/pages/AIChat.tsx) | ① 监听 `onToolFile`，在助手气泡下方渲染「📄 已生成讲解 PPT（N 页）」+ 下载按钮；② 下载走 JWT 鉴权 fetch（现有 `onToolStart`/`onToolEnd` 在 L460-465）；③（v1.4）增加「PPT 模板」单选面板（仿笔记选择 L140-182），拼装 `<ppt_template>` 块（§6.5） |
| [front/src/components/layout/Sidebar.tsx:31-38](front/src/components/layout/Sidebar.tsx#L31-L38)（v1.4） | `navItems` 新增 `/ppt-templates` 项（图标 `Presentation`，文案 `nav.ppt_templates`） |
| [front/src/pages/PPTTemplates.tsx](front/src/pages/PPTTemplates.tsx)（v1.4，新增页） | 模板库：上传（.pptx + 名称 + 大小/数量校验提示）+ 列表 + 删除；路由 `/ppt-templates` |

笔记多选、`<referenced_notes>` 拼装（[AIChat.tsx:311](front/src/pages/AIChat.tsx#L311)）均已存在，**零改动**。

**进度反馈（审查问题 7）**：`tool_start` 事件的 name 为 `generate_ppt_tool` 时，前端在工具状态区显示「🖼 正在生成 PPT（约需 20~30 秒）…」。**v1 不做工具执行中的增量 `thinking` 事件** —— 当前 `astream_events` 流式设计下，工具在 ToolNode 内部执行，`on_tool_start` 与 `on_tool_end` 之间不会产生任何中间事件，stream.py 无法感知工具内部进度；如需真实进度（如「大纲完成 / 渲染中」），Phase 2 可通过回调 + 队列 + 独立 SSE 通道实现，v1 用前端文案即可避免用户误以为卡死。

**下载实现（审查问题 11）**：

```typescript
const downloadPpt = async (file: ToolFileInfo) => {
  try {
    const res = await fetch(file.download_url, {
      headers: { Authorization: `Bearer ${getToken()}` },  // JWT 鉴权，不能用 <a href>
    });
    if (!res.ok) {
      throw new Error(res.status === 404 ? '文件已过期，请重新生成' : `下载失败(${res.status})`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${file.title || '讲解PPT'}.pptx`;   // 文件名取自 tool_file 事件的 title
    document.body.appendChild(a);
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert((err as Error).message);   // 404 → 提示重新生成；401 → 提示重新登录
  }
};
```

---

## 8. 配置与依赖

### 8.1 新增依赖

```bash
pip install python-pptx
# Phase 3（可选）：pip install asposeslidescloud
```

### 8.2 新增配置（审查问题 9 —— 配置归属一刀切，不两边写）

| 配置文件 | 内容 | 理由 |
|---|---|---|
| **config/agent.yaml** | 仅 `tool_groups.ppt` + `tool_routing.keyword_rules.ppt`（§4.2） | `tool_groups`/`tool_routing` 结构上必须在此，与加载逻辑耦合 |
| **config/ppt.yaml（新建，唯一承载 PPT 功能参数）** | `max_notes: 10`、`max_slides: 20`、`per_note_chars: 2000`、`total_context_chars: 12000`、`outline_timeout: 25`、`outline_retries: 1`、`file_ttl_hours: 24`、`max_files_per_user: 20`、`engine: "python_pptx"`、`max_template_size_mb: 10`、`max_templates_per_user: 20`（v1.4 模板配额）、风格主题预设（business/academic/minimal 的配色与字体） | PPT 功能的所有参数集中在同一文件，便于维护 |

### 8.3 新增环境变量（.env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `PPT_ENGINE` | `python_pptx` | 渲染引擎切换（Phase 3 支持 `aspose_cloud`） |
| `ASPOSE_CLIENT_ID` / `ASPOSE_CLIENT_SECRET` | 空 | Aspose Cloud 凭证（Phase 3 才需要） |

**凭证读取方式（v1.6 补充，Phase 3 已实施）**：与 `DASHSCOPE_API_KEY` 完全同构——代码只读 `os.getenv`，真实值只存在于 `.env` / 部署环境变量（`.env` 已在 .gitignore），`.env.example` 仅提供空占位（已补）：

```python
class AsposeCloudRenderer:
    def __init__(self, config):
        # 从环境变量读取凭证（与 factory.py 读 DASHSCOPE_API_KEY 的模式一致）
        self.client_id = os.getenv("ASPOSE_CLIENT_ID", "")
        self.client_secret = os.getenv("ASPOSE_CLIENT_SECRET", "")
        if not self.client_id or not self.client_secret:
            raise ValueError("ASPOSE_CLIENT_ID/ASPOSE_CLIENT_SECRET 未配置")
        # asposeslidescloud SDK：Configuration 绑定凭证后创建 ApiClient，
        # 模板上传存储 + 模板渲染模式调用（§5.6）
```

`PPT_ENGINE=aspose_cloud` 时渲染器工厂才创建 `AsposeCloudRenderer`（v1 默认 `python_pptx` 不依赖任何凭证）。

### 8.4 超时与循环保护预算（审查问题 7 的边界控制）

> 现行超时体系（重构后）：`react_timeout = LLM_STREAM_TIMEOUT = 60s`（[chat.py:48](app/routers/chat.py#L48)），`plan_timeout = LLM_STREAM_TIMEOUT * 2 = 120s`（[chat.py:527](app/routers/chat.py#L527)，仅作为 `execute_plan_agent` 的兜底默认值）；Plan 路径实际总超时 `total_timeout=300s`（[agent.yaml:19](config/agent.yaml#L19)）、单步 `step_timeout=90s`（[agent.yaml:17](config/agent.yaml#L17)，`plan_execute:` 段）、综合 `synthesize_timeout=60s`（[agent.yaml:18](config/agent.yaml#L18)）。

| 环节 | 预算 | 说明 |
|---|---|---|
| 笔记批量读取 | ~0.5s | 单次 SQL，无风险 |
| 大纲生成（qwen3.8-max json mode） | **45s 内部超时**（`outline_timeout`）；实测单次 **15~20s**（两篇笔记） | 关闭 thinking（`enable_thinking=False`）提速约 3 倍；`ChatOpenAI(request_timeout=50)`；prompt 须含小写 `json` 字样（DashScope json_object 模式要求） |
| 大纲解析失败重试 | +1 次（约 15~20s，仅解析失败才触发） | **LLM 响应慢/超时不触发重试**（实现区分 `TimeoutError` → 直接降级），只解析失败才重试 |
| 渲染（to_thread） | <2s | 线程池，不占事件循环 |
| **ReAct 路径合计** | 正常 ~20s；最坏（重试）~40s | 路径超时 `react_timeout` = `LLM_STREAM_TIMEOUT` = **60s**（[chat.py:48](app/routers/chat.py#L48)）✅ |
| Plan 路径 | 工具作为单步执行 | 单步 `step_timeout=90s`（[agent.yaml:17](config/agent.yaml#L17)，`plan_execute:` 段）；总超时 `total_timeout=300s`（[agent.yaml:19](config/agent.yaml#L19)），重试场景绰绰有余 ✅ |
| `max_consecutive_tool_calls=6`（[agent.yaml:10](config/agent.yaml#L10)，`agent:` 段） | 不受影响 | PPT 是单次工具调用，不构成连续空转 |

> 边界结论：ReAct 路径最坏情形 ~53s 距 60s 上限还有余量，但**余量有限** —— 若未来大纲 Prompt 变长或模型延迟升高，优先调大 `LLM_STREAM_TIMEOUT` 或缩短 `outline_timeout`，不要在工具内盲目加长内部超时。Plan 路径受 90s 步超时与 300s 总超时双重保护，无虞。

---

## 9. 涉及改动文件清单

**新增**

| 文件 | 内容 |
|---|---|
| `app/services/ppt_service.py` | 生成管线：读模板(可选) → 读笔记 → 大纲（LLM 延迟获取）→ 渲染（to_thread）→ 落盘 → TTL/配额清理；构造注入 `ppt_template_service`（§6.5 方案 A） |
| `app/services/ppt_renderer.py` | `PPTRenderer` 接口 + `PythonPptxRenderer` 实现（Phase 3 加 `AsposeCloudRenderer`） |
| `app/schemas/ppt.py` | 大纲 Pydantic 模型（§4.4 代码）+ 解析校验函数 |
| `app/routers/ppt_router.py` | JWT 鉴权下载端点 |
| `config/ppt.yaml` | PPT 功能参数 + 风格主题预设 + 模板配额（§8.2，**PPT 参数唯一归属**） |
| `app/models/ppt_template.py`（v1.4） | 模板元数据模型（参照 `NoteTemplate`，§6.5） |
| `app/services/ppt_template_service.py`（v1.4） | 上传（落盘+记录）/ 列表 / 删除 / `resolve_template_path` 归属校验（§6.5） |
| `app/routers/ppt_template_router.py`（v1.4） | 上传 / 列表 / 删除 3 个端点（§6.5） |
| `front/src/pages/PPTTemplates.tsx`（v1.4） | 模板库页面（上传 / 列表 / 删除） |

**修改**

| 文件 | 改动 |
|---|---|
| `app/services/note_service.py` | 新增 `get_notes_by_ids(db, note_ids, user_id)`（签名见 §9.1） |
| `app/ai_service/agent_tools.py` | 工厂新增 `ppt_service=None` 参数 + `generate_ppt_tool`（v1.4 起含 `template_id` 参数）+ 注册进 `all_tools`；**更新文件头注释：11 → 12 个工具**（[agent_tools.py:4](app/ai_service/agent_tools.py#L4)，`send_email` 已完整实现并注册，见 L333-400） |
| `config/agent.yaml` | `ppt` 工具组 + 路由关键词（§4.2，**仅此两处**） |
| `app/ai_service/stream.py` | `on_tool_end`（L112-127）读取 `data.output`，产出 `tool_file` 事件（§6.3 第 1 段） |
| `app/ai_service/chat_route.py` | ① `ChatRouteContext` 新增 `ppt_service` 字段（L27-43）；② `react_events()` / `plan_events()` 补传 `ppt_service`；③ 白名单：`plan_events` `forwarded` 加 `tool_file`（L108-111）、`react_events` 补转 `tool_start/tool_end/tool_file`（L82-87） |
| `app/ai_service/agent_runner.py` | `execute_agent` 新增 `ppt_service=None` 并透传（L70-83 → L117-124） |
| `app/ai_service/plan_execute_agent.py` | `execute_plan_agent` / `_execute_batch` / `_execute_step` 新增 `ppt_service=None` 并逐层透传（§6.4） |
| `app/routers/chat.py` | 构造 `ChatRouteContext` 时传入 `ppt_service=init_manager.ppt_service`（L512-528）；**v1.4：与 `<referenced_notes>` 同段解析 `<ppt_template>` 注入 system_prompt**（L425-438） |
| `main.py` | `BackgroundInitManager.__init__` 同步创建 `self.ppt_template_service` 与 `self.ppt_service`（参照 `email_service` 模式 L66-70）；注册 ppt_router + ppt_template_router（L346-371 路由区） |
| `front/src/types/api.ts` / `useSSE.ts` / `AIChat.tsx` | `tool_file` 事件 + 下载卡片 + `generate_ppt_tool` 专用进度文案 |
| `front/src/components/layout/Sidebar.tsx` + `front/src/pages/PPTTemplates.tsx`（v1.4） | 侧边栏「PPT 模板」导航项 + 模板库页面（§7） |
| `.env.example` | PPT_ENGINE、Aspose 凭证占位 |

### 9.1 `get_notes_by_ids` 签名（审查问题 13）

```python
async def get_notes_by_ids(
    self, db: AsyncSession, note_ids: List[str], user_id: str
) -> List[Note]:
    """批量获取笔记（权限校验 + 已删除过滤）。

    与 get_note 不同：不抛 BusinessError —— 部分 ID 无效/不存在/无权限时
    静默忽略，只返回「属于该用户且未删除」的有效子集，调用方按需提示。
    保持输入顺序（按 id IN (...) 查询后在前端按输入顺序重排）。
    """
```

- 实现：`select(Note).where(Note.id.in_(note_ids), Note.user_id == user_id, Note.deleted_at.is_(None))`；
- **SQL `IN()` 不保证返回顺序与输入一致（MySQL 通常按主键索引顺序返回），必须在代码内按输入顺序重排（审查问题 2）**——否则 LLM 传 `C,A,B` 会生成 A、B、C 的章节顺序：

```python
notes = list(result.scalars().all())
id_order = {nid: i for i, nid in enumerate(note_ids)}
notes.sort(key=lambda n: id_order.get(n.id, 999))   # 理论上不会出现未匹配项，兜底排最后
return notes
```

- 上限由调用方 `max_notes=10` 保证，签名内不再重复限制。

---

## 10. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| **SSE 链路断裂（tool_file 被 chat_route 白名单丢弃）** | 前端收不到下载链接 | §6.3 三段式链路，**实施时先打通**：stream.py 产出 → chat_route.py 两处白名单（`react_events` / `plan_events`）→ 前端消费；每段有单测/日志验证 |
| qwen3-max JSON 输出偶发格式错误（漏括号/字段） | 大纲解析失败 | Pydantic 严格校验 + 解析失败自动重试 1 次 + 兜底降级为「纯文本大纲」按章节模板渲染 |
| 大纲内容与笔记不符（幻觉） | 讲解跑偏 | Prompt 强约束「仅基于给定笔记内容」，渲染前抽查关键字段非空 |
| **大纲结构非法（缺封面/无内容页/总结页位置错）** | 渲染出残缺 PPT | `PPTOutline.model_validator` 自动修复（插封面、移总结页）；无内容页才抛错走重试/降级（§4.4） |
| **SQL `IN()` 不保证顺序** | 多笔记章节顺序与选择顺序不符 | `get_notes_by_ids` 内按输入顺序重排（§9.1 代码） |
| **简单路径新增工具事件转发（行为变更）** | 简单对话突然出现工具状态指示 | 已核实前端为轻量 state 无遮罩（§6.3 提示）；配合工具名中文映射；Phase 1 实施时观察确认 |
| 长笔记截断丢细节 | 内容不全 | 保留标题层级/首段/结论；截断处标注「详见笔记」 |
| **大纲重试 + 网络波动逼近 60s SSE 超时（ReAct 路径）** | SSE 超时中断 | `outline_timeout=25s` 内部超时 + 仅解析失败重试（§8.4）；前端 `tool_start` 显示「生成 PPT 约需 20~30 秒」；Plan 路径 90s 步超时 + 300s 总超时无虞 |
| **python-pptx 同步渲染阻塞事件循环** | 全站请求卡顿 | `asyncio.to_thread`（§5.5） |
| **`list[str]` 工具参数与 qwen3-max 兼容性** | LLM 传参格式错误 | v1 用逗号分隔字符串（§4.1），与 `tags` 参数先例一致；Phase 2 再评估数组类型 |
| 文件服务磁盘膨胀 | 磁盘占满 | TTL 24h + 每用户 20 文件配额 + 启动时清理任务 |
| 越权下载他人 PPT | 隐私泄露 | file_id 格式校验 + 下载端点 JWT + 按 user_id 目录隔离 + sidecar 归属校验 |
| **用户模板损坏/版式复杂（v1.4）** | 渲染失败或版式错乱 | 上传时 `.pptx` 魔数校验 + 渲染前 `Presentation()` 打开校验 + 三档降级兜底（§5.6） |
| **v1 模板能力有限（v1.4）** | `{{key}}` 替换不支持复杂结构 | 能力边界写入代码注释（§5.6）；spike 先行；Phase 3 由 Aspose 模板渲染模式兜底 |
| **模板越权使用 / 路径穿越（v1.4）** | 他人模板被使用 / 读取任意文件 | `template_id` 归属强校验（同笔记）+ 固定 `data/ppt_templates/{user_id}/` 目录 + 不接收任意路径 |
| **模板库磁盘膨胀（v1.4）** | 磁盘占满 | 单文件 ≤10MB + 每用户 ≤20 个 + 删除接口（§8.2 配额配置） |
| 关键词误路由（如「讲解」） | 频繁加载工具 | 只用组合关键词，或用消息长度守卫 |
| Aspose 计费不可控（Phase 3） | 成本 | 默认 python-pptx；Aspose 仅在有模板需求时启用，按次计费提醒 |

---

## 11. 分阶段落地计划

| 阶段 | 范围 | 预估 |
|---|---|---|
| **Phase 1（MVP）** | ① **优先打通 SSE 端到端链路**（stream.py 产出 → chat_route.py 两处白名单转发 → 前端 tool_file 消费，先用 mock 工具输出验证；同时验证简单路径新增 tool_start/tool_end 转发的前端表现）；② `PptService` + `generate_ppt_tool` + agent.yaml 配置 + 注入链路（§6.4 十处）；③ 下载端点（参数级 Depends）+ TTL/配额；④ python-pptx 基础版式（封面/目录/章节/内容/总结 + 演讲者备注）；⑤ 前端下载卡片 + 工具名中文映射 + 进度文案 | 3~4 天 |
| **Phase 1.5（PPT 模板库，v1.4 新增）** | ① 模板库：`PptTemplate` 模型 + 服务 + 3 个端点 + 前端页面 + 侧边栏导航（§6.5）；② 对话「PPT 模板」单选 + `<ppt_template>` 注入 + 工具 `template_id` 参数（§4.1）；③ v1 有限渲染支持：母版/版式复用 + `{{key}}` 替换 + 三档降级兜底（§5.6）；④ **spike 先行**：用 1 份简单模板验证模板链路（§5.6 验证清单） | 约 3 天 |
| **Phase 2（质量）** | 大纲二次润色（content 页正文单独调 LLM 扩写）；config/ppt.yaml 风格预设扩充；代码块/表格/Markdown 清洗增强；真实进度事件（回调 + 独立 SSE 通道，若需要）；`note_ids` 数组参数兼容性评估 | 1~2 天 |
| **Phase 3（可选）** | `AsposeCloudRenderer`：设计模板（.pptx 模板填占位符）+ `PPT_ENGINE` 切换；PPT 历史记录（DB 表） | 按需 |

> 其他可选技术方向（供参考，非本方案推荐）：前端 PptxGenJS 直接生成（浏览器端免后端存储，但依赖前端实现大纲→版式逻辑，且无法复用后端 LLM 管线）；Marp 标记语言转 PPT（需在用户侧装 Marp，交付链路长）。当前方案为后端一次性生成 .pptx 文件，交付最直接。

---

## 12. 审查修订记录（v1.0 → v1.1 → v1.2 → v1.3 → v1.4）

| # | 优先级 | 问题 | 修订位置 |
|---|---|---|---|
| 1 | 🔴 | `tool_file` 事件在转发白名单中被静默丢弃（简单路径甚至不转发工具事件） | §2.2、§6.3 第 2 段 |
| 2 | 🔴 | stream.py `on_tool_end` 未读取 `event["data"]["output"]` | §6.3 第 1 段（含代码） |
| 3 | 🔴 | PptService 获取 LLM 实例的路径未设计 | §4.3「LLM 获取路径」（init_manager 延迟导入，与 chat.py 函数内导入模式一致） |
| 4 | 🟡 | python-pptx 同步渲染阻塞事件循环 | §5.5（`asyncio.to_thread`） |
| 5 | 🟡 | `list[str]` 工具参数兼容性存疑 | §4.1（改为逗号分隔字符串，与 `tags` 先例一致） |
| 6 | 🟡 | `ppt_service` 注入链路描述不完整 | §6.4（注入点表格） |
| 7 | 🟡 | 35s 逼近 60s 超时边界、缺进度反馈 | §8.4（预算表）、§7（前端进度文案 + 不做工具内增量事件的理由） |
| 8 | 🟡 | PptService 初始化策略未明确 | §6.4 末段（阶段 0 轻量创建，模型延迟获取） |
| 9 | 🟢 | config/ppt.yaml 与 agent.yaml 配置归属重复 | §8.2（一刀切：agent.yaml 只管工具组/路由，PPT 参数全进 ppt.yaml） |
| 10 | 🟢 | 大纲 Schema 只有 JSON 示例没有 Pydantic 代码 | §4.4（完整模型代码） |
| 11 | 🟢 | 前端下载缺文件名与错误处理细节 | §7（完整下载代码 + 404/401 提示） |
| 12 | 🟢 | agent_tools.py 文件头工具计数需更新 | §9（9 → 10 个工具）※v1.3 修订为 11 → 12，见 #24 |
| 13 | 🟢 | `get_notes_by_ids` 缺少签名设计 | §9.1（签名 + 语义：不抛 BusinessError，静默忽略无效 ID） |
| 14 | 🔴 | 下载端点双重依赖（装饰器级 + 参数级），归属校验风险 | §6.2（去掉 `dependencies=[...]`，只保留参数级 `Depends`，与 chat.py 风格一致） |
| 15 | 🟡 | SQL `IN()` 不保证返回顺序，影响 PPT 章节顺序 | §9.1（补重排代码：按输入顺序 sort） |
| 16 | 🟢 | 简单路径新增工具事件转发是行为变更 | §6.3（已核实前端为轻量 state 无遮罩；补工具名中文映射；Phase 1 验证） |
| 17 | 🟢 | `PPTOutline` 缺结构约束（封面/内容页/总结页位置） | §4.4（`model_validator` 自动修复：插封面、移总结页、无内容页才抛错） |

**v1.3（第三轮深度技术评审，基线 commit c6f5f81）**

| # | 优先级 | 问题 | 修订位置 |
|---|---|---|---|
| 18 | 🔴 | 架构已重构为 LangGraph StateGraph，文档描述的 chat.py 直调两条分支（简单 ReAct / Plan）不复存在，§2.2 / §6.3 / §6.4 的目标代码失效 | §2.2 重写为三层架构（chat.py 路由层 → chat_graph.py 编排层 → chat_route.py 执行路由层）；§6.3 第 2 段改指 `chat_route.py` 白名单；§6.4 重写注入链路 |
| 19 | 🔴 | 注入链路声称「chat.py 4 处调用」需补传 `ppt_service`，实际 chat.py 已不直接调用 `execute_agent`/`execute_plan_agent` | §6.4 改为 10 处注入点：`ChatRouteContext` 字段 + `react_events`/`plan_events` 补传 + chat.py 构造 ctx 传入 + 下游 5 层签名透传 |
| 20 | 🔴 | `tool_file` 转发白名单实际在 `chat_route.py`（`react_events` L83 / `plan_events` L108-111），不在 chat.py | §6.3 第 2 段给出 `chat_route.py` 两处白名单的精确修改代码 |
| 21 | 🔴 | `_execute_step` 透传机制描述为「显式白名单全量透传」，实际是 if/elif 之后的 fallthrough `yield event`，且行号错误 | §2.2 / §6.3 补充透传机制说明（L280-281），`tool_file` 可自动穿过，此层无需改动 |
| 22 | 🟡 | 行号引用大面积偏移（13 处中仅 2 处准确），6 处指向已不存在的代码 | 全文行号逐一对齐 commit c6f5f81；头部增加「代码基准 commit」标注 |
| 23 | 🟡 | `ChatRouteContext` 缺少 `ppt_service` 字段，注入链路遗漏关键数据类 | §6.4（新增字段代码 + 表格首行） |
| 24 | 🟡 | 工具计数「9 → 10」错误：`send_email` 已完整实现并注册，当前 `all_tools` 共 11 个 | §9（11 → 12 个工具，`agent_tools.py` 文件头 L4 同步更新） |
| 25 | 🟡 | `agent.yaml` 引用：`step_timeout` 实际在 `plan_execute:` 段（L17）；预算表未区分 ReAct/Plan 超时 | §8.4（明确 `react_timeout=60s`、`plan_timeout=120s`（兜底）、`step_timeout=90s`、`total_timeout=300s` 的配置归属） |
| 26 | 🟡 | `_execute_batch` 未在注入链路中提及，`ppt_service` 无法穿过并行/顺序批执行 | §6.4（补 `_execute_batch` 透传行：`execute_plan_agent` → `_execute_batch` → `_execute_step` → `execute_agent`） |
| 27 | 🟡 | `factory.py:249` 模型名引用偏移 95 行 | §1（改指 L344，并注明 `.env.example` 实际为 `qwen3.7-plus`）；§4.3 同步改指 L322 |
| 28 | 🟢 | stream.py `on_tool_end` 行号偏移 | §6.3 第 1 段（L112-127） |
| 29 | 🟢 | `main.py:49-59` 初始化描述不完整，缺 `email_service` try/except 先例 | §2.1 / §6.4（L50-71，`PptService` 参照 L66-70 模式同步创建） |
| 30 | 🟢 | `auth_utils.py:356-424` 行号未验证 | §6.2（已核实 `get_current_user_id` 自 L356 起 ✅）；§7 前端行号同步修正（api.ts L317-339 / useSSE.ts L163-167 / AIChat.tsx L460-465） |
| 31 | 🟢 | 文档日期与代码状态不匹配（v1.2 定稿后发生重大重构） | 头部增加「代码基准 commit c6f5f81」标注，后续行号漂移风险可控 |
| 32 | 🟢 | §2.1「相关代码路径」表缺 `chat_graph.py` / `chat_route.py` 两个核心中间层 | §2.1（补充两行，标注三层职责与白名单所在处） |

**v1.4（新增功能：用户 PPT 模板）**

| # | 类型 | 内容 | 位置 |
|---|---|---|---|
| 33 | ➕ 新功能 | 侧边栏「PPT 模板」库：上传/列表/删除，克隆 `note_template` CRUD + `chat_attachment` 文件存储双模式 | §2.1、§6.5、§9 |
| 34 | ➕ 新功能 | 对话中与笔记一起选中模板：`<ppt_template>` 块 → chat.py 同段解析注入 system_prompt | §6.5、§7 |
| 35 | ➕ 新功能 | `generate_ppt_tool` 新增 `template_id` 参数（归属强校验 + LLM 漏传时降级默认版式） | §4.1、§4.3 |
| 36 | ➕ 新功能 | 渲染抽象扩展 `template_path`；v1 有限支持（母版复用 + `{{key}}` 替换）三档降级，Phase 3 Aspose 模板渲染模式完整支持 | §5.2、§5.6 |
| 37 | ➕ 新功能 | 模板存储与配额：`data/ppt_templates/{user_id}/` + DB 记录 + 10MB/20 个限额（模板为永久资产，不进 TTL） | §6.1、§8.2 |
| 38 | ➕ 新功能 | 模板相关风险与对策（损坏降级 / 能力边界 / 越权 / 路径穿越 / 磁盘膨胀） | §10 |
| 39 | ➕ 新功能 | 分阶段：新增 Phase 1.5（模板库 + 对话链路 + spike，约 3 天） | §11 |

**v1.5（第五轮深度技术评审，基线 commit c6f5f81）**

| # | 优先级 | 问题 | 修订位置 |
|---|---|---|---|
| 40 | 🟡 | `ppt_template_service` 注入链路缺失：§6.4 注入表格无此服务，§4.3 `generate()` 直接调用但签名/来源未定义 | §6.4（注明该服务**不走** 10 处工具透传链）、§6.5（方案 A 注入代码）、§4.3（改用 `self.ppt_template_service`） |
| 41 | 🟡 | `template_id` 类型不一致：工具签名 `str` vs DB 主键/路由 `int` | §6.5（明确 `resolve_template_path` 参数为 `str`、方法内部 `int()` 转换后查库，符合项目工具参数惯例） |
| 42 | 🟡 | `ppt_template_service` 到达 `PptService.generate()` 的具体路径未定义（方案 A/B 未选定） | §6.5（**选定方案 A**：`PptService.__init__(config, ppt_template_service)` 构造注入；理由：模板解析为 PptService 内部行为，工具层无需感知，生命周期同阶段 0） |
| 43 | 🟢 | §3 架构图出现两行 `chat_graph.py 编排层` 重复标注 | §3（L101 右侧标注改为 `chat_route.py 白名单转发`，与下文呼应） |
| 44 | 🟢 | `PptTemplate` 模型缺 `updated_at`（参照的 `NoteTemplate` 有该字段） | §6.5（补 `updated_at`，为未来重命名等编辑预留） |
| 45 | 🟢 | 端点路径 `/ppt-templates`（复数）与先例 `/note-template`（单数）风格不一致；未注明 `success_response()` 约定 | §6.5（统一单数 `/ppt-template` + 注明响应包装风格） |
| 46 | 🟢 | §2.1 `note_template_service.py` 引用无行号 | §2.1（补 `create_template` L25 / `list_templates` L52 / `get_template` L72 / `delete_template` L123） |
| 47 | 🟢 | 上一轮遗留 P2-B：§2.1 stream.py 描述未标注 `stream_done` 在下游被丢弃 | §2.1（补注：`stream_done` 在 chat_route 层被过滤，不达前端） |

**v1.6（Phase 1 / Phase 1.5 实施同步，2026-08-06）**

| # | 类型 | 内容 | 修订位置 |
|---|---|---|---|
| 48 | 🔵 实施同步 | `generate()` 实际签名含 `db`（工具经 `db_session_factory` 创建）与 `note_service`（工具闭包透传），PptService 不持有两者引用；文档伪代码此前省略了来源 | §4.3 |
| 49 | 🔵 实施同步 | `PPTOutline.slides` 的 min_length 校验移入 `validate_structure`（字段层约束先于 after validator 执行，会阻断「自动插封面」修复） | §4.4 |
| 50 | 🔵 实施同步 | tool_file 解析实现为独立函数 `parse_tool_file_event()`（可单测），语义与文档内联代码一致 | §6.3 第 1 段 |
| 51 | ➕ Phase 1 已实施 | SSE 三段链路、PptService/渲染器/下载端点、`generate_ppt_tool` + 注入链 10 处、前端下载卡片 + 工具名映射——全部落地并通过验证 | 各节 |
| 52 | ➕ Phase 1.5 已实施 | 模板库落地：`PptTemplate` 模型（含 `updated_at`）+ 服务 + 3 端点（`/ppt-template` 单数 + `success_response`）+ 前端页面/侧边栏/AIChat 单选 + `<ppt_template>` 注入 | §6.5、§7 |
| 53 | ➕ Phase 1.5 已实施 | 渲染器模板 v1 有限支持落地并通过 spike：命名版式页匹配 + `{{key}}` 标量/列表/代码替换 + 逐页降级；**能力边界**：形状样式保留，母版/主题色继承不保证（复制用目标自身 blank 版式） | §5.6 |
| 54 | 🔵 实施调优 | 大纲生成显式关闭 thinking（实测提速约 3 倍：40s → 17s）；prompt 统一小写 `json`（DashScope json_object 模式对大小写敏感，大写 "JSON" 有 400 风险）；实现区分 `TimeoutError`（直接降级，不重试）与解析失败（重试）——与 §8.4「响应慢不触发重试」语义对齐 | §4.3、§8.4 |
| 55 | ➕ 实施验证 | qwen3.8-max 真实端到端：两篇笔记 **17.3s / 8 页**（cover→agenda→章节→summary，结构校验通过）；前端 tsc + vite build 全绿 | 全文 |
| 56 | 🔴 实施修复 | **Plan 路径不调用 PPT 工具**：`plan_generation.txt` 硬编码工具清单（10 个，无 `generate_ppt_tool`，且编号重复）→ 规划 LLM 不知道新工具。修复：prompt 改 `{tool_list}` 占位 + `_build_plan_tool_list()` 从 `tool_groups` 配置动态构建（新工具自动同步，编号无重复）；真实验证规划出 search → get_content → `generate_ppt_tool` → 汇总 完整步骤链 | §2.2 |
| 57 | 🔴 实施修复 | **tool_file 事件不产出 → 前端无下载卡片**：langgraph 1.x 的 `on_tool_end` 事件 `data.output` 是 **ToolMessage 对象**（内容在 `.content`）而非原始字符串，`parse_tool_file_event` 类型判断失败静默返回 None。修复：提取 `.content` 再解析；真实模型全链路验证产出 `tool_file` | §6.3 第 1 段 |
| 58 | ➕ 实施增强 | **模板渲染四级降级链（T2 内容覆盖 + T3 母版优先）**：用户纯设计模板（无命名页/占位符，如 4.pptx 15 页成品模板）不再降级默认版式——T2 识别标题/正文框并覆盖（角色优先 + 视觉得分，spike 校准），复杂卡片布局降级 T3；T3 删页保母版，用模板版式新建标准讲解页。全链路验证：9 页大纲全部内容来自笔记、布局来自模板，无旧文本残留 | §5.6 |
| 59 | 🔴 实施修复 | **模板色调被修改（主题色失效）**：T1/T2 原「复制到新演示文稿 + deepcopy」会把模板 `schemeClr` 主题色引用解析到默认主题。修复：**原地修改模板**——直接在模板文件上覆盖文本/同文件复制命名页/重排 sldIdLst（含 drop_rel 丢弃多余 slide part）/新建标准页用模板版式。实测 4.pptx 首页 7 个色块与原模板完全一致 | §5.6 |
| 60 | 🔴 实施修复 | **「单击此处添加标题」占位符提示残留与正文叠加**：标准页路径（T1/T2 缺失页、T3 全部页）用含 title+body 占位符的版式 `add_slide` 后未清除版式占位符形状，提示文字与 `add_textbox` 正文图层叠加重影。修复：`_render_slide` 新建页后清除 `is_placeholder` 形状（背景/母版保留）；T2/T3 全路径验证无残留 | §5.6 |
| 61 | 🔴 实施修复 | **下载卡片切换模块后消失（未持久化）**：tool_file 是 SSE 瞬时事件，前端独立 state 渲染，切换路由组件卸载即丢失。修复：① 后端 chat.py 收集 `tool_file` 事件，保存 assistant 消息时写入 `attachments_json`（复用现有 JSON 字段，不迁移表）；② 前端统一从**消息 attachments** 渲染下载卡片（流式挂载与历史回放同源）——切换模块/刷新后从历史接口恢复卡片 | §7 |
| 62 | 🟡 实施优化 | **生成回复杂冗、句式混乱**：步骤详情（校验报告/设计稿/工具说明）平铺进最终回复。修复：① `plan_synthesize.txt` 约束「步骤详情只作内部参考，不得复述；PPT 场景只回一句话」；② `main_prompt.txt` 增加「生成 PPT 必须调工具 + 成功后一句话」规则；③ 前端：含 PPT 卡片的消息文本折叠为「查看生成过程」（生成中实时显示） | §7、prompts |
| 63 | ➕ Phase 3 已实施 | **AsposeCloudRenderer（模板渲染模式 + `PPT_ENGINE` 切换）**：`create_renderer()` 工厂按 `PPT_ENGINE` 返回引擎；模板含 `{{key}}` 占位符 → Aspose 云端渲染（真实验证：XML 数据 + `fromTemplate` 直出 pptx），无占位符/失败 → 本地 T2/T3 兜底。**实施要点（实测校准）**：data 必须 XML（JSON → 服务器 500）；name 纯文件名（带文件夹 → 404）；`download_file` 返回本地临时路径；输出页数由模板决定（变长页需模板 `{{agenda}}`/`{{sections}}` 循环容器） | §5.2/§5.6/§8.3 |
| 64 | 🔴 实施修复 | **T1 命名页复用的 `used: set` 对 Slide 不可哈希**（`unhashable type: 'Slide'` → 静默降级默认版式，此前 T1 回归测试为假通过）。修复：改用 list 成员判断 | §5.6 |
| 65 | ➕ 测试套件 | **`test_aspose_renderer.py`（5 用例，全部通过）**：模板上传+md5 缓存 / Aspose 渲染合法 pptx（PK 头 33KB）/ 占位符替换（中文无乱码无残留）/ 多页模板逐页填充（顶层标量键）/ 无占位符本地 T2/T3 兜底。测试暴露并修复 **T2 页映射冲突 bug**（模板页数 < 大纲页数时末页映射与中间页撞同一模板页 → sldId 重复丢页，现冲突页用标准版式） | §5.6、test_aspose_renderer.py |
| 66 | ➕ Phase 3 增强 | **桥接方案 B（无占位符纯设计模板 → Aspose 渲染）**：本地 T2 识别（标题/副标题/正文框）→ 模板副本注入**纯字母语义键占位符**（`{{cover_title}}`/`{{content_a_bullets}}`…）→ 上传 Aspose 模板模式渲染 → 母版背景完整继承。实测校准的 Aspose 规则：① **数组数据 `<key><item>` 不填充普通文本框**（仅容器形状支持），bullets/items 用 **\n 连接的标量**（多行显示已验证）；② 数字键名数组不工作（`{{slide1_bullets}}` ✗），纯字母键正常；③ 复杂布局页（正文框 ≥4）**仅注入标题**（正文保留为设计元素），仍计入注入率（放宽判定，卡片型模板也可走 Aspose）；④ 注入率 <60% → 本地 T2/T3 兜底。引擎日志显式化：重启后日志输出「引擎 aspose_cloud 桥接模式: 注入率 N% → Aspose 渲染」或「桥接不适用 → 本地 T2/T3 渲染」 | §5.6、ppt_renderer_aspose.py |
| 67 | 🔴 实施修复 | **PPT_ENGINE=aspose_cloud 生效但用户模板仍走本地**：根因是桥接判定（复杂页不计入注入率 → 4/5.pptx 注入率不足 → 降级本地，日志与 python_pptx 引擎相同）。修复：① 放宽判定（复杂页仅标题注入计入注入率，4.pptx 实测 100% 走 Aspose）；② 引擎路径 INFO 日志显式化；③ 前端发送后清除模板选择（避免「没选模板却用了旧模板」） | §5.6、ppt_renderer_aspose.py、AIChat.tsx |
