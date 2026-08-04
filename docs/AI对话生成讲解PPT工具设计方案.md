# AI 对话「选中笔记生成讲解 PPT」工具设计方案

> 版本：v1.2（已通过两轮可行性审查修订，修订记录见 §12）  
> 日期：2026-08-03  
> 状态：待评审

---

## 1. 背景与目标

当前 AI 对话已支持在输入框选择**单个/多个笔记**（前端以 `<referenced_notes>` 结构化块附带笔记 ID 与全文），Agent 可基于这些笔记回答、总结、修改。但用户无法直接得到一份**可下载、可讲解的 PPT 文件**。

本方案在现有 Agent 工具体系中新增一个 `generate_ppt_tool` 工具，使 LLM（当前为通义千问 qwen3-max，见 [app/utils/factory.py:249](app/utils/factory.py#L249) `DASHSCOPE_CHAT_MODEL` 默认值）在用户说「把这几个笔记做成 PPT / 生成讲解幻灯片」时：

1. 从数据库按 ID 读取所选笔记（**以 DB 为准，不依赖消息中可能被截断的笔记正文**）；
2. 调用 LLM 生成**结构化 PPT 大纲**（JSON）；
3. 由渲染引擎生成 `.pptx` 文件并落盘；
4. 通过 SSE 推送「PPT 已生成」事件，前端渲染下载按钮，用户点击下载。

目标：

| 维度 | 目标 |
|---|---|
| 交互 | 沿用现有「选择笔记 → 发送」交互，零新增学习成本 |
| 输出 | 16:9 `.pptx` 文件，含封面、目录、章节页、内容页、演讲者备注 |
| 质量 | 大纲由 qwen3-max 结构化生成，内容忠于笔记原文 |
| 成本 | v1 用免费开源的 python-pptx 渲染；Aspose.Slides Cloud 作为可插拔的高保真引擎（Phase 3） |
| 安全 | PPT 只能访问本人笔记；下载端点走 JWT 鉴权，不挂公开静态目录 |

---

## 2. 现状分析（改造基础）

### 2.1 相关代码路径

| 模块 | 位置 | 说明 |
|---|---|---|
| Agent 工具工厂 | [app/ai_service/agent_tools.py](app/ai_service/agent_tools.py) | `create_agent_tools()` 用 `@tool` 定义异步工具，`all_tools` 注册表 + 按 `groups` 过滤 |
| 工具分组/路由 | [config/agent.yaml](config/agent.yaml) | `tool_groups` 定义分组；`tool_routing.keyword_rules` 关键词命中后追加工具组 |
| 聊天主链路 | [app/routers/chat.py](app/routers/chat.py) | `/chat/query` SSE：RAG + 记忆压缩 → 分类器 → ReAct（简单）/ Plan-and-Execute（复杂） |
| 引用笔记解析 | [app/routers/chat.py:262-296](app/routers/chat.py#L262-L296) | 解析 `<referenced_notes>`，把 `- ID: xxx \| 标题: yyy` 注入 system_prompt |
| 流式事件 | [app/ai_service/stream.py](app/ai_service/stream.py) | 产出 `response / tool_start / tool_end / error / stream_done` 事件 |
| 笔记模型 | [app/models/note.py](app/models/note.py) | `id / user_id / title / content(Markdown) / tags / category / deleted_at` |
| 笔记服务 | [app/services/note_service.py](app/services/note_service.py) | 已有 `get_note(db, note_id, user_id)`（单条），**缺批量查询，需补充** |
| 模型初始化 | [main.py:49-59](main.py#L49-L59) | `BackgroundInitManager.__init__`：`chat_model=None`、`note_service=None`、阶段事件 |
| 前端 SSE | [front/src/hooks/useSSE.ts](front/src/hooks/useSSE.ts) | 事件分发，需新增 `tool_file` 分支 |
| 笔记选择 UI | [front/src/pages/AIChat.tsx:129-180](front/src/pages/AIChat.tsx#L129-L180) | 已支持多选笔记并拼装 `<referenced_notes>`，**无需改动** |
| 静态文件 | [main.py:327-331](main.py#L327-L331) | 仅 `/static/avatars` 公开挂载；PPT 属敏感数据，**不可复用此模式** |

### 2.2 两条 Agent 路径的兼容性（含事件透传差异）

- **ReAct（简单查询）**：[app/ai_service/agent_runner.py:113](app/ai_service/agent_runner.py#L113) 走 `resolve_tool_groups(user_message)` 关键词路由 → 在 `agent.yaml` 加 `ppt` 组 + 路由关键词即可自动生效。
- **Plan-and-Execute（复杂查询）**：[app/ai_service/plan_execute_agent.py:155-177](app/ai_service/plan_execute_agent.py#L155-L177) `_resolve_step_tool_groups()` 从同一个 `tool_groups` 配置构建「工具名 → 组名」反向映射，**新增 `ppt` 组后两条路径自动可用**，无需额外改造。`_execute_step` 内部对 `execute_agent` 的事件是**全量透传**（[plan_execute_agent.py:256-257](app/ai_service/plan_execute_agent.py#L256-L257)）。

⚠️ **关键差异（审查问题 1）**：`execute_agent` 产出的工具事件在两处调用方的**转发白名单不同**：

| 调用路径 | 事件转发现状 |
|---|---|
| 简单 ReAct（[chat.py:338-361](app/routers/chat.py#L338-L361)） | **只转发 `response / error / stream_done`**，`tool_start / tool_end` 一律丢弃 |
| Plan 路径（[chat.py:406-450](app/routers/chat.py#L406-L450)） | 转发 `plan_*` + `tool_start / tool_end`，**新增事件类型不在白名单同样被丢弃** |

因此 `tool_file` 事件必须**在 stream.py 产出 + chat.py 两处转发分支都显式加入**（详见 §6.3），否则前端永远收不到。

### 2.3 为什么工具读取笔记而不是靠 LLM 记忆

消息里虽然带笔记全文，但：
- 消息内容可能被截断/过长，直接进 LLM 上下文浪费 token；
- LLM 可能「回忆」错笔记内容（幻觉）。

因此工具内按 ID 从 DB 批量读取（校验 `user_id` + `deleted_at IS NULL`），**内容以数据库为准**。

---

## 3. 总体架构

```
┌─────────────┐  发送消息(含<referenced_notes>)   ┌──────────────────────────────┐
│   前端       │ ────────────────────────────────► │ POST /api/v1/chat/query (SSE) │
│ AIChat.tsx  │                                   └──────────────┬───────────────┘
│  笔记多选(已有)│                                              │ 分类器
└─────────────┘                                              ReAct / Plan-Execute
      ▲                                                          │
      │ ① tool_file 事件(下载链接)                                 ▼
      │ ② 渲染下载卡片                              Agent 调用 generate_ppt_tool
      │                                                  │
      │                                     ┌────────────▼────────────┐
      │                                     │      PptService         │
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

---

## 4. 工具设计

### 4.1 工具签名

在 [app/ai_service/agent_tools.py](app/ai_service/agent_tools.py) 的 `create_agent_tools()` 中新增（工厂注入 `ppt_service` 参数，模式与 `note_service`/`review_service` 一致）：

```python
@tool
async def generate_ppt_tool(
    note_ids: str,       # 必填：笔记 ID，逗号分隔（如 "id1,id2,id3"），须来自用户引用的笔记
    title: str = "",     # 可选：PPT 主题，默认由 LLM 根据笔记内容拟定
    style: str = "business",  # 可选：风格预设 business / academic / minimal
) -> str:
    """
    根据用户选中的一篇或多篇笔记，生成一份讲解用 PPT（.pptx 文件）。
    适用场景：用户说「把这几篇笔记做成PPT / 生成讲解幻灯片 / 整理成演示文稿」。
    注意：note_ids 必须是用户引用笔记中的 ID（<referenced_notes> 内提供的），
    逗号分隔，可一次传入多篇，每篇笔记会生成独立的章节。
    返回 JSON 字符串，包含 file_id、download_url、slide_count、title。
    """
```

**为什么 `note_ids` 用逗号分隔字符串而不是 `list[str]`（审查问题 5）**：
- 本项目所有工具的参数均为标量类型，且已有先例 —— `create_note_tool` / `update_note_tool` 的 `tags` 参数就是「逗号分隔字符串」（[agent_tools.py:143](app/ai_service/agent_tools.py#L143)、[agent_tools.py:169](app/ai_service/agent_tools.py#L169)）；
- 避免 LangChain `@tool` + 数组类型 JSON Schema 与 qwen3-max function calling 的兼容性不确定性；
- 工具内部 `[i.strip() for i in note_ids.split(",") if i.strip()]` 解析，与 `create_note_tool` 的 tags 解析方式完全一致，LLM 出错率最低。

**为什么 `note_ids` 由 LLM 传参而不是从消息里解析**：与现有 `update_note_tool` 的惯例一致（LLM 从 system_prompt 中 `referenced_notes` 拿到 ID 后填入参数），工具内部再强校验归属，双保险。

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

> 注意：`讲解` 单独作为关键词误伤率较高（如「帮我讲解一下这个概念」），建议只用组合词，或加「命中时消息长度 ≥ 10 字符」的守卫。`ppt` 组不加入 `default_groups`，保持轻量工具集（qwen3-max 的工具 schema 越少，幻觉率越低）。

### 4.3 工具执行流程（PptService.generate）

```python
async def generate(self, user_id, note_ids, title, style) -> dict:
    # ① 参数校验与上限
    ids = [i.strip() for i in note_ids.split(",") if i.strip()]
    if not 1 <= len(ids) <= MAX_NOTES(10):
        return error("一次最多选择 10 篇笔记")

    # ② 批量读取笔记（新增 NoteService.get_notes_by_ids，见 §6.4）
    notes = await note_service.get_notes_by_ids(db, ids, user_id)   # 过滤已删除，静默忽略无效 ID
    if not notes:
        return error("未找到对应笔记，请确认所选笔记未被删除")

    # ③ 内容截断与组装上下文（每篇 ≤ 2000 字，保留标题/列表结构）
    context = build_ppt_context(notes)          # 截断规则见 5.4

    # ④ qwen3-max 生成结构化大纲（JSON mode，25s 超时，解析失败重试 1 次）
    #    LLM 实例获取方式见下方「LLM 获取路径」
    outline = await llm_generate_outline(context, title, style)

    # ⑤ 渲染引擎生成 .pptx 字节流（同步库，必须进线程池，见 §5.5）
    pptx_bytes = await asyncio.to_thread(renderer.render, outline, theme=style)

    # ⑥ 落盘 + 元数据 + 返回下载信息
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

- `PptService.__init__(config)` 只保存配置与路径（轻量对象，可在 `BackgroundInitManager.__init__` 中同步创建，见问题 8）；
- `generate()` 内通过**函数内延迟导入**获取模型（与 [chat.py:64/93](app/routers/chat.py#L64) 的既有模式一致，避免模块级循环导入）：

```python
# app/services/ppt_service.py 内部
def _get_chat_model(self):
    from main import init_manager   # 延迟导入，复用全局管理器的模型实例
    model = init_manager.chat_model
    if model is None:
        raise PptError("AI 模型未就绪，请稍后重试")
    return model
```

- 大纲生成使用独立的 `ChatOpenAI` 调用（复用 `DASHSCOPE_BASE_URL` / `DASHSCOPE_API_KEY`，见 [factory.py:230](app/utils/factory.py#L230)），`response_format={"type": "json_object"}` + Pydantic 校验；
- 不选择「把 `chat_model` 一路透传到工具工厂」的方案：需要穿透 `execute_agent` / `execute_plan_agent` / `_execute_step` 四层签名，且与现有 `note_service`/`review_service` 的注入风格不同，收益有限。

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
    subtitle: str
    style: Literal["business", "academic", "minimal"]
    slides: List[PPTSlide] = Field(min_length=3, max_length=20)

    @model_validator(mode="after")
    def validate_structure(self):
        """结构约束（审查问题 4）：首页必须封面、必须含内容页、总结页必须在最后。
        采用自动修复而非抛错 —— 避免二次调用 LLM，保证确定性。"""
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
    def render(self, outline: PPTOutline, theme: str) -> bytes: ...

# 实现一（v1 默认）：PythonPptxRenderer —— 本地 python-pptx
# 实现二（Phase 3 可选）：AsposeCloudRenderer —— 上传模板 + 填大纲数据 + 下载结果
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

---

## 6. 文件存储、下载与 SSE 事件链路

### 6.1 存储

```
data/ppt/
└── {user_id}/
    ├── {file_id}.pptx          # file_id = uuid4().hex
    └── {file_id}.json          # 元数据: {title, slide_count, created_at, size, engine}
```

- 元数据用 JSON sidecar，不建新表（文件是临时产物，不进 MySQL）；
- **TTL 24 小时**：启动时后台任务 + 下载命中时惰性清理，删除过期文件；
- 配额：每用户最多保留 20 个文件，超限删最旧（防磁盘膨胀）。

### 6.2 下载端点（新增 app/routers/ppt_router.py）

```python
@router.get("/ppt/{file_id}")
async def download_ppt(file_id: str, user_id: str = Depends(get_current_user_id)):
    # ① file_id 必须匹配 ^[0-9a-f]{32}$，防路径穿越
    # ② 读取 {user_id}/{file_id}.json，校验归属（sidecar 不存在 → 404）
    # ③ FileResponse(path, filename=f"{title}.pptx", media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")
```

**只用参数级 `Depends`（审查问题 1）**：`get_current_user_id` 是返回 `user_id` 字符串的依赖（[auth_utils.py:356-424](app/utils/auth_utils.py#L356-L424)），参数级注入即可用于归属校验；若同时写 `dependencies=[...]` 会**重复执行两次 JWT 解码 + 两次 DB 会话**，且装饰器级返回值被丢弃，纯属冗余。项目内所有端点（如 [chat.py:51](app/routers/chat.py#L51)）均只用参数级写法，保持一致。

- **不走公开静态目录**（`/static/avatars` 是公开的，PPT 含用户笔记内容，必须 JWT 鉴权）；
- 在 [main.py:310-325](main.py#L310-L325) 注册：`app.include_router(ppt_router.router, prefix=API_PREFIX, tags=["PPT"])`。

### 6.3 SSE 事件链路（端到端，审查问题 1+2 —— 实施时最易遗漏的坑）

`tool_file` 事件的完整链路分 **3 段**，每一段都必须打通：

**第 1 段：stream.py 产出**（[app/ai_service/stream.py:95-107](app/ai_service/stream.py#L95-L107)）

langgraph v2 的 `on_tool_end` 事件 `data` 字段带 `output`（工具返回值），当前代码完全没读。新增解析：

```python
elif event_type == "on_tool_end":
    tool_name = event.get("name", "unknown")
    # ... 现有 duration 计算与 tool_end 产出不变 ...
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

**第 2 段：chat.py 转发白名单**（两处都要加，见 §2.2）

- 简单 ReAct 分支（[chat.py:338-361](app/routers/chat.py#L338-L361)）：当前**连 `tool_start/tool_end` 都不转发**，本次顺带补上：

```python
elif event_type in ("tool_start", "tool_end", "tool_file"):
    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
```

> ⚠️ **行为变更提示（审查问题 3）**：简单路径此前从不转发工具事件，前端 `onToolStart/onToolEnd` 只在 Plan 路径触发过。补上转发后，简单对话中 `search_notes_tool` 等工具也会显示状态指示。已核实前端实现为**轻量 state 更新**（[AIChat.tsx:314-319](front/src/pages/AIChat.tsx#L314-L319)：`setCurrentTool(name)` / `setCurrentTool('')`，无全屏遮罩），不会闪烁或遮挡；但 UI 上展示的是**原始工具名**（如 `generate_ppt_tool`），需在 `tool_start` 分支做中文名映射（见 §7）。对 PPT 场景这同时是生成中的进度指示（工具运行约 30s 期间状态持续可见，正好补上 §7 的进度反馈）。

- Plan 分支（[chat.py:448](app/routers/chat.py#L448)）：

```python
elif event_type in ("tool_start", "tool_end", "tool_file"):
    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
```

- Plan 分支内层 `_execute_step` 已是全量透传（[plan_execute_agent.py:256-257](app/ai_service/plan_execute_agent.py#L256-L257)），无需改。

**第 3 段：前端 useSSE 消费**（见 §7）

**兜底**：即便 `tool_file` 事件因任何原因丢失，工具的返回串（含 download_url）对 LLM 可见，LLM 的文本回复中也会提到「PPT 已生成」，前端渲染链接仍有兜底。

### 6.4 注入链路（审查问题 6）

`ppt_service` 与现有 `note_service`/`review_service` 走**完全相同的显式参数透传**方式（不引入新的 `agent_kwargs` 模式，保持项目现有风格；待未来工具增多（如 TODO 的 send_email）再统一重构为依赖字典）：

| 位置 | 当前签名/调用 | 改动 |
|---|---|---|
| [agent_tools.py:24-30](app/ai_service/agent_tools.py#L24-L30) `create_agent_tools()` | 已有 `note_service=None, review_service=None, db_session_factory=None, groups=None` | 新增 `ppt_service=None`，闭包捕获并注入新工具 |
| [agent_runner.py:74-84](app/ai_service/agent_runner.py#L74-L84) `execute_agent()` | 透传 `db_session_factory / note_service / review_service` | 新增 `ppt_service=None` 参数并透传 |
| [plan_execute_agent.py:193-205](app/ai_service/plan_execute_agent.py#L193-L205) `_execute_step()` | 同上 | 新增 `ppt_service=None`，透传给内部 `execute_agent`（L237-247） |
| [plan_execute_agent.py](app/ai_service/plan_execute_agent.py) `execute_plan_agent()` | 接收 `db_session_factory / note_service / review_service` | 新增 `ppt_service=None`，透传给 `_execute_step` |
| [chat.py](app/routers/chat.py) 4 处调用 | L342（ReAct）、L372（降级 ReAct）、L395（Plan）、L421（Plan 降级 ReAct） | 4 处全部补传 `ppt_service=ppt_service` |
| [main.py:49-59](app/ai_service/../main.py#L49-L59) `BackgroundInitManager.__init__` | 轻量服务初始化 | 同步创建 `self.ppt_service = PptService(load_ppt_config())`（**不持有模型**，见问题 3/8） |

**初始化策略（审查问题 8）**：`PptService` 是轻量对象（只读配置 + 目录初始化，不依赖模型），在 `BackgroundInitManager.__init__`（阶段 0）同步创建即可；`chat_model` 在阶段 1 才就绪，故 `generate()` 内部延迟从 `init_manager` 获取（§4.3）。

---

## 7. 前端改造（front/）

| 文件 | 改动 |
|---|---|
| [front/src/types/api.ts:260](front/src/types/api.ts#L260) | SSE 事件联合类型追加 `'tool_file'`；`onToolFile` 回调类型 |
| [front/src/hooks/useSSE.ts:162-169](front/src/hooks/useSSE.ts#L162-L169) | 增加 `case 'tool_file':` → `callbacks.onToolFile?.(data)`；`tool_start` 分支增加**工具名中文映射**（`generate_ppt_tool` → 「正在生成 PPT」，其他工具 → 显示名），`tool_end` 后清除 |
| [front/src/pages/AIChat.tsx](front/src/pages/AIChat.tsx) | ① 监听 `onToolFile`，在助手气泡下方渲染「📄 已生成讲解 PPT（N 页）」+ 下载按钮；② 下载走 JWT 鉴权 fetch |

笔记多选、`<referenced_notes>` 拼装均已存在，**零改动**。

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
| **config/ppt.yaml（新建，唯一承载 PPT 功能参数）** | `max_notes: 10`、`max_slides: 20`、`per_note_chars: 2000`、`total_context_chars: 12000`、`outline_timeout: 25`、`outline_retries: 1`、`file_ttl_hours: 24`、`max_files_per_user: 20`、`engine: "python_pptx"`、风格主题预设（business/academic/minimal 的配色与字体） | PPT 功能的所有参数集中在同一文件，便于维护 |

### 8.3 新增环境变量（.env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `PPT_ENGINE` | `python_pptx` | 渲染引擎切换（Phase 3 支持 `aspose_cloud`） |
| `ASPOSE_CLIENT_ID` / `ASPOSE_CLIENT_SECRET` | 空 | Aspose Cloud 凭证（Phase 3 才需要） |

### 8.4 超时与循环保护预算（审查问题 7 的边界控制）

| 环节 | 预算 | 说明 |
|---|---|---|
| 笔记批量读取 | ~0.5s | 单次 SQL，无风险 |
| 大纲生成（qwen3-max JSON mode） | **25s 内部超时**（`outline_timeout`） | 独立于 `LLM_STREAM_TIMEOUT`，`ChatOpenAI(request_timeout=25)` |
| 大纲解析失败重试 | +1 次（约 25s，仅解析失败才触发） | 重试前先校验；LLM 响应慢**不**触发重试，只解析失败才重试 |
| 渲染（to_thread） | <2s | 线程池，不占事件循环 |
| **ReAct 路径合计** | 正常 ~28s；最坏（重试）~53s | < `LLM_STREAM_TIMEOUT`（60s，[chat.py:40](app/routers/chat.py#L40)）✅ |
| Plan 路径 | 工具作为单步执行，`step_timeout=90s`（[agent.yaml:17](config/agent.yaml#L17)） | 重试场景也绰绰有余 ✅ |
| `max_consecutive_tool_calls=6`（[agent.yaml:10](config/agent.yaml#L10)） | 不受影响 | PPT 是单次工具调用，不构成连续空转 |

> 边界结论：ReAct 路径最坏情形 ~53s 距 60s 上限还有余量，但**余量有限** —— 若未来大纲 Prompt 变长或模型延迟升高，优先调大 `LLM_STREAM_TIMEOUT` 或缩短 `outline_timeout`，不要在工具内盲目加长内部超时。

---

## 9. 涉及改动文件清单

**新增**

| 文件 | 内容 |
|---|---|
| `app/services/ppt_service.py` | 生成管线：读笔记 → 大纲（LLM 延迟获取）→ 渲染（to_thread）→ 落盘 → TTL/配额清理 |
| `app/services/ppt_renderer.py` | `PPTRenderer` 接口 + `PythonPptxRenderer` 实现（Phase 3 加 `AsposeCloudRenderer`） |
| `app/schemas/ppt.py` | 大纲 Pydantic 模型（§4.4 代码）+ 解析校验函数 |
| `app/routers/ppt_router.py` | JWT 鉴权下载端点 |
| `config/ppt.yaml` | PPT 功能参数 + 风格主题预设（§8.2，**PPT 参数唯一归属**） |

**修改**

| 文件 | 改动 |
|---|---|
| `app/services/note_service.py` | 新增 `get_notes_by_ids(db, note_ids, user_id)`（签名见 §9.1） |
| `app/ai_service/agent_tools.py` | 工厂新增 `ppt_service=None` 参数 + `generate_ppt_tool` + 注册进 `all_tools`；**更新文件头注释：9 → 10 个工具**（[agent_tools.py:4](app/ai_service/agent_tools.py#L4)，`send_email` 仍是未注册占位，不计入） |
| `config/agent.yaml` | `ppt` 工具组 + 路由关键词（§4.2，**仅此两处**） |
| `app/ai_service/stream.py` | `on_tool_end` 读取 `data.output`，产出 `tool_file` 事件（§6.3 第 1 段） |
| `app/ai_service/agent_runner.py` | `execute_agent` 新增 `ppt_service=None` 并透传 |
| `app/ai_service/plan_execute_agent.py` | `execute_plan_agent` / `_execute_step` 新增 `ppt_service=None` 并透传 |
| `app/routers/chat.py` | 4 处调用补传 `ppt_service`；**简单路径补转发 `tool_start/tool_end/tool_file`**，Plan 路径白名单加 `tool_file` |
| `main.py` | `BackgroundInitManager.__init__` 创建 `self.ppt_service`；注册 ppt_router |
| `front/src/types/api.ts` / `useSSE.ts` / `AIChat.tsx` | `tool_file` 事件 + 下载卡片 + `generate_ppt_tool` 专用进度文案 |
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
| **SSE 链路断裂（tool_file 被 chat.py 丢弃）** | 前端收不到下载链接 | §6.3 三段式链路，**实施时先打通**：stream.py 产出 → chat.py 两分支白名单 → 前端消费；每段有单测/日志验证 |
| qwen3-max JSON 输出偶发格式错误（漏括号/字段） | 大纲解析失败 | Pydantic 严格校验 + 解析失败自动重试 1 次 + 兜底降级为「纯文本大纲」按章节模板渲染 |
| 大纲内容与笔记不符（幻觉） | 讲解跑偏 | Prompt 强约束「仅基于给定笔记内容」，渲染前抽查关键字段非空 |
| **大纲结构非法（缺封面/无内容页/总结页位置错）** | 渲染出残缺 PPT | `PPTOutline.model_validator` 自动修复（插封面、移总结页）；无内容页才抛错走重试/降级（§4.4） |
| **SQL `IN()` 不保证顺序** | 多笔记章节顺序与选择顺序不符 | `get_notes_by_ids` 内按输入顺序重排（§9.1 代码） |
| **简单路径新增工具事件转发（行为变更）** | 简单对话突然出现工具状态指示 | 已核实前端为轻量 state 无遮罩（§6.3 提示）；配合工具名中文映射；Phase 1 实施时观察确认 |
| 长笔记截断丢细节 | 内容不全 | 保留标题层级/首段/结论；截断处标注「详见笔记」 |
| **大纲重试 + 网络波动逼近 60s SSE 超时（ReAct 路径）** | SSE 超时中断 | `outline_timeout=25s` 内部超时 + 仅解析失败重试（§8.4）；前端 `tool_start` 显示「生成 PPT 约需 20~30 秒」；Plan 路径 90s 步超时无虞 |
| **python-pptx 同步渲染阻塞事件循环** | 全站请求卡顿 | `asyncio.to_thread`（§5.5） |
| **`list[str]` 工具参数与 qwen3-max 兼容性** | LLM 传参格式错误 | v1 用逗号分隔字符串（§4.1），与 `tags` 参数先例一致；Phase 2 再评估数组类型 |
| 文件服务磁盘膨胀 | 磁盘占满 | TTL 24h + 每用户 20 文件配额 + 启动时清理任务 |
| 越权下载他人 PPT | 隐私泄露 | file_id 格式校验 + 下载端点 JWT + 按 user_id 目录隔离 + sidecar 归属校验 |
| 关键词误路由（如「讲解」） | 频繁加载工具 | 只用组合关键词，或用消息长度守卫 |
| Aspose 计费不可控（Phase 3） | 成本 | 默认 python-pptx；Aspose 仅在有模板需求时启用，按次计费提醒 |

---

## 11. 分阶段落地计划

| 阶段 | 范围 | 预估 |
|---|---|---|
| **Phase 1（MVP）** | ① **优先打通 SSE 端到端链路**（stream.py 产出 → chat.py 两分支转发 → 前端 tool_file 消费，先用 mock 工具输出验证；同时验证简单路径新增 tool_start/tool_end 转发的前端表现）；② `PptService` + `generate_ppt_tool` + agent.yaml 配置 + 注入链路（§6.4 六处）；③ 下载端点（参数级 Depends）+ TTL/配额；④ python-pptx 基础版式（封面/目录/章节/内容/总结 + 演讲者备注）；⑤ 前端下载卡片 + 工具名中文映射 + 进度文案 | 3~4 天 |
| **Phase 2（质量）** | 大纲二次润色（content 页正文单独调 LLM 扩写）；config/ppt.yaml 风格预设扩充；代码块/表格/Markdown 清洗增强；真实进度事件（回调 + 独立 SSE 通道，若需要）；`note_ids` 数组参数兼容性评估 | 1~2 天 |
| **Phase 3（可选）** | `AsposeCloudRenderer`：设计模板（.pptx 模板填占位符）+ `PPT_ENGINE` 切换；PPT 历史记录（DB 表） | 按需 |

> 其他可选技术方向（供参考，非本方案推荐）：前端 PptxGenJS 直接生成（浏览器端免后端存储，但依赖前端实现大纲→版式逻辑，且无法复用后端 LLM 管线）；Marp 标记语言转 PPT（需在用户侧装 Marp，交付链路长）。当前方案为后端一次性生成 .pptx 文件，交付最直接。

---

## 12. 审查修订记录（v1.0 → v1.1 → v1.2）

| # | 优先级 | 问题 | 修订位置 |
|---|---|---|---|
| 1 | 🔴 | `tool_file` 事件在 chat.py 转发白名单中被静默丢弃（简单路径甚至不转发工具事件） | §2.2、§6.3 第 2 段 |
| 2 | 🔴 | stream.py `on_tool_end` 未读取 `event["data"]["output"]` | §6.3 第 1 段（含代码） |
| 3 | 🔴 | PptService 获取 LLM 实例的路径未设计 | §4.3「LLM 获取路径」（init_manager 延迟导入，与 chat.py:64 一致） |
| 4 | 🟡 | python-pptx 同步渲染阻塞事件循环 | §5.5（`asyncio.to_thread`） |
| 5 | 🟡 | `list[str]` 工具参数兼容性存疑 | §4.1（改为逗号分隔字符串，与 `tags` 先例一致） |
| 6 | 🟡 | `ppt_service` 注入链路描述不完整 | §6.4（六处注入点表格） |
| 7 | 🟡 | 35s 逼近 60s 超时边界、缺进度反馈 | §8.4（预算表）、§7（前端进度文案 + 不做工具内增量事件的理由） |
| 8 | 🟡 | PptService 初始化策略未明确 | §6.4 末段（阶段 0 轻量创建，模型延迟获取） |
| 9 | 🟢 | config/ppt.yaml 与 agent.yaml 配置归属重复 | §8.2（一刀切：agent.yaml 只管工具组/路由，PPT 参数全进 ppt.yaml） |
| 10 | 🟢 | 大纲 Schema 只有 JSON 示例没有 Pydantic 代码 | §4.4（完整模型代码） |
| 11 | 🟢 | 前端下载缺文件名与错误处理细节 | §7（完整下载代码 + 404/401 提示） |
| 12 | 🟢 | agent_tools.py 文件头工具计数需更新 | §9（9 → 10 个工具） |
| 13 | 🟢 | `get_notes_by_ids` 缺少签名设计 | §9.1（签名 + 语义：不抛 BusinessError，静默忽略无效 ID） |
| 14 | 🔴 | 下载端点双重依赖（装饰器级 + 参数级），归属校验风险 | §6.2（去掉 `dependencies=[...]`，只保留参数级 `Depends`，与 chat.py 风格一致） |
| 15 | 🟡 | SQL `IN()` 不保证返回顺序，影响 PPT 章节顺序 | §9.1（补重排代码：按输入顺序 sort） |
| 16 | 🟢 | 简单路径新增工具事件转发是行为变更 | §6.3（已核实前端为轻量 state 无遮罩；补工具名中文映射；Phase 1 验证） |
| 17 | 🟢 | `PPTOutline` 缺结构约束（封面/内容页/总结页位置） | §4.4（`model_validator` 自动修复：插封面、移总结页、无内容页才抛错） |
