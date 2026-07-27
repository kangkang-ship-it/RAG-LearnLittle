# ReAct 与 Plan-and-Execute 混合路由方案

## 概述

在当前 Agent 对话系统中增加 **查询复杂度路由**：简单问题使用现有 ReAct 模式（快速响应），复杂问题使用新增的 Plan-and-Execute 模式（先规划再执行）。通过规则 + LLM 两级分类器自动判断查询复杂度，前端展示执行计划进度条，Plan 阶段使用更快/更便宜的模型以控制延迟和成本。

---

## 一、现状回顾

### 1.1 当前调用链路

```
用户消息 → chat.py (router)
  ├── RAG检索 + 记忆压缩 (asyncio.gather 并行)
  ├── 构建 system_prompt (注入 RAG 上下文)
  └── execute_agent() ──→ AgentFactory.create_agent() ──→ run_agent_stream()
        (ReAct 模式)         (langchain.agents.create_agent)   (astream_events v2)
              │
              └── SSE 流式响应 → 前端 AIChat.tsx
```

### 1.2 当前 ReAct Agent 特征

- 基于 `langchain.agents.create_agent()`，每次请求创建全新 `CompiledStateGraph` 实例
- 8 个异步工具：时间查询、用户信息、笔记搜索、笔记统计、今日回顾、标记回顾、创建笔记、关联推荐
- 最大迭代次数：10（`config/agent.yaml` → `agent.max_iterations`）
- 流式输出：`astream_events(version="v2")` → 逐 token SSE 推送
- **无显式规划阶段**：Agent 在 ReAct 循环中边思考边行动

### 1.3 核心文件清单

| 文件 | 职责 | 改动影响 |
|------|------|----------|
| `app/routers/chat.py` | 路由入口，编排 RAG + 记忆压缩 + Agent 调用 | **需修改** |
| `app/ai_service/agent_runner.py` | Agent 执行器，封装创建→输入→流式输出 | **需修改** |
| `app/ai_service/agent.py` | AgentFactory，基于 `create_agent` | 不变 |
| `app/ai_service/agent_tools.py` | 8 个工具定义 | 不变（共用） |
| `app/ai_service/agent_middleware.py` | 生命周期钩子 | 不变（共用） |
| `app/ai_service/stream.py` | `run_agent_stream()` 流式输出 | 不变（共用） |
| `app/schemas/chat.py` | 请求/响应 Schema | **需修改** |
| `config/agent.yaml` | Agent 配置 | **需修改** |
| `config/prompt.yaml` | 提示词路径映射 | **需修改** |
| `app/utils/factory.py` | 模型工厂 | **需修改** |
| `app/utils/config.py` | 配置加载工具 | **需修改** |
| `main.py` | 应用入口 + 后台初始化 | **需修改** |
| `front/src/pages/AIChat.tsx` | 前端对话页面 | **需修改** |
| `front/src/hooks/useSSE.ts` | SSE Hook | **需修改** |
| `front/src/types/api.ts` | 前端类型定义 | **需修改** |

---

## 二、整体架构设计

### 2.1 改动后调用链路

```
用户消息 → chat.py (router)
  │
  ├── RAG检索 + 记忆压缩 (asyncio.gather 并行，不变)
  │
  ├── 查询复杂度分类 query_classifier.classify()
  │     ├── L1: 规则预判 (关键词 + 模式匹配，<1ms)
  │     │     ├── 确定简单 → 走 ReAct
  │     │     ├── 确定复杂 → 走 Plan-Execute
  │     │     └── 不确定   → 进入 L2
  │     └── L2: LLM 精判 (轻量 prompt，~200ms)
  │           └── 返回 classification + confidence
  │
  ├── [简单] execute_agent() ──→ ReAct Agent ──→ SSE 流式输出
  │      (现有逻辑完全不变)
  │
  └── [复杂] execute_plan_agent() ──→ Plan-and-Execute Agent ──→ SSE 流式输出
         (新增)                           │
                                          ├── Phase 1: Plan  (用轻量模型生成执行计划)
                                          ├── Phase 2: Execute (逐步执行，ReAct 每步)
                                          └── Phase 3: Synthesize (汇总结果，生成最终回答)
```

### 2.2 架构全景图

