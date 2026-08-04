# MCP 工具接入 与 Reflection 反思机制 改造方案（v1）

> **文档目的：** 评估云尚 AI 笔记助手未来两项架构升级的可行性、适用场景与改动范围：
> - **Part A（第一~七节）：MCP（Model Context Protocol）工具接入**
> - **Part B（第八~十节）：Reflection（反思/自我修正）机制**
>
> **结论先行（MCP）：** 架构上完全可行且改动收敛（工具层已与 Agent 逻辑解耦），**建议做**；但只建议把 MCP 用于**外部能力集成**（联网搜索、网页读取、浏览器操作、代码执行、第三方服务等），**内部业务工具（笔记/回顾/邮件）保持原生 LangChain 工具不变**。最小改动路径约 200~400 行代码，可在 1~2 天内完成试点。
>
> **结论先行（Reflection）：** 同样**建议做**，且与 MCP 天然互补（MCP 扩大工具面 → 工具出错概率上升 → 反思机制修复失败、提升正确率）。推荐"三层次递进"落地：L1 结果自检（Self-Refine）、L2 工具失败修复、L3 反思记忆（跨轮次学习）。MVP（L1）约 200~300 行代码、1~2 人日；**不改前端、不改数据库**。核心设计原则：**触发要克制**（有门槛、有轮次上限、有会话级限流），避免"为反思而反思"的延迟与成本失控。

---

## 一、当前工具链路回顾（改造的事实基础）

```
POST /api/v1/chat/query (app/routers/chat.py)
  │  QueryClassifier 判定 simple / complex
  │
  ├─ [simple]  → execute_agent()                       (app/ai_service/agent_runner.py)
  │               ├─ resolve_tool_groups()             # 关键词路由 → 工具组列表
  │               ├─ create_agent_tools(user_id, ...)  # 工厂：绑定用户上下文创建工具
  │               ├─ AgentFactory.create_agent()       # langchain create_agent → CompiledStateGraph
  │               └─ run_agent_stream()                # astream_events v2 → SSE 事件流
  │
  └─ [complex] → execute_plan_agent()                  (app/ai_service/plan_execute_agent.py)
                  ├─ Phase1 Plan    (轻量模型生成计划, 每步声明 tool)
                  ├─ Phase2 Execute (逐步 ReAct Agent, _resolve_step_tool_groups 反查工具组)
                  └─ Phase3 Synthesize
```

关键事实（代码勘测结论）：

| 模块 | 职责 | 与 MCP 的关系 |
|---|---|---|
| `app/ai_service/agent_tools.py` | 11 个原生工具（`@tool` 装饰器），工厂函数按 `groups` 按需加载 | **接入点 A：** 工具列表在此处汇合 |
| `app/ai_service/agent_runner.py` | 工具路由 + Agent 组装 + 流式调用链 | **接入点 B：** 合并 MCP 工具后统一交给 create_agent |
| `app/ai_service/plan_execute_agent.py` | Plan-and-Execute 三阶段引擎 | 无需改动（见 3.4 分析） |
| `app/ai_service/stream.py` | SSE 事件流（tool_start/tool_end 透传） | **无需改动**（MCP 工具调用自动透传） |
| `app/ai_service/agent_middleware.py` | 生命周期钩子（日志/监控） | **无需改动** |
| `config/agent.yaml` | tool_groups / tool_routing / 各类阈值 | 新增 `mcp_servers` 配置段 |
| `app/utils/config.py` | YAML 加载（模块级缓存） | 新增 1 个 getter |
| `main.py` `BackgroundInitManager` | 模型初始化（stage1_complete 事件） | **接入点 C：** MCP 客户端生命周期挂载 |
| `app/utils/factory.py` | 模型工厂（DashScope / Ollama 双提供商） | 无需改动 |

---

## 二、适合性分析

### 2.1 为什么"合适"

