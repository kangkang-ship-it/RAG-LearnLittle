# AI Agent 实习能力短板分析与补足计划

> 目标:进入公司实习做 AI Agent 开发前,对照行业 Agent 能力图谱,盘点自身能力现状,明确短板并制定可执行的补足计划。
>
> 文档基于本项目的实践现状编写(RagLearnCode:ReAct/Plan-Execute 混合路由、工具引擎、记忆体系、RAG、流式输出等)。

---

## 1. 能力现状盘点(已有实践)

### 1.1 已具备的能力

| 能力域 | 具体实践 | 项目落点 |
|---|---|---|
| 工具工程 | 工具注册表、按需加载(groups)、防幻觉系统提示词、Plan-Execute 直指定工具组 | `app/ai_service/agent_tools.py` |
| 混合路由 | ReAct / Plan-Execute 双模式、查询复杂度分类(L1 规则 + L2 LLM 判断) | `app/ai_service/plan_execute_agent.py` |
| 记忆体系 | 对话记忆压缩、滑动窗口、长期记忆提取与检索 | `app/services/memory_compressor.py` |
| RAG | 语义搜索、路由阈值、embedding 模型切换 | `app/rag/rag_service.py` |
| 流式输出 | SSE 流式、中间件钩子、中间步骤透出 | `app/ai_service/stream.py` |
| 工程化 | token 预算、超时保护、循环检测、数据库连接池、生产风险分析 | 全项目 |

### 1.2 结论

**"能跑通 demo"的能力已经具备,并且超过大部分实习生水平。** 但距离"能上生产、能对业务负责"还有明显差距,差距集中在下面五个方向。

---

## 2. 核心短板分析(按重要程度排序)

### 2.1 MCP 协议(Model Context Protocol)⭐ 最重要

**现状**:工具硬编码在 `agent_tools.py` 的工厂函数里,通过闭包注入服务。工具接入方式是"改代码 + 重启服务"。

**行业现状**(2026 年):MCP 已是行业标配标准协议,工具通过 MCP server 动态接入,支持热插拔、跨项目复用、第三方工具生态(浏览器、数据库、Slack 等)。

**核心概念**:
- 协议流程:`initialize` → `tools/list` → `tools/call` 三种请求
- 角色划分:**MCP Server**(提供工具) / **MCP Client**(宿主应用,如 Claude Code / 自研 agent)
- 传输方式:stdio(本地进程)、Streamable HTTP(远程)
- 工具生态:官方 registry + 社区 server 海量可复用