```
┌──────────────────────────────────────────────────────────────────────┐
│                         POST /api/v1/chat/query                       │
│                         (app/routers/chat.py)                         │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
                  ┌──────────▼──────────┐
                  │  RAG 检索 + 记忆压缩  │  ← 不变
                  │  (asyncio.gather)    │
                  └──────────┬──────────┘
                             │
                  ┌──────────▼──────────┐
                  │  查询复杂度分类器     │  ← 新增: query_classifier.py
                  │                     │
                  │  L1: 规则预判        │
                  │  ├─ 简单 → ReAct    │
                  │  ├─ 复杂 → Plan-Ex  │
                  │  └─ 不确定 → L2     │
                  │                     │
                  │  L2: LLM 精判        │
                  │  └─ 返回分类结果     │
                  └──────┬──────┬───────┘
                         │      │
                    simple    complex
                         │      │
          ┌──────────────▼──┐   ┌─▼──────────────────────────────┐
          │  execute_agent() │   │  execute_plan_agent()           │
          │  (现有 ReAct)    │   │  (新增 Plan-and-Execute)        │
          │                  │   │                                │
          │  AgentFactory    │   │  Phase 1: Plan                 │
          │  .create_agent() │   │    轻量模型生成步骤列表 (JSON)   │
          │                  │   │    → SSE: plan_start + steps   │
          │  run_agent_      │   │                                │
          │  stream()        │   │  Phase 2: Execute              │
          │                  │   │    逐步执行 + ReAct per step   │
          │  8 个工具         │   │    → SSE: plan_step_start/end │
          │                  │   │                                │
          │  max_iter=10     │   │  Phase 3: Synthesize           │
          │                  │   │    汇总结果 → 最终回答          │
          │                  │   │    → SSE: plan_complete        │
          └──────┬───────────┘   └─┬──────────────────────────────┘
                 │                 │
                 └────────┬────────┘
                          │
                ┌─────────▼──────────┐
                │  SSE 流式响应       │
                │  (StreamingResponse)│
                │                    │
                │  事件类型:          │
                │  - thinking        │
                │  - plan_start (新) │
                │  - plan_step (新)  │
                │  - response        │
                │  - done            │
                │  - error           │
                └─────────┬──────────┘
                          │
                ┌─────────▼──────────┐
                │  前端 AIChat.tsx    │
                │                    │
                │  展示:              │
                │  - 思考过程         │
                │  - 执行计划进度条(新)│
                │  - Markdown 回答    │
                └────────────────────┘
```

---

## 三、查询复杂度分类器设计

### 3.1 两级分类架构

```
输入: user_message (str)
  │
  ▼
┌─────────────────────────────────────────────┐
│ L1: 规则预判 (Rule-based Pre-classifier)     │
│                                              │
│ 返回: "simple" | "complex" | "uncertain"     │
│ 耗时: <1ms                                   │
│ 成本: 零                                      │
└──────────────┬──────────────────────────────┘
               │
        ┌──────┼──────┐
        │      │      │
     simple  complex  uncertain
        │      │      │
        ▼      ▼      ▼
      直接    直接    ┌──────────────────────────┐
      路由    路由    │ L2: LLM 精判              │
                      │                           │
                      │ 轻量 prompt (~100 tokens)  │
                      │ 结构化输出:                │
                      │   { complexity, reason }   │
                      │                           │
                      │ 返回: "simple" | "complex" │
                      │ 耗时: ~200-500ms           │
                      │ 成本: ~100-200 tokens      │
                      └──────────────────────────┘
```

### 3.2 L1 规则预判逻辑

**判定为"复杂"的关键词/模式（任一命中即判定）：**

| 类别 | 模式 | 示例 |
|------|------|------|
| 多步操作词 | `分析.*总结`、`对比.*整理`、`研究.*归纳`、`先.*然后.*再` | "先搜索我的Python笔记，然后总结重点，再创建一个学习计划" |
| 规划意图词 | `计划`、`规划`、`步骤`、`流程`、`方案`、`策略`、`教程` | "帮我制定一个学习FastAPI的计划" |
| 综合分析词 | `综合分析`、`全面了解`、`深入探讨`、`系统梳理` | "系统梳理我最近一周的笔记内容" |
| 多目标并列 | 同时包含 3+ 个不同领域的工具需求 | "查一下我的笔记统计，然后搜索关于Docker的内容，再帮我回顾今天的笔记，最后创建一个关于微服务的笔记" |
| 长文本 | 消息长度 > 200 字符 且包含 2+ 个问号 | — |
| 条件分支 | `如果.*否则`、`要么.*要么`、`根据.*决定` | "如果我有Python笔记就总结一下，否则推荐相关学习资源" |

**判定为"简单"的模式（任一命中即判定）：**

| 类别 | 模式 | 示例 |
|------|------|------|
| 单步工具 | 仅匹配 1 个工具意图 | "帮我搜索Python笔记" |
| 闲聊/问候 | `你好`、`谢谢`、`再见`、`今天.*怎么样` | "你好！" |
| 简单问答 | 消息长度 < 50 字符且不含工具意图词 | "什么是RAG？" |
| 单步操作 | `创建.*笔记`、`搜索.*`、`现在.*时间` | "现在几点了？" |
| 明确单选 | `帮我.*一下`（单个动词） | "帮我查一下今天的回顾" |