1. **工具层已经解耦，接入点收敛。** 所有工具都在 [agent_tools.py](../app/ai_service/agent_tools.py) 一个文件里、由工厂函数产出、通过 langchain `@tool` 与 `create_agent` 绑定。MCP 工具可以以"另一个工具来源"的身份并入同一列表，**Agent 循环、流式输出、中间件、循环检测全部复用，一行不改**。
2. **技术栈天然支持。** 项目基于 LangChain（实测 langchain 1.3.14）+ LangGraph，官方提供 `langchain-mcp-adapters` 适配器（`MultiServerMCPClient` / `load_mcp_adapters`），可将 MCP 工具直接转换为 LangChain `BaseTool`，与现有 `create_agent` 完全兼容。模型侧 qwen3-max 走 OpenAI 兼容端点，原生支持 function calling，无需换模型。
3. **配置驱动已有先例。** `agent.yaml` 的 `tool_groups` / `tool_routing` 已经证明"YAML 声明 → 运行时加载"的扩展模式可行，MCP server 清单天然适合放进同一份配置。
4. **扩展外部能力的边际成本极低。** 未来想加"联网搜索/网页抓取/读取知乎文章/浏览器操作"等能力，原生实现每个都要写请求封装、错误处理、上下文截断；MCP 生态有现成 server（官方 + 社区），接入成本变为"写 5 行 YAML"。

### 2.2 为什么"不要全盘 MCP 化"

| 内部工具 | 与 MCP 的冲突 |
|---|---|
| `create_note_tool` / `update_note_tool` 等 | 依赖**每用户会话绑定**（`db_session_factory` + `user_id` 闭包）。MCP 工具是共享的无状态工具，若要感知用户，需在每次调用时传入 user_id 参数或在 server 侧做会话管理，反而比原生闭包复杂 |
| `send_email` | 失败降级逻辑、PDF 渲染、审计日志都是定制逻辑，搬进通用 MCP server 无收益 |
| 内部 SQL 访问 | 直接注入服务层是私有契约，暴露为 MCP 工具等于给外部协议开内部接口，徒增安全面 |

**结论：双轨制。** 内部业务工具保持原生 LangChain 工具；MCP 只接"项目边界之外的能力"。这与项目现状（11 个工具全部面向内部服务）并不冲突——MCP 解决的是"工具不够用"而非"工具不好写"。

### 2.3 典型适用场景（云尚助手语境）

| 场景 | 推荐 MCP Server 示例 | 用户价值 |
|---|---|---|
| 联网搜索 / 资讯获取 | 官方 fetch + 社区 search server | 回答"帮我查一下最近一个月 AI 论文进展并整理成笔记" |
| 网页内容抓取 | fetch server（URL → Markdown） | "把这篇博客的内容提炼成笔记" |
| 浏览器自动化 | Playwright MCP server | 未来的"帮我打开知乎搜一下 XX" |
| 代码执行沙箱 | 官方 sandbox / jupyter server | 学习场景运行代码片段 |
| 文件系统/云盘（若未来有） | 自建 server | 笔记附件管理 |

> ⚠️ 注意：接入**第三方社区 server** 等于在服务器上执行不可信代码（MCP server 拥有宿主进程的权限），只能接入**官方发布或自审源码后自托管**的 server。详见第五节安全风险。

---

## 三、改造范围详解

### 3.1 改动全景图

```
新增文件：
  app/ai_service/mcp_manager.py      # MCP 客户端生命周期管理（连接/断开/重连/工具获取）
  config/mcp.yaml (可选)              # 或并入 agent.yaml 的 mcp_servers 段

修改文件（按改动量排序）：
  config/agent.yaml                  # 新增 mcp_servers 配置段（约 10 行）
  app/utils/config.py                # 新增 get_mcp_servers_config()（约 6 行）
  app/ai_service/agent_runner.py     # execute_agent 中合并 MCP 工具（约 10 行）
  main.py                            # BackgroundInitManager 挂载/关闭 MCP 客户端（约 20 行）
  requirements.txt                   # + langchain-mcp-adapters（1 行）
  prompts/main_prompt.txt            # 可选：提示词中声明 MCP 工具的存在（约 2 行）

无需改动：
  app/ai_service/stream.py           # SSE 事件流自动透传 MCP 工具调用
  app/ai_service/agent_middleware.py # 钩子按工具名触发，无类型依赖
  app/ai_service/plan_execute_agent.py # 见 3.4
  app/routers/chat.py / 前端           # 接口与 SSE 事件格式完全不变
```