**补足方案**:
1. 通读 MCP spec(官方文档:https://modelcontextprotocol.io)
2. 用 `fastmcp`(或 `mcp` python sdk)写一个最小 MCP server,把本项目中的 `what_time_is_now`、`search_notes_tool` 暴露出去,约 20~50 行代码
3. 用一个现成 client(如 Claude Code / `mcp` cli)连接自己写的 server,跑通 tools/list 和 tools/call
4. **进阶**:把本项目的工具引擎改造成"本地注册 + MCP 扩展"双通道,即保留硬编码工具的向后兼容,同时支持从 MCP server 动态拉取工具

**面试价值**:会写 MCP server = 入职当天能干活。

---

### 2.2 Agent 评测体系(Eval)⭐ 最容易被忽略

**现状**:项目没有任何评测手段。修改提示词、工具参数后,无法量化"变好还是变坏",全凭人工对话感受。

**行业现状**:生产级 agent 开发必须有评测集 + 回归对比,用于:
- 验证提示词改动没有回归
- 量化工具选择准确率
- 比较不同模型/不同路由策略的优劣

**核心概念**:
- 评测集(Test Set):N 条用例,每条包含「用户输入 → 期望行为」(期望的工具调用序列 / 期望的最终答案)
- 指标:工具选择正确率、任务完成率、首轮延迟、token 消耗、成本
- 回归对比:同一评测集跑改动前后,对比指标差异
- 工具:LangSmith、Langfuse、DeepEval、自研 eval runner

**补足方案**:
1. 建 30~50 条用例的评测集(覆盖:简单问答、搜索笔记、创建笔记、更新笔记、跨工具多步任务、恶意/边界输入)
2. 写一个 eval runner 脚本:批量跑评测集 → 记录每次的工具调用序列 → 与期望序列比对 → 输出准确率报告
3. 把评测接入"每次改动提示词后跑一遍"的流程,形成回归意识
4. **进阶**:接入 Langfuse 做 trace + eval 一体化

**面试价值**:"工程师"和"调参玩家"的分水岭。能回答"agent 准确率多少、怎么证明你的改动有效"的候选人极少。

---

### 2.3 可观测性与生产排障(Trace)

**现状**:有日志体系(console + 文件滚动),但没有全链路 trace。agent 出问题时,难以定位是"哪一步、哪个工具、哪段上下文"出了问题。

**行业现状**:生产环境排障依赖 trace——每个请求分配一个 Trace ID,串联:
- 每一步 LLM 的输入/输出
- 每次工具调用的参数与返回
- token 消耗、延迟、重试次数
- 路由决策(走了 ReAct 还是 Plan-Execute、为什么)

**工具**:LangSmith、Langfuse、OpenTelemetry(OTel)

**补足方案**:
1. 在现有中间件钩子的基础上(已有流式中间件),增加 trace 中间件:每个请求生成 Trace ID,把「LLM 请求/响应、工具调用、路由决策、耗时、token」事件序列化写入 Redis 或 DB
2. 提供查询接口:按 Trace ID 回放一次完整 agent 执行
3. **进阶**:接入 Langfuse 开源版,对比自研与现成方案的取舍

**面试价值**:做过 trace 的人能讲清楚"生产环境怎么排障",这是实习转正的关键能力之一。

---

### 2.4 多 Agent 协作与编排

**现状**:单 agent 架构(ReAct/Plan-Execute 是同一 agent 内部的两条路径),没有 agent 间的协作。

**行业现状**:复杂任务普遍用多 agent 分工:
- Planner / Executor / Critic / Reviewer 角色拆分
- 反思循环(Reflection):执行 → 检查 → 纠错 → 重执行
- Agent 间消息传递与结果仲裁

**补足方案**(在现有项目上最小改造):
1. 增加 **Critic 反思循环**:agent 执行完后,用一个轻量模型检查输出质量(是否答非所问、工具是否用错),不合格则携带反馈重跑一次
2. 统计反思触发率与修正成功率,验证该机制的实际收益
3. **进阶**:读 AutoGen / CrewAI / LangGraph 的多 agent 设计,理解角色编排与共享上下文管理

**面试价值**:"agent 自我纠错"是公司最常问的能力,有实际实现 + 收益数据非常加分。

---

### 2.5 结构化输出的可靠性

**现状**:Plan 模型使用结构化输出(schema 约束),但只有一次机会,没有失败重试与兜底。

**行业现状**:生产环境要求:
- 解析失败自动重试(通常最多 2~3 次)
- pydantic schema 校验,非法输出直接拦截
- 兜底策略(重试耗尽后回退到默认计划或 ReAct 模式)
- 统计一次成功率,用于模型选型与提示词优化

**补足方案**:
1. 给 Plan 输出加 pydantic 校验 + 失败重试(最多 2 次)
2. 重试耗尽后回退到 ReAct 模式(项目已有该模式,天然支持兜底)
3. 统计一次成功率,对比不同模型(如 qwen3-flash vs 主模型)的结构化输出稳定性

---

## 3. 优先级与时间规划建议

| 优先级 | 事项 | 预计工作量 | 对应短板 |
|---|---|---|---|
| P0 | MCP 最小 server + 接入 client | 1~2 天 | 2.1 |
| P0 | 评测集(30~50 条)+ eval runner | 2~3 天 | 2.2 |
| P1 | trace 中间件 + 按 Trace ID 回放 | 1~2 天 | 2.3 |
| P1 | 结构化输出重试 + 兜底 | 0.5~1 天 | 2.5 |
| P2 | Critic 反思循环 + 收益统计 | 2~3 天 | 2.4 |

建议顺序:**P0 两项优先**——MCP 是行业入场券,评测体系是证明能力的基础设施。

---

## 4. 面试/实习话术要点

1. **多讲"为什么"**:本项目 docs 中已有 ReAct vs Plan-Execute 的对比分析、路由决策依据、生产风险分析——大多数人只知道"用 LangChain 跑通",你能讲清楚架构权衡,这是稀缺优势
2. **用数据说话**:补上 eval 后,任何改动都能报出"准确率从 X% 到 Y%"的量化结果
3. **展示架构视角**:工具按需加载、向后兼容、安全保底(空结果回退全量工具)等设计,体现生产思维
4. **提及学习路径**:MCP、Langfuse/OTel、LangGraph,展示持续跟进行业标准的能力

---

## 5. 学习资源清单

| 方向 | 资源 |
|---|---|
| MCP | https://modelcontextprotocol.io (官方 spec)、`fastmcp` / `mcp` Python SDK |
| Agent 模式 | 《Building Agents with LLMs》课件(DeepLearning.AI)、LangGraph 文档 |
| 评测 | LangSmith、Langfuse、DeepEval 官方文档 |
| 可观测性 | OpenTelemetry 规范、Langfuse 自托管部署 |
| 多 Agent | AutoGen、CrewAI、LangGraph 官方教程 |
| 记忆 | 本项目已有实践(压缩/滑动窗口/长期记忆),可对比 MemGPT 论文思路 |