**以上均不匹配 → 返回 `"uncertain"`，进入 L2 LLM 精判。**

### 3.3 L2 LLM 精判

#### 3.3.1 提示词模板

新增文件：`prompts/classify_complexity.txt`

```
你是一个查询复杂度分析器。判断以下用户消息属于"简单"还是"复杂"。

简单消息的特征：
- 可以在一步内完成（单一工具调用或直接回答）
- 不涉及多个子任务
- 不需要先收集信息再综合处理

复杂消息的特征：
- 需要多步骤完成（先搜索、再分析、最后汇总等）
- 包含多个子任务或目标
- 需要制定计划分步执行

用户消息：{user_message}

请用 JSON 格式回答：
{{"complexity": "simple" 或 "complex", "reason": "简短判断理由(10字以内)"}}
```

#### 3.3.2 模型选择

L2 精判使用与主对话**相同提供商**的轻量模型，通过环境变量配置：

| 提供商 | 主模型 (ReAct) | 分类模型 (L2) |
|--------|---------------|---------------|
| DashScope | `qwen3-max` | `qwen3-flash`（默认） |
| Ollama | `qwen3:latest` | `qwen3:0.6b`（默认） |

通过环境变量 `CLASSIFIER_MODEL` 覆盖默认值。

#### 3.3.3 结构化输出解析

```python
# 分类结果
@dataclass
class ClassificationResult:
    complexity: Literal["simple", "complex"]
    source: Literal["rule", "llm"]  # 分类来源
    reason: str                      # 判断理由
    confidence: float                # 置信度 (规则=1.0, LLM=0.8)
```

### 3.4 分类器实现文件

**新增文件：** `app/ai_service/query_classifier.py`

```python
# 核心类和方法
class QueryClassifier:
    def __init__(self, llm_model=None):
        self.rules = [...]        # 规则列表
        self.llm_model = llm_model  # L2 精判模型（可选）

    async def classify(self, user_message: str) -> ClassificationResult:
        # 1. L1 规则预判
        result = self._rule_classify(user_message)
        if result.complexity != "uncertain":
            return result

        # 2. L2 LLM 精判
        if self.llm_model:
            return await self._llm_classify(user_message)

        # 3. 无 LLM 可用时默认简单
        return ClassificationResult("simple", "rule", "default", 0.5)

    def _rule_classify(self, msg: str) -> ClassificationResult:
        ...

    async def _llm_classify(self, msg: str) -> ClassificationResult:
        ...
```

---

## 四、Plan-and-Execute Agent 设计

### 4.1 三阶段状态机

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐
│ Phase 1  │────→│  Phase 2     │────→│  Phase 3     │
│  Plan    │     │  Execute     │     │  Synthesize  │
│          │     │              │     │              │
│ 生成执行  │     │ 逐步执行每   │     │ 汇总所有步骤  │
│ 计划步骤  │     │ 个计划步骤   │     │ 结果，生成    │
│          │     │ (ReAct per   │     │ 最终用户回答  │
│          │     │  step)       │     │              │
└──────────┘     └──────────────┘     └──────────────┘
  轻量模型          主模型 (ReAct)       主模型
  ~500ms           每步 ~1-3s           ~500ms
```

### 4.2 Phase 1: Plan（规划阶段）

**目标：** 将复杂用户消息分解为 2-5 个有序的执行步骤。

**模型：** 轻量模型（与分类器 L2 共用，通过环境变量 `PLAN_MODEL` 配置）。

**提示词：** 新增文件 `prompts/plan_generation.txt`

```
你是一个任务规划器。将用户的复杂请求分解为有序的执行步骤。

可用工具：
1. search_notes - 语义搜索用户笔记
2. get_note_stats - 获取笔记分类统计
3. get_today_reviews - 获取今日待回顾笔记
4. create_note - 创建新笔记
5. get_related_notes - 获取关联笔记推荐
6. 直接回答 - 不需要工具的问题直接回答

用户请求：{user_message}

请生成一个 JSON 格式的执行计划：
{
  "goal": "用一句话概括目标",
  "steps": [
    {
      "step": 1,
      "action": "步骤描述（简短）",
      "tool": "可能需要用到的工具名或'none'",
      "depends_on": []  // 依赖的前置步骤编号列表
    },
    ...
  ]
}

