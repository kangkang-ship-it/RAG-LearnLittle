# AI Agent 架构评估与演进建议

> 版本：v1.1 ｜ 日期：2026-08-04 ｜ 状态：评审完成 + P0/P1 已实施（已知遗留项：流式调用 token 为 null，见 P0 已知限制）

## 1. 评审结论

对 RagLearnCode 的 Agent 链路（FastAPI + LangChain + DashScope）进行架构评审，结论：

**模型路由层符合企业级实践（多模型分级路由是标准做法），但整体 Agent 是"企业级核心元素 + 个人项目级工程外壳"的混合体。**

- ✅ 核心：模型工厂抽象、多模型分级路由、Token 预算、记忆压缩、流式协议、降级链——已达标
- ❌ 工程外壳：可观测性（无 trace/指标）、评测体系（无 golden 用例）、编排分层（自研胶水）——已通过 P0/P1 补齐前两项

## 2. 模型路由现状（2026-08-04 修复后）

| 场景 | 执行模型 | 实测延迟 | 说明 |
|---|---|---|---|
| 普通文本 | `chat_model`（qwen3.8-max，thinking 关） | ~0.7s | 主对话模型 |
| 文本 + 深度思考 | `chat_model_thinking`（qwen3.8-max，thinking 开） | ~2-7s | 思考模式 |
| 文件输入 | `vision_model`（qwen3.7-max-2026-06-08） | ~1.6-3s | 设计 §6.1 独立视觉模型 |
| 文件 + 深度思考 | `vision_model`（思考自动关闭） | ~1.6-3s | 多模态+思考实测必超时 |
| 查询分类 | `classifier_model`（qwen3.7-flash-2026-07-15） | L1 规则优先 | 规则命中不调 LLM |
| 复杂任务计划 | `plan_model`（qwen3.7-flash-2026-07-15） | ~2s | 关闭思考实测 2.4s；开启思考实测 30s+ 超时；失败降级 ReAct |
| 向量检索 | Embedding（qwen3.7-text-embedding） | — | ChromaDB 向量化，不进 Agent 链路 |
| 会话标题/记忆摘要/RAG | `chat_model`（文本任务恒用主模型） | — | 不受附件影响 |

关键设计：`chat_query` 中 **`chat_model`（文本任务）与 `agent_model`（执行链路）双实例分工**——
标题/RAG/摘要永远走主模型，执行链路按模态/思考开关路由。

## 3. 已符合企业级实践的部分

| 维度 | 实现 | 评价 |
|---|---|---|
| 模型抽象 | `factory.py` 模型工厂 + provider 一键切换（dashscope/ollama）+ 每模型独立降级 | ✅ 标准做法 |
| 模型分级 | 轻量（分类/计划）+ 重量（执行）+ 视觉（按模态） | ✅ |
| Token 预算 | `TokenBudget` 配额分配 + 多模态图片估算 + 历史裁剪 | ✅ 超出多数同类项目 |
| 记忆体系 | 滑动窗口 + 里程碑摘要 + Redis 热缓存 | ✅ |
| 提示词外部化 | `prompts/` 目录 | ✅ |
| 降级链 | Plan 模型不可用/计划生成失败→ReAct、视觉模型不可用→主模型、分类器 LLM 失败→simple、记忆压缩失败→简单截断、PDF 生成失败→MD 附件 | ✅ 完整 |
| 流式协议 | SSE + thinking/tool/plan 事件（thinking 由路由层 yield，plan 由 Plan 执行器 yield；Agent 流本身仅产出 response/tool_start/tool_end/error/stream_done 五类） | ✅ |
| 工具集 | 11 个工具 / 5 组（base、note_read、note_write、review、email），关键词路由 + default_groups 加载；Plan 步骤经 override_groups 直指定 | ✅ |
| 附件管线 | 上传→magic bytes→归属校验→会话绑定→多模态处理（`multimodal_processor.py`：图片压缩/视频抽帧）→base64→历史回放（`max_history_images` 截断） | ✅ |
| 安全（附件） | magic bytes + 归属校验 + 鉴权预览 + 孤儿清理 | ✅ |

## 4. 差距与演进建议（按优先级）

### P0 ✅ 已实施：模型调用 Trace（app/core/model_trace.py）

**问题**：只有 logger 文本日志，排查"哪个模型调用慢"靠 grep 日志拼时间线（实测 60s 超时定位耗时数小时）。

**方案**：LangChain `BaseCallbackHandler` 在 factory 层统一挂载（8 处 Chat 模型构造：4×ChatOpenAI + 4×ChatOllama；2 处 Embedding 构造不支持 callbacks 参数，不在 Trace 范围），一次覆盖所有 LLM 调用点：
- 每次 LLM 调用输出结构化 JSON 行（`event=model_trace`）
- 字段：request_id / user_id / session_id / stage / model / prompt_tokens / completion_tokens / total_tokens / latency_ms / success / error
- 请求上下文用 `contextvars` 传递（chat_query 设置，后台任务独立设置）；stage 覆盖 classify/agent/plan_execute/title/summary

**输出示例**：
```json
{"event": "model_trace", "request_id": "0525918a2d64", "user_id": "ea475f050e1a4b2c", "session_id": "c2f81571-1d6e-4a2f-9b3c", "stage": "agent", "model": "qwen3.8-max", "prompt_tokens": null, "completion_tokens": null, "total_tokens": null, "latency_ms": 1141, "success": true, "error": null}

> 注：user_id/session_id 全量输出（P2-2 起，DB 落库按用户/会话聚合，截断会导致前缀碰撞）
```

