# MCP 工具接入优先级推荐与实施路线

> 版本：v1.3（第八轮技术评审后修订：更新 langchain-mcp-adapters 版本要求与 Fetch 包名、刷新代码基准）  
> **文档目的：** 基于 [MCP 工具接入可行性分析与改造方案](MCP工具接入可行性分析与改造方案.md) 的架构结论，结合项目现有功能定位与能力缺口，给出 **Top 5 MCP Server 推荐排序**、场景匹配分析、兼容性确认与最小可行实施路线。  
> **前置依赖：** MCP 基础设施（`mcp_manager.py` + `langchain-mcp-adapters` + `tool_registry` 动态注册）已由改造方案 Part A 定义，本文档不重复设计，仅聚焦"接什么、先接哪个、怎么接"。  
> **代码基准：commit fe1f5ca（2026-08-08）**。全文行号与配置已对该 commit 校验；后续重构可能导致行号偏移，引用前请以最新 commit 为准核对。  
> **日期：** 2026-08-08  
> **状态：** 已经评审并实施（已根据第八轮技术评审反馈修订）

---

## 一、当前能力缺口分析

### 1.1 已有能力（12 个原生工具 + RAG）

| 能力域 | 覆盖工具 | 能力边界 |
|---|---|---|
| 笔记管理 | `create_note_tool` / `update_note_tool` / `search_notes_tool` / `get_note_content_tool` / `get_note_stats_tool` / `get_related_notes_tool` | 完整的 CRUD + 语义搜索 + 关联推荐 |
| 知识回顾 | `get_today_reviews_tool` / `mark_reviewed_tool` | 艾宾浩斯间隔重复 |
| AI 对话 | ReAct（简单）+ Plan-Execute（复杂）+ QueryClassifier 路由 | 双模式对话引擎 |
| 知识检索 | RAG（HyDE + 双源检索 + 重排序 + 分批总结） | **仅限用户上传文档 + 本地笔记** |
| 内容输出 | `send_email`（邮件）/ `generate_ppt_tool`（PPT） | Markdown/PDF 附件 + 讲解幻灯片 |
| 基础信息 | `what_time_is_now` / `get_user_info_tools` | 时间 + 用户信息 |

### 1.2 缺失能力（MCP 补位方向）

| 缺失能力 | 影响的核心场景 | 原生实现可行性 |
|---|---|---|
| **联网搜索** | "帮我查一下最近 AI 论文进展并整理成笔记" | ❌ 搜索引擎对接工作量大，且需持续维护索引 |
| **网页内容提取** | "把这篇博客整理成笔记 https://..." | ❌ HTML 解析/清洗/去噪规则维护成本高 |
| **浏览器自动化** | JS 渲染页面、需交互的复杂网页 | ❌ 需完整浏览器运行时 |
| **代码执行** | 学习场景下运行代码片段验证结果 | ❌ 需沙箱隔离，安全风险高 |
| **学术/论文检索** | "最近 XX 领域有什么新进展" | ❌ 学术 API 对接 + 结果格式化 |

**结论：** 以上 5 项均属于"项目边界之外的能力"，符合 MCP 改造方案 §2.2 的双轨制原则——**MCP 只接外部能力，内部业务工具保持原生**。

---

## 二、推荐排序总览

按「用户价值 × 实现成本」综合评分：

| 排名 | MCP Server | 核心能力 | 用户价值 | 实现成本 | 综合评分 | 建议阶段 |
|---|---|---|---|---|---|---|
| **#1** | **Tavily** | 联网搜索 + URL 内容提取 | ★★★★★ | ★☆☆☆☆ 极低 | **95** | Phase 1（必接） |
| **#2** | **Fetch** | 通用网页内容抓取 | ★★★★☆ | ★☆☆☆☆ 极低 | **88** | Phase 1（必接） |
| **#3** | **Playwright** | 浏览器自动化 | ★★★☆☆ | ★★★☆☆ 中等 | **65** | Phase 2 |
| **#4** | **Brave Search** | 备选搜索引擎 | ★★★☆☆ | ★☆☆☆☆ 极低 | **62** | 可选/备选 |
| **#5** | **Python REPL** | 代码执行沙箱 | ★★☆☆☆ | ★★☆☆☆ 较低 | **52** | Phase 3 |

---

## 三、Top 5 详细分析

### 3.1 #1 Tavily — AI 原生联网搜索（强烈推荐）

#### 是什么

专为 AI Agent 设计的搜索 API，返回经 AI 优化的结构化搜索结果（标题 + 摘要 + 相关度评分），自带搜索与 URL 内容提取能力。`tavily-mcp` 0.2.22 实测暴露 5 个工具：`tavily_search` / `tavily_extract` / `tavily_crawl` / `tavily_map` / `tavily_research`（Phase 1 建议按 §7 #3 在 `mcp_manager` 层白名单仅启用前两个）。