### 3.2 核心接入点：工具合并

[agent_runner.py:114](../app/ai_service/agent_runner.py#L114) 的 `create_agent_tools()` 返回工具列表后，追加 MCP 工具即可：

```python
# agent_runner.py execute_agent() 内，第 2 步之后新增：
tools = create_agent_tools(...)

# ── MCP 工具合并（新增）──
from app.ai_service.mcp_manager import get_mcp_tools
mcp_tools = await get_mcp_tools()          # 从已连接的 MCP 客户端拉取工具
if mcp_tools:
    tools = list(tools) + mcp_tools        # 与原生工具合并
    logger.info(f"MCP 工具合并: {len(mcp_tools)} 个")
```

**关键设计点——按需加载的衔接：** 现有 `tool_groups` 机制只作用于原生工具。建议 MCP 工具**默认不参与 groups 过滤**（全量合并），原因：

1. MCP 工具数量通常少（1 个 server 几个工具），token 开销可控；
2. 工具组过滤用工具名做映射，MCP 工具名是 server 声明的，不该写死在 YAML 工具组里；
3. 若未来 MCP 工具数量膨胀，再在 `mcp_servers` 配置段加 `enabled_groups` 字段做组级开关（为后续预留，本期不做）。

### 3.3 MCP 客户端生命周期（最关键的新增模块）

MCP 客户端（stdio 子进程 / streamable-http 长连接）是**有状态的资源**，与现有"每次请求新建工具闭包"的模式不同，必须集中管理：

```python
# mcp_manager.py 设计草案
class MCPManager:
    """全局单例：管理所有已配置 MCP server 的会话生命周期"""

    def __init__(self):
        self._sessions = {}      # server_name → ClientSession
        self._tools = []         # 合并后的 MCP 工具缓存
        self.ready = asyncio.Event()

    async def start_all(self, configs): ...   # main.py stage1 中调用，逐 server 建立会话
    async def close_all(self):  ...           # 应用 shutdown 时调用
    async def get_tools(self):  ...           # 拉取/返回工具列表（连接失败则返回 [] 并降级）

    # 降级策略：任一 MCP server 连接失败 → 记日志 + 跳过该 server，
    # 绝不阻断 Agent 主流程（与 plan_execute 的降级哲学一致）
```

挂载点对应 [main.py:227](../main.py#L227) 的 `asyncio.create_task(init_manager.run())`：在 stage1 模型初始化完成后、设置 `stage1_complete` 事件**之前**并行拉起 MCP 会话；失败只降级不阻塞（见 3.5 风险表中的超时保护）。

### 3.4 Plan-and-Execute 兼容性（重点确认：无需改动）

已核实 [plan_execute_agent.py:155](../app/ai_service/plan_execute_agent.py#L155) 的 `_resolve_step_tool_groups()` 行为：

- Plan 阶段模型声明的 `step.tool` 若是 MCP 工具名 → 反向映射查不到 → 返回 `None` → `execute_agent` 走关键词路由 → `default_groups`（当前为全量加载）→ **MCP 工具仍然可用**；
- 若 plan 的步骤声明 `tool: none`（纯推理步骤）→ 直接 LLM 生成，不涉及工具，同样无影响。

即：**MCP 工具在复杂任务模式下自动可用，只是享受不到工具组精简优化**。这属于可接受的降级，无需为 MCP 改造 plan-execute 引擎。唯一可选优化（非本期）：在 `mcp_servers` 配置中增加工具名 → 组的映射，让 plan 反查也能命中，成本约 10 行。

### 3.5 两种实现路径对比

| 维度 | 路径 A：langchain-mcp-adapters（推荐） | 路径 B：原生 mcp SDK 手写适配 |
|---|---|---|
| 新增依赖 | `langchain-mcp-adapters`（内含 mcp SDK） | `mcp` 一个依赖 |
| 代码量 | 约 200~400 行（含生命周期管理） | 约 500~1000 行（含协议、工具转换、错误处理） |
| 兼容性 | 工具转换、流式、错误映射由官方维护 | 需要自己处理 AsyncIterator → BaseTool 的适配 |
| 生态 | 与 langchain 版本同步演进 | 自己维护适配层 |
| 风险 | 依赖 langchain-mcp-adapters 与项目 langchain 1.3.x 的版本匹配（需验证一次） | 无第三方依赖风险，但维护成本高 |

**推荐路径 A**，且试点时先验证版本兼容（见第六节 Phase 0）。

### 3.6 前端与接口：零改动

SSE 事件流中 `tool_start` / `tool_end` 按工具名透传，前端已能正确展示"工具调用中"状态；MCP 工具调用会以同样的事件格式到达，前端无感知。会话、标题生成、记忆压缩等链路均不感知工具实现来源。

---

## 四、改动量估算

| 任务 | 涉及文件 | 估算工作量 |
|---|---|---|
| Phase 0：版本兼容验证 + 1 个官方 fetch server 试点 | 环境验证 | 0.5~1 天 |
| Phase 1：MCP 配置 + 管理器 + 合并接入 | `mcp_manager.py`（新增）、`agent.yaml`、`config.py`、`agent_runner.py`、`main.py`、`requirements.txt` | 1~2 天 |
| Phase 2：接入 1~2 个真实场景 server（搜索/网页）+ 提示词说明 | `prompts/main_prompt.txt`、`agent.yaml` | 0.5~1 天 |
| Phase 3：加固（重连、超时、工具名冲突检测、token 预算、安全清单） | `mcp_manager.py`、`agent.yaml`、`token_budget.py`（微调） | 1~2 天 |
| 测试 | `tests/`（新增 mcp 集成测试） | 0.5~1 天 |

**总计：4~6 人日**。其中 Phase 0+1 的 MVP（能跑通"网页内容 → 总结成笔记"）约 1.5~3 人日。

---

## 五、风险清单与规避

| # | 风险 | 等级 | 规避措施 |
|---|---|---|---|
| 1 | **安全**：MCP server 在宿主进程内执行任意代码（stdio 子进程 / http 服务），第三方 server 不可信 | 🔴 高 | 只接入官方或自托管并审过源码的 server；配置文件白名单；生产环境禁止用户自定义 server（本期只做管理员配置） |
| 2 | **版本兼容**：`langchain-mcp-adapters` 与 langchain 1.3.x / langgraph 0.3.x 的版本矩阵 | 🟡 中 | Phase 0 先建最小 demo 验证；锁定依赖版本到 requirements.txt |
| 3 | **Windows 环境**：stdio transport 需要启动子进程（本项目开发机为 Win11），进程管理、路径、编码差异 | 🟡 中 | 优先使用 streamable-http / SSE transport 的 server；stdio server 需验证 Windows 下 `uvicorn` 子进程可正常 spawn 与回收 |
| 4 | **连接失败/断开**：MCP 会话失效导致 Agent 工具调用报错 | 🟡 中 | 全局降级策略（连接失败 → 该 server 跳过，Agent 主流程不受影响）；检测到会话失效时自动重连（指数退避） |
| 5 | **上下文 token 膨胀**：MCP 工具描述往往冗长（有的单工具数百 token），与现有 token_budget 预算冲突 | 🟡 中 | 工具数量克制（每个 server ≤ 5 个工具）；必要时在 `mcp_servers` 增加 `tools_include/exclude` 过滤；可复用工具组机制按需加载 |
| 6 | **工具名冲突**：MCP 工具名与原生工具（如 `search_notes_tool`）或不同 server 之间撞名 | 🟢 低 | 接入时统一加前缀（`mcp_<server>_<tool>`）；冲突时拒绝加载并告警 |
| 7 | **模型工具调用能力**：qwen3-max 走兼容端点已验证可用；Ollama 本地小模型（qwen3:latest）对多工具描述的处理可能退化 | 🟢 低 | 保持现状按 provider 区分；MCP 工具默认只在 DashScope 提供商下启用，Ollama 下可通过配置关闭 |
| 8 | **调试成本**：MCP 调用链跨进程/跨网络，问题定位比原生工具难 | 🟢 低 | 复用现有 middleware 钩子记录工具名/耗时；为 mcp_manager 增加独立日志标签 `[mcp]` |

---

## 六、分阶段实施计划

### Phase 0：可行性验证（0.5~1 天，先做！）
- [ ] 验证 `langchain-mcp-adapters` 与当前 langchain 1.3.14 兼容（跑官方 fetch server 最小 demo）
- [ ] 验证目标 server 在 Windows + 现有 Python 环境的可运行性
- [ ] 产出验证结论后决定路径 A/B

### Phase 1：MVP 接入（1~2 天）
- [ ] `requirements.txt` 增加依赖
- [ ] `agent.yaml` 新增 `mcp_servers` 段；`config.py` 新增 getter
- [ ] 新建 `mcp_manager.py`（生命周期 + 降级 + 工具拉取）
- [ ] `agent_runner.py` 合并 MCP 工具；`main.py` 挂载 start/close
- [ ] 联调：SSE 前端正常展示 MCP 工具调用

### Phase 2：真实场景（0.5~1 天）
- [ ] 接入 1~2 个高价值 server（如 fetch + search）
- [ ] `main_prompt.txt` / `plan_generation.txt` 补充一句工具说明（可选）
- [ ] 验证 Plan-and-Execute 复杂任务中 MCP 工具的可用性

### Phase 3：加固与安全（1~2 天）
- [ ] 自动重连（指数退避）、会话健康检查
- [ ] 工具名冲突检测与前缀规范化
- [ ] token 预算：MCP 工具描述计入 `token_budget` 预留估算
- [ ] 生产安全清单：server 白名单、禁用用户自定义 server、日志脱敏

---

## 七、结论

1. **适合**：项目"大脑-手脚分离"的既有架构使 MCP 接入天然低侵入，官方适配器与 langchain 技术栈无缝衔接，前端与流式链路零改动。
2. **改动范围可控**：MVP 约 3~4 个文件新增/微改 + 1 个新模块，4~6 人日可完成全量落地；所有改动集中在后端，接口契约不变。
3. **推荐路径**：`langchain-mcp-adapters` + 配置驱动的 server 白名单；内部业务工具保持原生实现（双轨制）。
4. **先做 Phase 0**：版本兼容与 Windows 环境验证是唯一实质性阻塞风险，1 天内可闭环，验证通过后再投入 Phase 1。

---

# Part B：Reflection（反思/自我修正）机制改造方案

## 八、现状分析与反思的定位

### 8.1 现有架构中"不可反思"的现状（代码勘测结论）

| 现状 | 位置 | 后果 |
|---|---|---|
| 工具调用失败 → 错误事件直接抛给前端，Agent 循环终止 | [stream.py:109-116](../app/ai_service/stream.py#L109-L116)（`asyncio.TimeoutError` / 异常 → `error` 事件后 `return`） | 用户只看到"生成失败"，模型没有机会基于错误信息修正 |
| 循环检测 `max_consecutive_tool_calls: 6` 直接强杀 | [stream.py:80-88](../app/ai_service/stream.py#L80-L88) | 防死循环正确，但也杜绝了"失败后换策略重试" |
| Plan-Execute 步骤失败 → 记录失败结果继续往下走 | [plan_execute_agent.py:267-270](../app/ai_service/plan_execute_agent.py#L267-L270)（`step.result = 失败`，Synthesize 阶段如实呈现） | 复杂任务容错靠"如实说明"，不靠"修复" |
| 回答生成完就结束，没有质量校验环节 | [agent_runner.py:141-148](../app/ai_service/agent_runner.py#L141-L148)（`run_agent_stream` 出 `stream_done` 即结束） | 生成错误/遗漏工具结果时，只能靠用户发现 |
| 工具错误信息不沉淀 | middleware 仅记录工具名与耗时 | 同类错误反复发生，模型从不"吸取教训" |

### 8.2 三种层次的反思（从轻到重，可独立上线）

```
L1 结果自检（Self-Refine）       生成 → 批判 → 修正（单轮内闭环，本次回答即修正）
L2 工具失败修复（Self-Repair）   工具出错 → 注入错误原因 → 定向重试 1 次
L3 反思记忆（Reflexion）         失败/修复经验 → 持久化 → 未来会话注入"教训"提示词
```

- **L1 是 MVP**：改动最小、效果立竿见影（复杂任务回答质量、邮件/笔记操作正确性）；
- **L2 收益最大**：项目现状是"工具一错就全盘失败"，修复后复杂任务完成率明显提升；同时与 MCP 协同——外部工具（联网搜索等）出错率天然高于内部工具，MCP 接入后 L2 价值进一步放大；
- **L3 改动涉及持久化**：建议与 [长期记忆提取与检索式历史设计方案.md](长期记忆提取与检索式历史设计方案.md) 合并实施，避免两套记忆体系重复设计（该文档的 `user_memory` 表可扩展 `reflection` 记忆类型，提取管线复用其"对话 → 结构化记忆"模式）。

### 8.3 与 MCP 方案的协同关系

```
MCP（Part A）：扩大 Agent 的工具面（外部能力）
Reflection（Part B）：保证"用对工具、用对结果"
┌─ 协同点 1：MCP 工具失败 → L2 修复轮（错误信息回灌模型，定向重试）
┌─ 协同点 2：MCP 工具描述冗长易误用 → L1 自检兜底（检查是否用了正确工具/参数）
┌─ 协同点 3：外部工具结果不可信 → L1 批判要求"标注来源、注明不确定性"
```

## 九、Reflection 改造方案

### 9.1 设计总览

```
                    ┌────────────────────────────────────────────┐
                    │      ReflectionController（新增）            │
                    │      app/ai_service/reflection.py           │
                    │  · critiqu 模型选择（复用轻量/主模型）        │
                    │  · 触发判定（门槛 + 会话级限流）              │
                    │  · 修正循环（max_refine_rounds，硬上限 2）    │
                    └──────────────┬─────────────────────────────┘
                                   │
    ┌──────────────────────────────┼──────────────────────────────┐
    │ ReAct 路径（simple）          │ Plan-Execute 路径（complex）  │
    │ chat.py → execute_agent      │ chat.py → execute_plan_agent │
    │                              │                              │
    │ ① stream_done 后（可选）       │ ① 步骤级：_execute_step 失败  │
    │    L1 自检 → 可能 refine      │    时注入错误原因重试 1 次(L2) │
    │ ② error 事件时（必检）         │ ② 最终级：_synthesize 输出后  │
    │    L2 错误回灌 → 重试 1 次     │    L1 自检 → 可能 refine      │
    └──────────────────────────────┴──────────────────────────────┘
                                   │
                    ┌──────────────┴─────────────┐
                    │ L3（Phase 3）：反思记忆      │
                    │ DB 持久化 → 下次会话注入     │
                    └────────────────────────────┘
```

### 9.2 文件级改动清单

**新增：**

| 文件 | 内容 | 估算 |
|---|---|---|
| `app/ai_service/reflection.py` | `ReflectionController`（触发判定、critique、refine 循环、限流） | 150~250 行 |
| `prompts/reflection_critique.txt` | 批判 prompt（质量检查维度 + "只指出实质问题"约束），沿用 prompt_loader 加载模式 | ~30 行 |
| `prompts/reflection_refine.txt`（可选） | 修正 prompt（如与 critique 合并则不需要） | ~20 行 |
| `tests/test_reflection.py` | 单元 + 集成测试 | ~100 行 |

**修改：**

| 文件 | 改动 | 估算 |
|---|---|---|
| `config/agent.yaml` | 新增 `reflection` 配置段（触发门槛、轮次、超时、限流、模型选择） | ~20 行 |
| `app/utils/config.py` | 新增 `get_reflection_config()`（照抄现有 getter 模式） | ~6 行 |
| `app/ai_service/agent_runner.py` | `execute_agent` 包一层：`stream_done` 后按触发条件调 L1；`error` 事件时调 L2 | ~25 行 |
| `app/ai_service/plan_execute_agent.py` | ① `_execute_step` 失败分支增加 1 次修复轮；② `_synthesize` 输出后接 L1 | ~40 行 |
| `app/routers/chat.py` | SSE 透传 `reflection` 类型事件（thinking 样式） | ~10 行 |
| `app/services/token_budget.py` | `TokenBudget` 增加 `reflection_reserve` 字段（默认 2000），从历史配额扣减 | ~5 行 |
| `prompts/main_prompt.txt` | 规则 5 补充"失败重试最多 1 次"约束（与修复轮衔接） | ~2 行 |

**无需改动：** `stream.py`（事件类型由调用方透传）、`agent_middleware.py`、`agent.py`、`factory.py`、前端（`reflection` 事件按 `thinking` 样式渲染即可，不渲染也无感）。

### 9.3 关键设计决策

#### 决策 1：批判模型复用现有轻量模型（不新增模型实例）

`init_manager` 已持有 `classifier_model`（qwen3-flash）与 `plan_model`（qwen3-flash），**复用即可**，无需新增模型实例与初始化成本：

```yaml
# agent.yaml reflection 段
reflection:
  critic_model: "light"        # "light"（复用 qwen3-flash，默认，快且省）| "main"（主模型，质量优先）
  critic_timeout: 15            # 批判调用超时（秒）
  max_refine_rounds: 1          # 修正轮次上限（硬上限 2，代码层兜底）
```

建议：ReAct 简单回答用 `light`；Plan-Execute 复杂任务默认也用 `light` 批判、`main` 修正（质量敏感路径成本已高，不差这一次调用）。

#### 决策 2：触发门槛（克制原则，避免每句都反思）

```yaml
reflection:
  trigger:
    on_tool_error: true        # 工具出错 → 必检（L2）
    on_stream_error: true      # Agent 整体出错 → 必检（L2 回灌重试）
    min_answer_chars: 800      # 回答 ≥ 800 字才 L1 自检（短回答不检）
    complex_task: true         # Plan-Execute 复杂任务始终 L1 自检
    rate_limit_per_session: 5  # 每会话最多 5 次反思（防成本失控，存 session metadata）
```

效果：绝大多数简单问答（"现在几点"、"谢谢"）零额外调用；只有长回答、复杂任务、出错场景才触发。

#### 决策 3：修正循环的收敛控制

- `max_refine_rounds` 默认 1，硬上限 2（`min(rounds, 2)` 兜底）；
- 每轮修正的输入 = 草稿 + 批判意见；若批判判定"无需修正"（`needs_refine: false`）立即结束；
- 修正阶段**禁止调用工具**（纯文本修正）——消除两个风险：① 与邮件发送的"用户确认"流程冲突（不会产生未经确认的发送）；② 与循环检测 `max_consecutive_tool_calls` 的耦合。

#### 决策 4：L2 修复轮的安全边界

- 只允许重试**已失败的那个工具**，且注入完整错误信息回灌模型："上次调用 `{tool}` 失败（`{error}`），请修正参数或更换策略，最多再尝试 1 次"；
- 例外：`send_email` 失败**不自动重试**（避免重复发送），提示用户重试；
- 修复轮次数计入 `main_prompt.txt` 的工具调用总数约束（规则 5 相应微调），避免"重试 → 再失败 → 再重试"放大。

#### 决策 5：SSE 流式体验（草案 → 修正的分段输出）

L1 修正发生在草稿已流出之后，前端呈现为两段。为避免割裂感：

```
草稿流（response 事件）→ reflection 事件（stage=checking，前端显示"正在检查回答质量..."）
→ 如判定需修正：reflection 事件（stage=refining）→ 修正版继续以 response 事件输出 → stream_done
```

- 前端改动**可选**（把 `reflection` 事件当 `thinking` 渲染即可，一行配置）；
- 若完全不动前端，用户感知为"回答分两段到达"，可接受（MVP 默认如此）。

#### 决策 6：与现有机制的关系（均已核实无冲突）

| 现有机制 | 冲突点 | 规避 |
|---|---|---|
| `max_consecutive_tool_calls: 6` 循环检测（stream.py） | 修复轮可能新增工具调用 | 修复轮在 run_agent_stream **外层**独立调用，不触发连续计数；且 L1 修正禁工具 |
| `LLM_STREAM_TIMEOUT=60`（ReAct） / `total_timeout: 300`（Plan-Execute） | 反思增加耗时可能挤占超时预算 | critic 超时 15s 独立预算；refine 计入总超时内，超时即跳过反思（降级为直接输出草稿） |
| `TokenBudget`（32768 窗口） | 反思上下文额外消耗 | 新增 `reflection_reserve: 2000` 从历史配额扣减（决策见 9.2 token_budget.py 改动） |
| 邮件确认流程（main_prompt 第六节） | refine 可能重复发送 | 修正阶段禁工具 + `send_email` 失败不自动重试 |
| 记忆压缩（memory_compressor） | L3 反思记忆的注入通道 | 复用"摘要注入 system_prompt"模式：查询最近 N 条教训注入，而非改压缩器 |

### 9.4 改动量估算

| 阶段 | 内容 | 工作量 |
|---|---|---|
| Phase 1（L1 自检 MVP） | reflection.py + critique prompt + 配置 + ReAct/Plan-Execute 接入 + SSE 事件 | 1~2 人日 |
| Phase 2（L2 工具失败修复） | 错误回灌重试 + `send_email` 例外 + 步骤级修复轮 | 0.5~1 人日 |
| Phase 3（L3 反思记忆） | DB 表 + 提取/注入管线（与长期记忆方案合并实施省 ~30%） | 1~2 人日 |
| 测试与回归集 | 20 个典型问题基准集，量化"改进率/回退率" | 0.5~1 人日 |

**总计：3~5 人日**；其中 L1+L2（不含持久化）约 2~3 人日，且**不触碰数据库与前端**。

### 9.5 风险清单与规避

| # | 风险 | 等级 | 规避 |
|---|---|---|---|
| 1 | **过度修正**：批判模型挑刺但修正版更差（质量回退） | 🟡 中 | 批判 prompt 约束"只指出实质性问题，禁止为修改而修改"；轮次上限 2；可选按 1% 流量采样对比（`enable_sampling` 开关） |
| 2 | **延迟/成本**：每轮反思 = 1 次额外 LLM 调用 | 🟡 中 | 触发门槛（9.3 决策 2）+ 会话级限流 5 次 + 批判用轻量模型 |
| 3 | **与写操作冲突**（邮件、笔记更新） | 🔴 高 | L1 修正禁工具；`send_email` 失败不自动重试（9.3 决策 4） |
| 4 | **流式体验割裂**：草稿与修正版分段 | 🟢 低 | `reflection` 事件按 thinking 渲染；MVP 可接受 |
| 5 | **批判模型幻觉**：轻量模型批判质量不稳 | 🟡 中 | `critic_model: "main"` 兜底开关；基准集回归验证 |
| 6 | **超时放大**：反思挤占现有总超时预算 | 🟢 低 | critic 独立 15s 超时；超时跳过反思直接输出草稿 |
| 7 | **记忆污染（L3）**：错误教训被固化反复注入 | 🟡 中 | 教训只记录"失败 + 已生效修复"；设最大条数（如 10 条/会话）与去重；与长期记忆方案共用的审查机制 |

## 十、综合结论与实施优先级

| 方案 | 建议 | 优先级 | 前提条件 |
|---|---|---|---|
| MCP 工具接入 | 做（双轨制：外部能力 MCP、内部工具原生） | 中 | 先跑 Phase 0 版本兼容验证（0.5 天） |
| Reflection L1 自检 | 做 | **高**（成本最低、收益确定性最高，且为 L2/L3 打地基） | 无，可直接实施 |
| Reflection L2 修复 | 做 | 中（MCP 接入后价值翻倍） | L1 落地后 |
| Reflection L3 记忆 | 做（合并进长期记忆方案） | 低 | 长期记忆方案立项时 |

**推荐路线：** 先独立落地 Reflection L1+L2（2~3 人日，无依赖、无数据库、无前端改动）；MCP Phase 0 验证通过后并行投入；两者在"工具失败修复"处交汇（MCP 工具出错 → L2 定向重试），形成完整闭环。