规则：
- 步骤数控制在 2-5 个
- 每个步骤明确指定是否需要工具
- 如果步骤之间没有依赖关系，可以并行执行
- 最后一步始终是综合前面的结果给出最终回答
```

**SSE 事件：**
```json
{"type": "plan_start", "goal": "...", "total_steps": 3}
{"type": "plan_step", "step": 1, "action": "搜索Python相关笔记", "status": "pending"}
{"type": "plan_step", "step": 2, "action": "总结笔记内容", "status": "pending"}
{"type": "plan_step", "step": 3, "action": "生成学习建议", "status": "pending"}
```

### 4.3 Phase 2: Execute（执行阶段）

**目标：** 逐步执行每个计划步骤（有依赖关系的串行，无依赖的并行）。

**模型：** 主模型（与 ReAct Agent 相同）。

**每步执行方式：**
- 如果需要工具调用 → 创建该步骤专用的 ReAct Agent（工具集完整，但 prompt 限定在当前步骤）
- 如果不需要工具 → 直接 LLM 生成

**SSE 事件：**
```json
{"type": "plan_step_start", "step": 1, "action": "搜索Python相关笔记"}
  ... (该步骤内的 ReAct 流式输出，类型仍为 "response")
{"type": "plan_step_end", "step": 1, "result": "找到3篇Python笔记"}

{"type": "plan_step_start", "step": 2, "action": "总结笔记内容"}
  ...
{"type": "plan_step_end", "step": 2, "result": "总结完成"}
```

**并行优化：** 如果步骤之间没有 `depends_on` 依赖关系，使用 `asyncio.gather` 并行执行。

### 4.4 Phase 3: Synthesize（综合阶段）

**目标：** 汇总所有步骤的执行结果，生成最终的用户回答。

**模型：** 主模型。

**提示词策略：** 将各步骤结果作为上下文注入，让模型生成连贯的自然语言回答。

**SSE 事件：**
```json
{"type": "plan_synthesize", "content": "正在汇总结果..."}
{"type": "response", "content": "基于你的Python笔记..."}  // 逐 token 输出
{"type": "plan_complete", "total_steps": 3, "completed_steps": 3}
```

### 4.5 Plan-and-Execute Agent 实现文件

**新增文件：** `app/ai_service/plan_execute_agent.py`

```python
# 核心函数
async def execute_plan_agent(
    chat_model,          # 主模型（用于 Execute + Synthesize）
    plan_model,          # 轻量模型（用于 Plan）
    user_id: str,
    user_message: str,
    system_prompt: str,
    compressed_messages: list,
    db_session_factory,
    timeout: int = 120,  # Plan-Execute 超时比 ReAct 长
) -> AsyncGenerator[dict, None]:
    """
    Plan-and-Execute Agent 执行器

    Yields:
        SSE 事件字典（包含 plan_start/plan_step/plan_step_start/
        plan_step_end/response/plan_complete 等类型）
    """
    # Phase 1: Plan
    plan = await _generate_plan(plan_model, user_message, system_prompt)
    yield {"type": "plan_start", "goal": plan.goal, "total_steps": len(plan.steps)}
    for step in plan.steps:
        yield {"type": "plan_step", "step": step.step, "action": step.action, "status": "pending"}

    # Phase 2: Execute（拓扑排序后执行，无依赖步骤并行）
    results = {}
    for batch in _topological_batches(plan.steps):
        # batch 内的步骤无依赖关系，可并行
        async for event in _execute_batch(batch, chat_model, ...):
            yield event

    # Phase 3: Synthesize
    async for event in _synthesize(chat_model, plan, results, ...):
        yield event
```

---

## 五、轻量模型管理

### 5.1 模型工厂扩展

**修改文件：** `app/utils/factory.py`

新增两个工厂函数：

```python
def create_classifier_model():
    """
    创建分类器专用 Chat 模型（轻量、快速）
    环境变量 CLASSIFIER_MODEL 指定模型名，默认根据 provider 选择轻量版
    """
    ...

def create_plan_model():
    """
    创建 Plan 阶段专用 Chat 模型（轻量、支持结构化输出）
    环境变量 PLAN_MODEL 指定模型名，默认复用分类器模型
    """
    ...
```

默认模型选择策略：

| 提供商 | 主模型 | 分类模型 | Plan 模型 |
|--------|--------|----------|-----------|
| DashScope | `qwen3-max` | `qwen3-flash` | `qwen3-flash` |
| Ollama | `qwen3:latest` | `qwen3:0.6b` | `qwen3:0.6b` |

> **注：** 如果环境变量未指定轻量模型且提供商不支持独立配置（如 Ollama 只有一个模型），分类和 Plan 模型退化为使用主模型。

### 5.2 后台初始化扩展

**修改文件：** `main.py` → `BackgroundInitManager`

在阶段 1 中增加分类模型和 Plan 模型的初始化：

```python
async def _init_models(self):
    """初始化 AI 模型（Chat + Embedding + Classifier + Plan）"""
    self.chat_model = create_chat_model()
    self.embed_model = create_embed_model()
    self.classifier_model = create_classifier_model()  # 新增
    self.plan_model = create_plan_model()              # 新增