**已知限制**：
- 流式调用 token 为 null（DashScope 兼容模式流式响应不返回 usage；已设 `stream_usage=True` 仍无）——非流式调用（分类/计划）有完整 token
- 模型名提取依赖 LangChain 序列化格式（`serialized.kwargs.model`），框架版本升级后可能提取失败——已加 run name 兜底（P2-5），极端情况仍会回退 "unknown"
- trace 服务转发已实现（P2-5）：`TRACE_SINK=log,db,langfuse` + `LANGFUSE_*` 配置，经 `_emit` → LangfuseSink 批量转发

### P1 ✅ 已实施：Golden 评测体系（tests/eval/）

**问题**：模型/提示词改动质量退化无法量化，全靠手测。

**方案**：
- `golden_cases.json`：23 条用例，覆盖 6 类（general 10 / thinking 2 / complex 2 / note 4 / multimodal 4 / knowledge 1），字段含 expected_keywords + match 规则 + 附件生成 spec
- `eval_runner.py`：登录 → 前置创建 EVAL_ 测试笔记 → 逐条执行（SSE 收集回复）→ 关键词判定 → 汇总报告（总通过率/分类通过率/平均延迟/失败明细）→ 自动清理（会话/笔记/附件）
- 报告输出：控制台表格 + `tests/eval/results/report_*.json`

**首轮结果**：执行 22 条（kb-001 依赖知识库文档，首轮未纳入分母），通过率 90.9%（20/22），平均延迟 5.0s；2 个失败均为用例设计问题（gen-008 题目歧义、mm-004 要求模型报精确像素），用例修正后 22/22 通过（结果文件见 `tests/eval/results/report_20260804_*.json`）。

**用法**：
```bash
.venv/Scripts/python.exe -X utf8 tests/eval/eval_runner.py
```

### P2 ⏳ 建议（按下表实施顺序，原编号保留便于引用）

| 顺序 | 项 | 说明 | 收益 |
|---|---|---|---|
| ① | P2-4 | 路由策略配置化补全 | 分类规则已配置化（agent.yaml `classifier` 段）；剩余硬编码迁入配置：`_rule_classify` 的 `tool_keywords` 列表、复杂判定分支 | 可调优 |
| ② | P2-2 | 成本账单 | 每次调用实际 token/费用落库（model_trace 数据源已有），按会话/用户汇总 | 成本控制 |
| ③ | P2-3 | 安全护栏 | 前置安全审计（Prompt 注入测试、工具参数校验覆盖度）；`send_email` 已有"先与用户确认邮箱"约束（main_prompt.txt + 工具 docstring），仍缺调用频率限制与审计日志 | 安全 |
| ④ | P2-5 | trace 服务化 | model_trace → Langfuse/OpenTelemetry（依赖 ② 的数据基础） | 可观测性升级 |
| ⑤ | P2-1 | 编排层声明式改造 | chat_query 的 if/else 路由改为 langgraph StateGraph（节点：classify→route→react/plan→fallback），可视化 + 可单步调试。迁移复杂度中高：generate_stream 闭包耦合 SSE 与 rag_context/compressed_messages 等非局部变量，建议先抽取路由函数再逐步迁移 | 可维护性 |
| ⑥ | P2-6 | 工具注册动态化 | `all_tools` 硬编码字典 → 动态注册机制，为 MCP 工具接入预留（MCP 可行性另见 docs/ 下 MCP 专项方案） | 可扩展性 |

### 技术债务（评审中识别，暂未排期）

1. **按需加载在默认配置下失效**：`agent.yaml` `default_groups` 全量包含 5 个工具组（注释称 email "不进 default_groups 以节省上下文窗口"，但配置实际已包含，自相矛盾）；关键词路由对已含组跳过追加（agent_runner.py），仅 Plan-Execute 的 `override_groups` 能真正缩减工具集
2. **函数默认值与配置不一致**：`agent.py` `max_iterations=5` 与 `agent.yaml` `max_iterations: 10`（运行时以 yaml 为准）；`plan_execute` 超时项代码默认值（plan 10s / step 30s / synthesize 30s）均低于 yaml 配置（30s / 90s / 60s）
3. **超时边界叠加**：`max_steps(5) × step_timeout(90s) + synthesize_timeout(60s) = 510s` > `total_timeout(300s)`，总超时触发时可能强制中断正在执行的步骤（asyncio.timeout 兜底）
4. **`_resolve_step_tool_groups` 每个步骤重建工具名→组名反向映射**（plan_execute_agent.py），多步骤任务存在冗余开销

## 5. 附录：实施过程中的关键教训

1. **多模态 + thinking 组合超时**（架构教训）：qwen3.8-max thinking + 图片输入首 token >60s（`LLM_STREAM_TIMEOUT`），必须按模态路由（附件→视觉模型）而非叠加思考开关
2. **重构变量引用**（架构教训）：`chat_model` 被标题/RAG/摘要复用，重构为双实例时需 grep 全部引用
3. **Windows 开发环境注意事项**（通用开发）：bash 内联中文 curl body 解析失败（编码），测试脚本用文件 body 或 httpx；Git Bash 的 `/tmp` 与 Windows 原生程序（python/curl）路径不互通；`py_compile` 与 Edit 源文件 mtime 同秒时 Python 误加载旧字节码，改代码后重启前删除 `__pycache__`