#### 解决的具体场景

| 场景 | 用户原话示例 | 当前系统表现 | +Tavily 后 |
|---|---|---|---|
| 实时信息查询 | "帮我查一下最近一个月 AI 论文进展并整理成笔记" | RAG 仅检索本地文档，无外部信息 | 搜索最新论文 → 整理 → `create_note_tool` 保存 |
| 技术问答补充 | "FastAPI 最新版本有什么变化？" | RAG 无此文档时无法回答 | 搜索官方文档 → 返回最新信息 |
| URL 内容提取 | "帮我总结这篇文章 https://xxx" | 无法访问 URL | `tavily_extract` 直接提取正文 |
| 结合 PPT 生成 | "搜索 XX 主题的最新资料，做成 PPT" | 无外部数据源 | 搜索 → 整理 → `generate_ppt_tool` |
| 结合邮件导出 | "搜一下 XX 的最新教程发到我邮箱" | 无外部数据源 | 搜索 → 整理 → `send_email` 发送 |

#### 与现有功能的协同链路

```
用户: "帮我查一下最近 AI Agent 的研究进展，整理成笔记"
  → tavily_search("AI Agent 最新研究进展 2026")
  → 搜索结果 + LLM 整理
  → create_note_tool(title="AI Agent 研究进展", content=...)
  → 返回笔记 ID
  → 后续可触发：间隔回顾 / 邮件导出 / PPT 生成
```

#### 兼容性确认