```

---

## 六、路由层改动

### 6.1 chat.py 改动点

**修改文件：** `app/routers/chat.py`

改动集中在 `generate_stream()` 内部，RAG 和记忆压缩逻辑完全不变：

```python
# ===== 改动前 =====
async def generate_stream():
    # ... thinking 事件 ...
    async for event in execute_agent(
        chat_model=chat_model,
        user_id=user_id,
        user_message=data.message,
        system_prompt=system_prompt,
        compressed_messages=compressed_messages,
        db_session_factory=async_session_factory,
        timeout=LLM_STREAM_TIMEOUT,
    ):
        # ... 事件处理 ...

# ===== 改动后 =====
async def generate_stream():
    # ... thinking 事件 ...

    # 查询复杂度分类
    classifier = QueryClassifier(llm_model=init_manager.classifier_model)
    classification = await classifier.classify(data.message)
    logger.info(f"查询分类: complexity={classification.complexity}, "
                f"source={classification.source}, reason={classification.reason}")

    if classification.complexity == "simple":
        # 简单问题：走现有 ReAct Agent（逻辑完全不变）
        async for event in execute_agent(
            chat_model=chat_model,
            user_id=user_id,
            user_message=data.message,
            system_prompt=system_prompt,
            compressed_messages=compressed_messages,
            db_session_factory=async_session_factory,
            timeout=LLM_STREAM_TIMEOUT,
        ):
            # ... 事件处理（不变）...
    else:
        # 复杂问题：走 Plan-and-Execute Agent
        async for event in execute_plan_agent(
            chat_model=chat_model,
            plan_model=init_manager.plan_model,
            user_id=user_id,
            user_message=data.message,
            system_prompt=system_prompt,
            compressed_messages=compressed_messages,
            db_session_factory=async_session_factory,
            timeout=LLM_STREAM_TIMEOUT * 2,  # 复杂任务给双倍超时
        ):
            # ... 处理新增的 plan_start/plan_step/plan_step_start/
            #     plan_step_end/plan_complete 事件类型 ...
```

### 6.2 SSE 事件类型汇总

| 事件类型 | 来源模式 | 用途 | 新增/现有 |
|----------|----------|------|-----------|
| `thinking` | 共用 | RAG + 思考过程 | 现有 |
| `response` | 共用 | 逐 token 回答内容 | 现有 |
| `done` | 共用 | 对话完成 | 现有 |
| `error` | 共用 | 错误 | 现有 |
| `plan_start` | Plan-Ex | 计划开始（含 goal + total_steps） | **新增** |
| `plan_step` | Plan-Ex | 单个步骤声明（含 status: pending） | **新增** |
| `plan_step_start` | Plan-Ex | 步骤开始执行 | **新增** |
| `plan_step_end` | Plan-Ex | 步骤执行完成（含 result 摘要） | **新增** |
| `plan_synthesize` | Plan-Ex | 进入综合阶段 | **新增** |
| `plan_complete` | Plan-Ex | 计划全部完成 | **新增** |

---

## 七、前端改动

### 7.1 类型定义

**修改文件：** `front/src/types/api.ts`

```typescript
// 聊天 SSE 消息类型扩展
export interface ChatSSEMessage {
  type: 'thinking' | 'response' | 'done' | 'error'
       | 'plan_start' | 'plan_step' | 'plan_step_start'
       | 'plan_step_end' | 'plan_synthesize' | 'plan_complete';  // 新增
  stage?: string;
  content?: string;
  details?: Record<string, unknown>;
  session_id?: string;
  // 新增字段
  goal?: string;
  total_steps?: number;
  completed_steps?: number;
  step?: number;
  action?: string;
  status?: 'pending' | 'running' | 'completed' | 'failed';
  result?: string;
}
```

### 7.2 SSE Hook

**修改文件：** `front/src/hooks/useSSE.ts`

在 `switch (data.type)` 中新增 case 分支，将 plan 事件透传给回调：

```typescript
// 新增回调类型
interface SSECallbacks {
  // ... 现有回调 ...
  onPlanStart?: (goal: string, totalSteps: number) => void;
  onPlanStep?: (step: number, action: string, status: string) => void;
  onPlanStepStart?: (step: number, action: string) => void;
  onPlanStepEnd?: (step: number, result: string) => void;
  onPlanSynthesize?: () => void;
  onPlanComplete?: (totalSteps: number, completedSteps: number) => void;
}
```

### 7.3 聊天页面

**修改文件：** `front/src/pages/AIChat.tsx`

新增 **执行计划进度条组件**，在 Plan-Execute 模式下展示：

```
┌─────────────────────────────────────────────┐
│  📋 执行计划：分析Python学习进度              │
│                                             │
│  ✅ 步骤1：搜索Python相关笔记                 │
│  🔄 步骤2：总结笔记重点内容                   │  ← 当前正在执行
│  ⏳ 步骤3：生成学习建议                       │
│                                             │
│  ████████████░░░░░░░░  2/3 步骤完成           │
└─────────────────────────────────────────────┘
```

实现方式：
- 在 AI 消息气泡上方渲染一个独立的计划进度卡片（`PlanProgressCard` 组件）
- 监听 `plan_start` → 初始化进度条
- 监听 `plan_step` → 渲染步骤列表（全部 pending）
- 监听 `plan_step_start` → 标记步骤为 running
- 监听 `plan_step_end` → 标记步骤为 completed
- 监听 `plan_complete` → 进度条填满，折叠/收起

---

## 八、配置改动

### 8.1 agent.yaml

**修改文件：** `config/agent.yaml`

```yaml
# Agent 配置
agent:
  max_iterations: 10
  stream_chunk_size: 15
  max_history_rounds: 20

# Plan-and-Execute 配置（新增）
plan_execute:
  # Plan 阶段
  max_steps: 5                    # 计划最多步骤数
  plan_timeout: 10                # Plan 生成超时（秒）
  step_timeout: 30                # 单步执行超时（秒）
  synthesize_timeout: 30          # 综合阶段超时（秒）
  total_timeout: 120              # 总超时（秒）
  # 并行执行
  enable_parallel: true           # 是否并行执行无依赖步骤
  max_parallel_steps: 3           # 最大并行步骤数

# 查询分类配置（新增）
classifier:
  # L1 规则层
  rule_complex_keywords:          # 复杂意图关键词
    - "分析.*总结"
    - "对比.*整理"
    - "研究.*归纳"
    - "先.*然后.*再"
    - "计划"
    - "规划"
    - "步骤"
    - "方案"
    - "策略"
    - "综合分析"
    - "系统梳理"
  rule_simple_patterns:           # 简单意图模式
    - "^你好"
    - "^谢谢"
    - "^再见"
    - "^现在.*时间"
  rule_complex_min_length: 200    # 长消息判定阈值（字符数）
  # L2 LLM 层
  llm_enabled: true               # 是否启用 LLM 精判
  llm_confidence: 0.8             # LLM 判定置信度

# RAG 配置 (不变)
rag:
  enable_summarize: true
  truncate_max_chars: 800

# Token 预算配置 (不变)
token_budget:
  ...

# 记忆压缩配置 (不变)
memory_compression:
  ...
```

### 8.2 prompt.yaml

**修改文件：** `config/prompt.yaml`

```yaml
prompts:
  main: "prompts/main_prompt.txt"
  # ... 现有映射不变 ...
  # 新增
  classify_complexity: "prompts/classify_complexity.txt"
  plan_generation: "prompts/plan_generation.txt"
  plan_synthesize: "prompts/plan_synthesize.txt"
```

### 8.3 环境变量

`.env` 中新增的可选配置：

```bash
# === 分类器和 Plan 模型（可选，默认使用轻量版）===
# CLASSIFIER_MODEL=qwen3-flash       # L2 分类模型
# PLAN_MODEL=qwen3-flash             # Plan 生成模型
# CLASSIFIER_LLM_ENABLED=true        # 是否启用 L2 LLM 精判
```

---

## 九、提示词模板

### 9.1 新增文件清单

| 文件 | 用途 |
|------|------|
| `prompts/classify_complexity.txt` | L2 LLM 查询复杂度分类 |
| `prompts/plan_generation.txt` | Plan 阶段：生成执行计划 |
| `prompts/plan_synthesize.txt` | Synthesize 阶段：汇总结果生成回答 |

### 9.2 classify_complexity.txt

```
你是一个查询复杂度分析器。判断以下用户消息属于"简单"还是"复杂"。

简单消息的特征：
- 可以在一步内完成（单一工具调用或直接回答）
- 不涉及多个子任务
- 不需要先收集信息再综合处理
- 示例："现在几点了？"、"帮我搜索Python笔记"、"什么是Docker？"

复杂消息的特征：
- 需要多步骤完成（先搜索、再分析、最后汇总等）
- 包含多个子任务或目标
- 需要制定计划分步执行
- 示例："分析我最近的笔记，总结重点，然后制定学习计划"

用户消息：{user_message}

请用 JSON 格式回答（不要包含其他内容）：
{{"complexity": "simple" 或 "complex", "reason": "简短判断理由(10字以内)"}}
```

### 9.3 plan_generation.txt

```
你是一个任务规划器。将用户的复杂请求分解为有序的执行步骤。

当前时间：{current_time}