| 维度 | 状态 |
|---|---|
| 官方 MCP Server | `tavily-mcp`（npm 包，`npx tavily-mcp@latest`）✅ |
| `langchain-mcp-adapters` 适配 | `MultiServerMCPClient` 直接接入，社区已验证 ✅ |
| API Key | 需要 `TAVILY_API_KEY`（credits 制，免费额度需以 [tavily.com](https://tavily.com) 官网实时说明为准，个人日常使用通常充足） |
| Token 消耗 | 每次搜索约 500~1500 tokens，可控 |
| 中文支持 | 良好，中英文搜索均可用 |
| Windows 兼容 | stdio 子进程模式，需 Phase 0 验证 |

#### 实施成本

~0.5 天（Phase 0 验证 + 配置 + 联调），**全部推荐中 ROI 最高**。

---

### 3.2 #2 Fetch — 通用网页内容抓取（强烈推荐）

#### 是什么

MCP 官方参考 Server（`mcp-server-fetch`，Python 版，`uvx` 启动），发送 HTTP GET 请求后自动将 HTML 转换为干净的 Markdown，去除广告、导航、侧边栏等噪音。

#### 解决的具体场景

| 场景 | 用户原话示例 | Fetch 能否处理 | +Fetch 后 |
|---|---|---|---|
| 博客/文章提炼 | "把这篇博客整理成笔记 https://..." | ✅ | 抓取 → Markdown → `create_note_tool` |
| 官方文档查阅 | "帮我看看这个 API 的用法 https://docs..." | ✅ | 抓取文档内容 → 精确回答 |
| 多源信息聚合 | "对比这三篇文章的观点" + 3 个 URL | ✅ | 分别抓取 → LLM 对比分析 |
| 结合 RAG 入库 | 抓取外部文档存入知识库 | ✅ | 自动抓取 → `vector_store` 入库 |

#### 与 Tavily 的分工

| 维度 | Tavily | Fetch |
|---|---|---|
| 擅长 | **搜索**（给关键词 → 返回多源结果） | **提取**（给 URL → 返回单页完整内容） |
| 输入 | 搜索查询 / URL | 仅 URL |
| 输出 | 结构化搜索结果（多源摘要） | 单页完整 Markdown |
| 需要 API Key | 是 | **否（零配置）** |
| JS 渲染 | 否 | 否（纯 HTTP GET） |
| 适用场景 | "帮我搜一下 XX" | "帮我读一下这个链接" |

> Tavily 的 `tavily_extract` 也能提取 URL 内容，但 Fetch 更通用（无 API Key 限制、支持任意 HTTP 方法、返回更完整的页面内容）。两者互补而非重复。

#### 兼容性确认

| 维度 | 状态 |
|---|---|
| 官方 MCP Server | `mcp-server-fetch`（Python uvx）✅（npm 包 `@modelcontextprotocol/server-fetch` 不存在，统一使用 Python 包；**需固定 `mcp<2`**，见 §5.1 注） |
| `langchain-mcp-adapters` 适配 | 直接兼容 ✅ |
| API Key | **不需要**（零外部依赖） |
| 项目依赖 | 已有 `httpx>=0.28.0`，网络层兼容 ✅ |
| Windows 兼容 | stdio 子进程，轻量无浏览器依赖；但 stdio 子进程 spawn/回收在 Windows 下需 Phase 0 统一验证（见 §7 #1）⚠️ |

#### 实施成本

~0.3 天（最简单的一个，零配置即可跑通）。

---

### 3.3 #3 Playwright — 浏览器自动化（推荐，Phase 2）

#### 是什么

Microsoft 官方 MCP Server，提供完整的浏览器自动化能力——页面导航、元素交互、表单填写、截图、JS 渲染页面内容提取。

#### 解决的具体场景

| 场景 | 当前系统表现 | +Playwright 后 |
|---|---|---|
| JS 渲染页面（SPA） | Fetch 纯 HTTP 拿不到内容 | ✅ 完整渲染后提取 |
| 需要登录/表单交互 | ❌ 需要点击/输入 | ✅ 自动填表/登录 |
| 页面截图存档 | ❌ 无法截图 | ✅ 页面截图返回 |
| 动态加载（滚动翻页） | ❌ 无法滚动 | ✅ 模拟滚动/翻页 |

#### 为什么不排更高

- 实现成本明显高于前两个（需安装浏览器二进制文件、Windows 下进程管理更复杂）
- 使用频率低于搜索/抓取（大多数场景 Fetch + Tavily 已覆盖）
- MCP 改造方案 §5 风险 #3 特别提到 Windows 下 stdio 子进程管理需注意

#### 兼容性确认

| 维度 | 状态 |
|---|---|
| 官方 MCP Server | `@playwright/mcp`（npm，Microsoft 维护，[microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp)）✅ |
| `langchain-mcp-adapters` 适配 | 兼容 ✅ |
| Windows 兼容 | 需 `npx @playwright/mcp@latest`（需另装浏览器二进制，见 Phase 3 `playwright install chromium`），Phase 0 验证 ⚠️ |
| 安全注意 | 浏览器拥有完整网络访问能力，需严格限制（生产环境建议沙箱模式）⚠️ |

#### 实施成本

~1 天（含浏览器安装 + Windows 适配 + 安全策略）。建议放在 Phase 2，在 #1 #2 验证通过后再投入。

---

### 3.4 #4 Brave Search — 备选搜索引擎（可选）

#### 是什么

modelcontextprotocol 组织维护的 MCP 参考 Server（`@modelcontextprotocol/server-brave-search`），基于 Brave 搜索引擎的高质量网络搜索。

#### 与 Tavily 的对比

| 维度 | Tavily | Brave Search |
|---|---|---|
| 结果质量 | AI 优化摘要（直接可用） | 原始搜索结果（标题+摘要+URL） |
| 中文支持 | 良好 | **更好**（Brave 中文索引覆盖更全） |
| 免费额度 | credits 制（免费额度需以 [tavily.com](https://tavily.com) 官网实时说明为准） | 按查询次数计费（免费额度需以 [brave.com/search/api](https://brave.com/search/api) 官网实时说明为准） |
| 额外工具 | `tavily_extract`（URL 提取） | 仅搜索 |
| LangChain 集成 | 好 | 好（modelcontextprotocol 组织维护，与 Fetch 同源码仓库） |
| Token 消耗 | 较低（AI 摘要精简） | 中等（原始结果较长） |

#### 推荐理由

如果实际使用中发现 Tavily 中文搜索结果质量不理想，Brave Search 是最佳备选。两者可以共存（搜索时 LLM 根据场景选择），但**建议先只接 Tavily，不够再加 Brave**，避免初期工具过多导致 token 膨胀和 LLM 选择困难。

#### 实施成本

~0.3 天（与 Tavily 接入模式完全相同）。

---

### 3.5 #5 Python REPL — 代码执行沙箱（低优先级）

#### 是什么

在安全沙箱中执行 Python 代码，返回运行结果（stdout / stderr / 图片输出）。

#### 解决的具体场景

| 场景 | 当前系统表现 | +REPL 后 |
|---|---|---|
| 代码验证 | "帮我跑一下这段代码看看结果" → 只能文字解释 | 实际执行 + 返回输出 |
| 数据处理可视化 | "把这组数据画个图" → 无法处理 | 执行 matplotlib → 返回图片 |
| 学习练习 | "运行这个算法看看对不对" → 只能文字反馈 | 执行 + 对比预期输出 |

#### 为什么不排更高

- 与项目核心定位（笔记管理 + 知识回顾）关联度较低
- 安全风险最高（执行任意代码需要严格沙箱隔离）
- MCP 改造方案 §2.3 列为「典型适用场景」之一，但优先级低于搜索/抓取

#### 兼容性确认

| 维度 | 状态 |
|---|---|
| MCP Server | 社区多个实现（`mcp-server-python-repl` 等）✅ |
| 安全 | 建议 Docker 沙箱隔离或白名单模块 ⚠️ |
| `langchain-mcp-adapters` 适配 | 兼容 ✅ |

#### 实施成本

~1.5 天（含沙箱安全策略 + Docker 配置）。建议放在 Phase 3 或按需评估。

---

## 四、实施路线

### 4.1 分阶段计划

```
Week 1 Day 1     Phase 0：版本兼容验证（阻塞项，必须先做）
                 ├─ pip install langchain-mcp-adapters
                 ├─ 最小 demo：MultiServerMCPClient + Tavily 跑通
                 └─ 验证 Windows stdio 子进程正常 spawn/回收

Week 1 Day 2-3   Phase 1：MCP 基础设施 + #1 Tavily + #2 Fetch
                 ├─ mcp_manager.py（MCP 客户端生命周期管理）
                 ├─ agent.yaml 新增 mcp_servers 段
                 ├─ agent_runner.py 无需改动（MCP 工具由 create_agent_tools 自动解析）
                 ├─ main.py 挂载 start/close（~20 行）
                 ├─ .env 新增 TAVILY_API_KEY
                 └─ tool_registry 动态注册联调

Week 1 Day 4     Phase 2：联调 + 提示词 + 前端验证
                 ├─ prompts/main_prompt.txt 补充 MCP 工具说明
                 ├─ 验证 Plan-Execute 路径 MCP 工具可用
                 ├─ SSE 前端正常展示 MCP 工具调用状态
                 └─ 端到端场景验证（搜索→笔记→回顾→PPT）

Week 2（可选）    Phase 3：#3 Playwright 浏览器自动化
                 ├─ playwright install chromium
                 ├─ Windows 进程管理适配
                 └─ 安全策略（域名白名单）

Week 3（可选）    Phase 4：#4 Brave Search（Tavily 中文不够时）
未来              Phase 5：#5 Python REPL（学习场景需求明确时）
```

### 4.2 改动范围（Phase 1 最小可行）

| 文件 | 改动 | 估算 |
|---|---|---|
| `requirements.txt` | 新增 `langchain-mcp-adapters>=0.3.2`（需 `langchain-core>=1.3.3`，当前 1.4.5 满足） | 1 行 |
| `config/agent.yaml` | 新增 `mcp_servers` 配置段 + `default_groups` 追加 `mcp`（§5.1 + §5.2） | ~16 行 |
| `app/utils/config.py` | 新增 `get_mcp_servers_config()` | ~6 行 |
| `app/ai_service/mcp_manager.py` | **新增**：MCP 客户端生命周期管理 | ~200 行 |
| `app/ai_service/agent_runner.py` | 如走 §5.2 注册表方案则无需改动（`create_agent_tools` 已能通过 `get_dynamic` 解析 MCP 工具） | 0 行 |
| `main.py` | `BackgroundInitManager` 挂载 MCP start/close | ~20 行 |
| `.env` / `.env.example` | 新增 `TAVILY_API_KEY` | 1 行 |
| `prompts/main_prompt.txt` | 补充 MCP 工具存在说明 | ~3 行 |

**总计：~260 行新增/修改**（MCP 改造方案 §4 估算为 4~6 人日含加固与测试，此处为 Phase 1 MVP 代码量，口径不同但量级一致）。

---

## 五、配置设计

### 5.1 agent.yaml 新增段

```yaml
# MCP 动态工具配置
mcp_servers:
  # #1 Tavily：联网搜索 + URL 内容提取（必接）
  tavily:
    transport: "stdio"
    command: "npx"
    args: ["-y", "tavily-mcp@latest"]
    env:
      TAVILY_API_KEY: "${TAVILY_API_KEY}"
    enabled: true

  # #2 Fetch：通用网页抓取（必接）
  # 注：必须固定 mcp<2 —— mcp-server-fetch 2026.7.10 与 mcp SDK 2.x 不兼容
  # （2.x 移除了 mcp.shared.exceptions.McpError，不固定时 uvx 解析到最新 mcp 2.x，
  #   启动即 ImportError；实测 2026-08-08）
  fetch:
    transport: "stdio"
    command: "uvx"
    args: ["--with", "mcp<2", "mcp-server-fetch"]
    enabled: true

  # #3 Playwright：浏览器自动化（Phase 2 可选）
  # playwright:
  #   transport: "stdio"
  #   command: "npx"
  #   args: ["-y", "@playwright/mcp@latest"]
  #   enabled: false
```

### 5.2 tool_groups 必须改动：将 `mcp` 加入 `default_groups`

> ⚠️ **关键修正**：MCP 改造方案 §3.2 描述的「全量合并」是目标设计，但**当前代码并未实现**。已核实：
>
> - [agent_runner.py:24-67](../app/ai_service/agent_runner.py#L24-L67) `resolve_tool_groups()` 仅从 `agent.yaml` 的 `default_groups`（base / note_read / note_write / review / email）+ `keyword_rules` 命中结果出发构建工具列表；
> - [plan_execute_agent.py:209-248](../app/ai_service/plan_execute_agent.py#L209-L248) `_resolve_step_tool_groups()` 也只从 `agent.yaml` 的 `tool_groups` 建反向映射；
> - [tool_registry.py:59-64](../app/ai_service/tool_registry.py#L59-L64) 中 MCP 动态工具注册进 `"mcp"` 组，但上述两条路径**都不会解析到注册表里的 `"mcp"` 组**。
>
> 即：如果只依赖 `tool_registry.register_tool` 动态注册而不修改 `default_groups`，MCP 工具会被**静默跳过**。

**正确做法**：在 `agent.yaml` 的 `default_groups` 中追加 `mcp`：

```yaml
default_groups:
  - base
  - note_read
  - note_write
  - review
  - email
  - mcp           # ★ 新增：MCP 动态工具组（tool_registry 自动创建）
```

这样 `resolve_tool_groups` 在解析 `default_groups` 时，会通过 `tool_registry.resolve_names(["mcp"])` 取出已注册的 MCP 动态工具（[agent_tools.py:481-483](../app/ai_service/agent_tools.py#L481-L483) 的 `get_dynamic` 分支）。`keyword_rules` 中的 `mcp` 关键词已废弃（组已全量加载，关键词规则为 no-op，见 §5.3）。

**方案选择**：上述 `default_groups` 改动仅修复关键词路由路径。更彻底的做法是在 `create_agent_tools` 解析处将 `tool_registry` 动态组**无条件并入**工具列表（不论 `groups` 参数如何）——若采用此方案，`default_groups` 改动可省略（无害但多余）。

> ⚠️ **覆盖范围与取舍**：无条件并入仅闭合**步骤执行阶段**缺口（gap #2）；**规划阶段**缺口（gap #1）仍在——`_build_plan_tool_list` 仍从 `agent.yaml` 的 `tool_groups` 读取，planner 不感知 MCP 工具。这在实际场景中**通常可接受**：搜索类步骤 planner 通常写 `tool=none`，回退关键词路由后 MCP 照样在场。若需 planner 显式规划 MCP 工具名（如直接输出 `tavily_search`），还需额外在 `_build_plan_tool_list` 并入动态工具名。
>
> 若不走无条件并入方案，则需同时改三处：① `default_groups` 加 `mcp`（§5.2）+ ② `_build_plan_tool_list` 补 MCP 动态工具 + ③ `_resolve_step_tool_groups` 返回时补 `mcp`。

### 5.3 tool_routing 关键词规则（已废弃——default_groups 含 mcp 后为 no-op）

> `mcp` 进入 `default_groups` 后，每轮对话已全量加载 MCP 工具。`keyword_rules` 中的 `mcp` 关键词无论是否命中，都不改变工具加载结果——是 no-op。
>
> 如未来 `default_groups` 改为精简模式（移除 `mcp`），可重新启用以下关键词规则实现按需加载：
>
> ```yaml
> tool_routing:
>   keyword_rules:
>     mcp:
>       - "搜索一下"
>       - "上网查"
>       - "帮我查一下"
>       - "这个链接"
>       - "这个网页"
> ```
>
> 现有 `tool_keywords` 中已有 `"搜索"` 关键词触发 `note_read` 组。新增 `"搜索一下"` / `"上网查"` 等组合词可区分"搜笔记"与"搜网络"的意图差异。

### 5.4 环境变量

```bash
# .env 新增
TAVILY_API_KEY=tvly-xxxxxxxxxxxxx     # Tavily 搜索 API Key（tavily.com 注册）
```

> ⚠️ **环境变量插值注意**：`config.py` 使用 `yaml.safe_load` 加载配置，**不会自动展开** `${TAVILY_API_KEY}` 等环境变量。`mcp_manager.py` 在读取 `mcp_servers.*.env` 时需手动调用 `os.path.expandvars()` 对值进行展开。另外 Fetch 使用 `uvx` 启动，Windows 下需先确保已安装 `uv`（`pip install uv`），否则 `uvx` 命令不可用。
>
> **日志噪音**：`default_groups` 含 `mcp` 但实际未配置任何 MCP server 时，`create_agent_tools` 每轮会打一条 `"工具组 'mcp' 未在 agent.yaml 中定义，跳过"` 的 warning（[agent_tools.py:469-471](../app/ai_service/agent_tools.py#L469-L471)）。不影响功能，可在 `init_tool_registry` 末尾无条件注册空 `mcp` 组消除此日志。

---

## 六、与现有功能的协同矩阵

MCP 工具与原生工具形成完整闭环：

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP 外部能力层                             │
│  Tavily（联网搜索/URL提取）  Fetch（网页抓取）  Playwright（浏览器） │
└──────────────────────────────┬──────────────────────────────────┘
                               │ 搜索结果 / 网页内容
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                       原生工具处理层                              │
│  create_note_tool ──→ 存为笔记                                   │
│  update_note_tool ──→ 追加到已有笔记                              │
│  send_email      ──→ 邮件导出                                    │
│  generate_ppt_tool ─→ 生成讲解 PPT                               │
└──────────────────────────────┬──────────────────────────────────┘
                               │ 笔记已存储
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                       知识管理层                                 │
│  RAG 知识库 ──→ 文档检索增强                                     │
│  间隔重复回顾 ──→ get_today_reviews / mark_reviewed              │
│  语义搜索 ──→ search_notes / get_related_notes                   │
└─────────────────────────────────────────────────────────────────┘
```

**典型端到端链路**：

| 链路 | 工具调用序列 |
|---|---|
| 搜索→笔记 | `tavily_search` → LLM 整理 → `create_note_tool` |
| 抓取→笔记 | `fetch` → LLM 提炼 → `create_note_tool` |
| 搜索→PPT | `tavily_search` → LLM 整理 → `create_note_tool` → `generate_ppt_tool` |
| 搜索→邮件 | `tavily_search` → LLM 整理 → `send_email` |
| 抓取→RAG 入库 | `fetch` → 文档内容 → `vector_store.upsert_document`（需扩展管线） |
| 笔记→回顾 | 间隔重复触发 → `get_today_reviews_tool` → `mark_reviewed_tool` |

---

## 七、风险与规避

| # | 风险 | 等级 | 规避措施 |
|---|---|---|---|
| 1 | **Windows stdio 子进程兼容性** | 🟡 中 | Phase 0 先验证 `npx` / `uvx` 子进程可正常 spawn 与回收；失败则切换 streamable-http transport |
| 2 | **Tavily API 额度耗尽** | 🟢 低 | Tavily 现行为 credits 制（搜索/提取各消耗不同 credits，免费额度需以官网实时说明为准）；进程内按用户限流（参照 `send_email` 的 `_email_rate_allowed` 模式） |
| 3 | **MCP 工具描述膨胀 token** | 🟡 中 | Phase 1 实测 Tavily 暴露 5 个工具（非 2 个，含 crawl/map/research）+ Fetch 1 个，共 6 个，token 增量约 1500~3000，在 `model_context_size: 32768` 内可控；**Phase 2 若接入 Playwright 需注意其暴露约 20 个工具**（browser_navigate / click / type / snapshot / screenshot / evaluate 等），工具总数将从 12+6 跃至 ~38，token 增量可达 5000~8000——建议在 `mcp_manager` 层做工具名白名单过滤（Phase 1 即可对 Tavily 只启用 `tavily_search` + `tavily_extract`） |
| 4 | **工具名冲突** | 🟢 低 | `tool_registry` 已有冲突检测（`register_tool` 重名报错）；MCP 工具名由 server 声明，与 12 个内置工具无交集 |
| 5 | **MCP server 连接失败** | 🟡 中 | `mcp_manager` 降级策略：连接失败 → 跳过该 server → 记日志 → Agent 主流程不受影响（与改造方案 §3.3 一致） |
| 6 | **Playwright 安全风险** | 🟡 中 | 生产环境限制域名白名单；禁止用户自定义 server（仅管理员配置）；浏览器运行在沙箱模式 |
| 7 | **qwen3-max 多工具选择退化** | 🟢 低 | Phase 1 工具总数从 12 增至 18（Tavily 5 + Fetch 1，实测），仍在 qwen3-max function calling 能力范围内；Phase 2 若接入 Playwright 需关注工具数膨胀（见风险 #3）；`main_prompt.txt` 补充工具使用指引 |

---

## 八、排除项说明

以下 MCP Server 经评估后**不推荐接入**，理由如下：

| MCP Server | 排除理由 |
|---|---|
| 笔记类 MCP（如 Notion MCP） | 与现有 `create_note_tool` / `update_note_tool` 功能重复 |
| 邮件类 MCP | 与现有 `send_email` 功能重复，且定制逻辑（PDF 渲染、审计日志）无法迁移 |
| 日历/提醒 MCP | 与现有 `review_service` 间隔重复回顾功能部分重叠，且非核心需求 |
| 数据库类 MCP（PostgreSQL/SQLite） | 项目已使用 SQLAlchemy 直连 MySQL，MCP 数据库层无收益 |
| 文件系统 MCP | PPT 下载、模板上传已走自有存储方案（`data/ppt/`、`data/ppt_templates/`），无需 MCP 文件层 |

---

## 九、结论

1. **Phase 1 必接**：Tavily（联网搜索）+ Fetch（网页抓取）—— 1 天内完成，立即解锁"联网搜索 + 网页提炼 → 整理成笔记"最高频场景链路。
2. **Phase 2 按需**：Playwright（浏览器自动化）—— 仅在 JS 渲染/交互场景需求明确时投入。
3. **可选备选**：Brave Search —— Tavily 中文搜索不够时补充。
4. **远期评估**：Python REPL —— 学习场景需求明确时再投入。
5. **不接**：与现有 12 个原生工具功能重叠的 MCP Server。

**一句话**：先接 Tavily + Fetch，1 天完成，ROI 最高，风险最低，立即打通“外部信息 → 笔记 → 回顾 → 导出/PPT”完整闭环。

---

## 十、审查修订记录（v1.0 → v1.1）

| # | 优先级 | 问题 | 修订位置 |
|---|---|---|---|
| A1 | 🔴 | §5.2 声称“default_groups 全量加载已天然覆盖 MCP 工具”，但 `resolve_tool_groups` 和 `_resolve_step_tool_groups` 均不会解析注册表中的 `"mcp"` 组，MCP 工具会被静默跳过 | §5.2 重写为“必须将 `mcp` 加入 `default_groups`”，含代码示例与替代方案 |
| A2 | 🔴 | §3.3 Playwright 包名 `@anthropic/mcp-playwright` 不存在，正确为 `@playwright/mcp`（Microsoft 维护） | §3.3 兼容性表 + §5.1 配置示例均已修正 |
| A3 | 🔴 | §7 #3/#7 工具数量假设错误（Playwright 实际暴露约 20 个工具，非 2 个） | §7 #3 重写，分 Phase 1 / Phase 2 两档估算；#7 同步更新 |
| A4 | 🟡 | §4.2 `langchain-mcp-adapters>=0.1.0` 版本下限过时 | 改为 `>=0.2.2`，注明需 `langchain-core>=1.0` |
| A5 | 🟡 | §6 协同矩阵引用 `vector_store.add_documents` 不存在 | 改为 `vector_store.upsert_document`（[vector_store.py:118](../app/rag/vector_store.py#L118)） |
| B1 | 🟡 | §3.2 Fetch Windows 兼容性标 ✅ 与 §7 #1 标 🟡 矛盾 | §3.2 改为 ⚠️ 并注明“需 Phase 0 统一验证” |
| B2 | 🟡 | §5.2 vs §5.3 自相矛盾（§5.2 说无需改动，§5.3 建议加关键词） | §5.2 重写后逻辑一致：必须先加 `default_groups`，关键词规则为加速补充 |
| B3 | 🟢 | §4.2 “与改造方案 §4 估算一致”口径不同 | 改为注明“改造方案 §4 为 4~6 人日含加固与测试，此处为 Phase 1 MVP 代码量” |
| C1 | 🟡 | 代码基线已过期（c6f5f81 → 965e15a） | 头部更新为 commit 965e15a（2026-08-07） |
| C2 | 🟡 | §3.2/§3.4 “Anthropic 官方维护”描述不准确 | 改为“modelcontextprotocol 组织维护” |
| C3 | 🟡 | §3.1 Tavily “免费 1000 次/月”已过期（现为 credits 制） | 改为“credits 制，以官网实时说明为准”；§7 #2 同步 |
| C4 | 🟡 | §5.1 `${TAVILY_API_KEY}` 插值坑 + Fetch 用 uvx 未提 Windows 需装 uv | §5.4 末尾补注意说明 |
| C5 | 🟢 | §3.5 引用“改造方案 §2.3 列为未来场景”不准确 | 改为“§2.3 列为「典型适用场景」之一” |
| D1 | 🟢 | §3.3 表头与全文风格不一致 | 改为“当前系统表现 | +Playwright 后” |
| D2 | 🟢 | §5.3 关键词"最新"误伤率高 | 删除"最新"，改为"帮我查一下" |

---

## 十一、审查修订记录（v1.1 → v1.2）

| # | 优先级 | 问题 | 修订位置 |
|---|---|---|---|
| R1 | 🔴 | §5.2 `default_groups` 加 `mcp` 只覆盖关键词路由路径；Plan-Execute 的 `_build_plan_tool_list` 和 `_resolve_step_tool_groups` 仍不感知 MCP 动态组，planner 不会规划 MCP 工具步骤、指定内置工具的步骤不带 `mcp` 组 | §5.2 新增"Plan-Execute 路径缺口"警告段，给出推荐修复方案（`create_agent_tools` 无条件并入动态组） |
| R2 | 🔴 | §4.2 仍列 `agent_runner.py | ~10 行`改动，与 §5.2 注册表方案冲突（`get_dynamic` 已能解析 MCP 工具，`agent_runner.py` 零改动） | §4.2 该行改为"如走 §5.2 注册表方案则无需改动 \| 0 行" |
| S1 | 🟢 | §5.3 `keyword_rules` 中 `mcp` 关键词在 `default_groups` 含 `mcp` 后为 no-op，"提前加载/区分意图"说明不成立 | §5.3 标题改为"已废弃——no-op"，内容改述为未来精简 `default_groups` 时的备选 |
| S2 | 🟢 | §3.4 Brave 免费额度"1000 次/月（credits 制）"混合单位，与 §3.1/§7 #2"以官网为准"矛盾 | §3.4 改为"credits 制，以官网实时说明为准"，与 Tavily 口径统一 |
| S3 | 🟢 | §3.3 "内置浏览器管理"措辞与 Phase 3 `playwright install chromium` 矛盾——`@playwright/mcp` 不捆绑浏览器二进制 | §3.3 改为"需另装浏览器二进制，见 Phase 3" |
| S4 | 🟢 | §4.2 `agent.yaml` 行估算只计 `mcp_servers` ~15 行，漏 §5.2 `default_groups` +1 行 | §4.2 改为 ~16 行，注明含 §5.1 + §5.2 |
| S5 | 🟢 | `default_groups` 含 `mcp` 但无 MCP server 配置时，每轮打 warning 日志 | §5.4 补日志噪音说明与消除方案 |
| N1 | 🟡 | §4.1 Phase 1 计划图仍写 `agent_runner.py 合并 MCP 工具（~10 行）`，与 §4.2（0 行）矛盾 | §4.1 改为"无需改动（MCP 工具由 create_agent_tools 自动解析）" |
| N2 | 🟡 | §5.2 "正确做法"与"推荐修复"关系未说清；推荐修复仅闭合执行缺口，规划阶段 gap 未说明取舍 | "替代方案"重写为"方案选择"，明确两方案替代关系、推荐修复仅覆盖执行路径、planner 不感知 MCP 属可接受取舍 |
| N3 | 🟢 | §3.4 Brave 被错贴"credits 制"标签——Brave 免费档按查询次数计费，非 credits 制 | Brave 列改为"按查询次数计费（以官网为准）"，Tavily 保持 credits 制 |
| N4 | 🟢 | 头部状态行仍写"第六轮"，与版本 v1.2（第七轮）不同步 | 改为"第七轮" |

---

## 十二、审查修订记录（v1.2 → v1.3）

| # | 优先级 | 问题 | 修订位置 |
|---|---|---|---|
| T1 | 🟡 | §4.2 `langchain-mcp-adapters>=0.2.2`（需 `langchain-core>=1.0`）版本要求过时；pip 实测最新为 0.3.2，实际要求 `langchain-core>=1.3.3`（已装 1.4.5 满足） | §4.2 改为 `>=0.3.2`（需 `langchain-core>=1.3.3`） |
| T2 | 🟡 | §3.2 Fetch npm 包名 `@modelcontextprotocol/server-fetch` 不存在（npm 404），正确包名为 `mcp-server-fetch`（npm / PyPI 同名） | §3.2 正文与兼容性表修正包名，统一使用 Python 版（`uvx` 启动） |
| T3 | 🟡 | 代码基线已过期（965e15a → fe1f5ca），全文行号需重新核对 | 头部代码基准更新为 fe1f5ca（2026-08-08）；§3.2/§4.2/§5.2 引用行号已对该 commit 复核一致 |
| T4 | 🟡 | §3.1/§7 称 Tavily 暴露 2 个工具，实测 tavily-mcp 0.2.22 暴露 5 个（search/extract/crawl/map/research） | §3.1 改为 5 个工具列举；§7 #3/#7 token 与工具总数估算同步修正；建议 Phase 1 即在 `mcp_manager` 层白名单过滤 |
| T5 | 🔴 | §5.1 Fetch 配置未固定 mcp 版本——实测 mcp-server-fetch 2026.7.10 与 mcp SDK 2.x 不兼容（2.x 移除 `mcp.shared.exceptions.McpError`），uvx 解析到最新 mcp 2.x 时启动即 ImportError | §5.1 配置加 `--with mcp<2` 固定并附注；§3.2 兼容性表同步注明。Phase 0 已在本机实测：npx tavily-mcp / uvx fetch（固定后）stdio 子进程 spawn/回收与 JSON-RPC 均通过，Fetch 真实抓取 URL 成功 |