可用工具：
1. search_notes - 语义搜索用户笔记
2. get_note_stats - 获取笔记分类统计
3. get_today_reviews - 获取今日待回顾笔记
4. mark_reviewed - 标记回顾完成
5. create_note - 创建新笔记（支持Markdown）
6. get_related_notes - 获取关联笔记推荐
7. get_user_info - 获取当前用户信息
8. 直接回答 - 不需要工具的问题直接回答（标注 tool: "none"）

用户请求：{user_message}

请用 JSON 格式生成执行计划（不要包含其他内容）：
{{"goal": "用一句话概括目标","steps": [{{"step": 1, "action": "步骤描述", "tool": "工具名或none", "depends_on": []}}]}}

规则：
- 步骤数控制在 2-5 个
- depends_on 填写前置步骤的编号列表（如 [1, 2]），无依赖则填 []
- 无依赖的步骤会被并行执行，有依赖的按序执行
- 最后一步始终是综合所有结果生成最终回答（tool: "none"）
```

### 9.4 plan_synthesize.txt

```
你是一个智能笔记助手。根据以下执行计划的结果，生成最终回答。

原始用户问题：{user_message}

执行计划：{plan_summary}

各步骤结果：
{step_results}

请基于以上结果，生成一个完整、连贯、有帮助的回答。
- 引用具体的数据和来源
- 保持简洁，不啰嗦
- 如果某个步骤没有结果，如实说明
```

---

## 十、数据结构与类型定义

### 10.1 Python 数据类（新增）

```python
# app/ai_service/query_classifier.py

from dataclasses import dataclass, field
from typing import Literal

@dataclass
class ClassificationResult:
    complexity: Literal["simple", "complex"]
    source: Literal["rule", "llm"]
    reason: str
    confidence: float = 1.0


# app/ai_service/plan_execute_agent.py

@dataclass
class PlanStep:
    step: int
    action: str
    tool: str  # 工具名或 "none"
    depends_on: list[int] = field(default_factory=list)
    result: str = ""  # 执行后填充


@dataclass
class ExecutionPlan:
    goal: str
    steps: list[PlanStep]
```

### 10.2 SSE 事件 Schema（扩展）

```python
# app/schemas/chat.py 中新增/扩展

class PlanStartEvent(TypedDict):
    type: Literal["plan_start"]
    goal: str
    total_steps: int
    mode: Literal["plan_execute"]

class PlanStepEvent(TypedDict):
    type: Literal["plan_step"]
    step: int
    action: str
    status: Literal["pending", "running", "completed"]

class PlanStepStartEvent(TypedDict):
    type: Literal["plan_step_start"]
    step: int
    action: str

class PlanStepEndEvent(TypedDict):
    type: Literal["plan_step_end"]
    step: int
    result: str

class PlanCompleteEvent(TypedDict):
    type: Literal["plan_complete"]
    total_steps: int
    completed_steps: int
    session_id: str
    sources: list[dict]  # RAG 来源（与 done 事件一致）
```

---

## 十一、文件清单与改动总结

### 11.1 新增文件（6 个）

| # | 文件路径 | 说明 | 预估行数 |
|---|----------|------|----------|
| 1 | `app/ai_service/query_classifier.py` | 查询复杂度分类器（L1 规则 + L2 LLM） | ~120 行 |
| 2 | `app/ai_service/plan_execute_agent.py` | Plan-and-Execute Agent（三阶段） | ~250 行 |
| 3 | `prompts/classify_complexity.txt` | L2 复杂度分类提示词 | ~20 行 |
| 4 | `prompts/plan_generation.txt` | Plan 生成提示词 | ~25 行 |
| 5 | `prompts/plan_synthesize.txt` | 综合阶段提示词 | ~15 行 |
| 6 | `front/src/components/chat/PlanProgressCard.tsx` | 执行计划进度卡片组件 | ~80 行 |

### 11.2 修改文件（10 个）

| # | 文件路径 | 改动说明 | 预估改动量 |
|---|----------|----------|------------|
| 1 | `app/routers/chat.py` | 增加分类+路由分支逻辑 | +50 行 |
| 2 | `app/ai_service/agent_runner.py` | 微调，保持 ReAct 路径不变 | ±10 行 |
| 3 | `app/schemas/chat.py` | 新增 Plan SSE 事件 Schema | +40 行 |
| 4 | `app/utils/factory.py` | 新增 `create_classifier_model()` / `create_plan_model()` | +50 行 |
| 5 | `app/utils/config.py` | 新增 `get_plan_execute_config()` / `get_classifier_config()` | +20 行 |
| 6 | `main.py` | 后台初始化增加 classifier_model + plan_model | +20 行 |
| 7 | `config/agent.yaml` | 新增 `plan_execute` + `classifier` 配置段 | +35 行 |
| 8 | `config/prompt.yaml` | 新增 3 个提示词映射 | +4 行 |
| 9 | `front/src/pages/AIChat.tsx` | 集成 PlanProgressCard + 新事件处理 | +50 行 |
| 10 | `front/src/hooks/useSSE.ts` | 新增 plan 事件回调 | +40 行 |
| 11 | `front/src/types/api.ts` | 扩展 ChatSSEMessage 类型 | +10 行 |

### 11.3 不变文件

| 文件 | 原因 |
|------|------|
| `app/ai_service/agent.py` | AgentFactory 仅用于 ReAct，Plan-Execute 单独构建 |
| `app/ai_service/agent_tools.py` | 8 个工具两种模式完全共用 |
| `app/ai_service/agent_middleware.py` | 中间件钩子两种模式共用 |
| `app/ai_service/stream.py` | `run_agent_stream()` 在 Plan-Execute 的 Execute 阶段复用 |
| `app/services/chat_service.py` | 会话管理不感知 Agent 模式 |
| `app/services/database_session_manager.py` | 存储层完全不感知 |
| `app/services/memory_compressor.py` | 记忆压缩不感知 Agent 模式 |
| `app/services/token_budget.py` | Token 预算不感知 Agent 模式 |
| `app/rag/*` | RAG 管线不感知 Agent 模式 |
| `front/src/api/chat.ts` | SSE 通信协议不变 |

### 11.4 工作量估算

| 类别 | 行数 | 复杂度 |
|------|------|--------|
| 新增 Python | ~420 行 | ⭐⭐⭐ |
| 修改 Python | ~190 行 | ⭐⭐ |
| 新增提示词 | ~60 行 | ⭐ |
| 新增前端 TSX | ~80 行 | ⭐⭐ |
| 修改前端 TS/TSX | ~100 行 | ⭐⭐ |
| YAML 配置 | ~40 行 | ⭐ |
| **合计** | **~890 行** | — |

---

## 十二、测试策略

### 12.1 单元测试

| 测试对象 | 测试内容 |
|----------|----------|
| `QueryClassifier._rule_classify()` | 覆盖所有规则模式，验证正确分类 |
| `QueryClassifier.classify()` | 验证 L1→L2 流转逻辑 |
| `ExecutionPlan` 拓扑排序 | 验证依赖解析和并行批次划分正确性 |

### 12.2 集成测试

| 场景 | 预期路由 | 验证点 |
|------|----------|--------|
| "你好" | ReAct | 分类为 simple，走 ReAct |
| "帮我搜索Python笔记" | ReAct | 分类为 simple，走 ReAct |
| "分析我的Python笔记，总结重点，然后制定学习计划" | Plan-Ex | 分类为 complex，走 Plan-Ex，前端展示进度条 |
| "先搜索Docker笔记，再对比K8s的优劣，最后创建一个对比总结笔记" | Plan-Ex | 分类为 complex，多步骤顺序执行 |

### 12.3 性能验证

| 指标 | 目标 |
|------|------|
| L1 规则分类延迟 | <1ms |
| L2 LLM 分类延迟 | <500ms |
| Plan 生成延迟 | <1s |
| Plan-Execute 总延迟（3 步） | <15s |
| ReAct 路径延迟（与现有相比） | 无退化（仅增加 L1 规则判断 <1ms） |

---

## 十三、风险与应急方案

| 风险 | 影响 | 应急方案 |
|------|------|----------|
| L2 分类模型不可用 | 不确定的消息默认走 ReAct | `classify()` 中捕获异常，fallback 到 "simple" |
| Plan 模型生成格式错误 | Plan-Execute 无法启动 | JSON 解析失败时降级为 ReAct |
| Plan 步骤执行超时 | 单步卡死 | `step_timeout` 保护 + 跳过失败步骤继续后续 |
| 轻量模型效果差 | 分类不准、Plan 质量低 | 环境变量切换回主模型 `CLASSIFIER_MODEL=qwen3-max` |
| 前端进度条渲染异常 | 用户体验差 | 降级为不展示进度条，仅展示最终回答 |
| Plan-Execute 总超时 | 用户等待过长 | `total_timeout` 默认 120s，超时返回已完成步骤的部分结果 |

---

## 十四、后续优化方向（不在本次范围）

1. **记忆型分类器**：记录用户历史查询的复杂度分布，个性化调整分类阈值
2. **分类反馈学习**：用户可通过 UI 反馈"这是一个简单问题"或"这是一个复杂问题"，持续优化规则
3. **Plan 模板库**：常见复杂任务（如"学习周报"、"知识总结"）沉淀为可复用的 Plan 模板
4. **流式 Plan 修正**：执行过程中如果发现计划不足，Agent 可触发 replan
5. **多模型智能路由**：根据查询类型（代码/写作/分析）自动选择最合适的模型
