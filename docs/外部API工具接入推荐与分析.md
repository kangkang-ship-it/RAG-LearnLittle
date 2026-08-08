# 外部 API 工具接入推荐与分析（直接集成）

> **版本：v1.1**（第九轮评审后修订：补 tts_router 注册、对齐存储路径、tag_handling 可选增强）  
> **文档目的：** 在 12 个内部工具 + RAG 管线 + 已推荐 5 个 MCP Server（Tavily / Fetch / Playwright / Brave Search / Python REPL）的基础上，分析是否还有值得以 **直接 API 集成**（非 MCP 协议）方式接入的外部工具/服务。  
> **与 MCP 推荐文档的关系：** 互补而非替代。MCP 文档聚焦"项目边界之外的通用能力"（搜索/抓取/浏览器/代码执行），本文档聚焦"需要精细控制、稳定 API 契约、或无现成 MCP Server 的专项能力"。  
> **代码基准：commit fe1f5ca（2026-08-08）**。  
> **日期：** 2026-08-08  
> **状态：** 待评审（已根据项目 MCP 配置落地同步更新；第九轮评审修订）

---

## 一、为什么需要直接 API 集成（而非全部走 MCP）

| 维度 | 直接 API 集成的优势 | MCP 更适合的场景 |
|---|---|---|
| **控制粒度** | 可精细控制请求参数、错误重试、降级策略、缓存 | 标准化协议，工具描述由 server 端决定 |
| **响应格式** | 可定制返回格式，减少 token 消耗 | 通用格式，可能包含冗余信息 |
| **依赖复杂度** | 一个 `httpx` 调用即可，无额外运行时 | 需 Node.js/Python 子进程 + MCP 协议栈 |
| **稳定性** | 直接 HTTP 调用，故障点少 | 多一层 stdio/pipe 通信 |
| **无 MCP Server** | 部分 API 无现成 MCP Server 实现 | 社区已有成熟 MCP Server 的服务 |

**结论**：对于 API 接口简单、响应格式明确、且需要精细控制的服务，直接封装为 `@tool` 比走 MCP 更轻量、更可控。

---

## 二、能力缺口分析

### 2.1 当前已覆盖能力全景

| 能力域 | 覆盖来源 | 边界 |
|---|---|---|
| 笔记 CRUD + 语义搜索 | 12 个内部工具 | 完整 |
| 间隔重复回顾 | 内部工具（艾宾浩斯） | 完整 |
| 文档 RAG 检索 | RAG 管线（HyDE + 双源 + 重排序） | 仅限本地文档 |
| 联网搜索 | MCP #1 Tavily（已配置，白名单 `tavily_search` + `tavily_extract`） | 通用搜索 + URL 提取 |
| 网页内容抓取 | MCP #2 Fetch（已配置，`mcp-server-fetch` + `mcp<2` 固定） | HTML → Markdown |
| 浏览器自动化 | MCP #3 Playwright（待 Phase 2） | JS 渲染 / 表单交互 |
| 代码执行 | MCP #5 Python REPL（待 Phase 3） | 沙箱执行 |
| 邮件 / PPT | 内部工具 | 完整 |
| 图片/视频理解 | 多模态处理器（base64 → 视觉模型） | 模型直接理解，无独立 OCR |

### 2.2 仍然缺失的能力

| 缺失能力 | 12 工具 + RAG + MCP 能否覆盖 | 缺口性质 |
|---|---|---|
| **高质量翻译** | LLM 可翻译但质量不稳定（术语不一致、长文退化、无词汇表） | 质量缺口 |
| **精确数学/科学计算** | LLM 计算不可靠（大数运算、单位换算、方程求解常出错）；Python REPL 可缓解但需用户写代码 | 可靠性缺口 |
| **语音播报/音频学习** | 系统无任何 TTS 能力，无法将笔记转为音频 | 能力空白 |
| 图表渲染 | LLM 可生成 Mermaid 语法但无法渲染为图片 | 渲染缺口（可通过本地库解决，无需外部 API） |
| OCR 文字识别 | 多模态处理器已将图片送视觉模型理解，无需独立 OCR | 已覆盖 |

---

## 三、推荐排序总览

按「用户价值 × 实现成本」综合评分：

| 排名 | API 服务 | 核心能力 | 用户价值 | 实现成本 | 综合评分 | 建议阶段 |
|---|---|---|---|---|---|---|
| **#1** | **DeepL** | 高质量翻译 | ★★★★★ | ★☆☆☆☆ 极低 | **90** | Phase 1（推荐） |
| **#2** | **Wolfram Alpha** | 精确数学/科学计算 | ★★★★☆ | ★★☆☆☆ 低 | **78** | Phase 2 |
| **#3** | **Edge TTS** | 语音合成（笔记朗读） | ★★★☆☆ | ★☆☆☆☆ 极低 | **72** | Phase 2 |

---

## 四、Top 3 详细分析

### 4.1 #1 DeepL — 高质量翻译 API（推荐）

#### 是什么

DeepL 是全球公认翻译质量最高的机器翻译服务（优于 Google Translate），支持中/英/日/韩/法/德等 31 种语言。API 为简单 REST 接口，发送文本即返回翻译结果。

#### 为什么不用 LLM 原生翻译

| 维度 | LLM 原生翻译 | DeepL API |
|---|---|---|
| 术语一致性 | 同一术语在不同段落可能翻译不同 | 内置词汇表（Glossary）保证一致 |
| 长文本稳定性 | 超长文本翻译质量随 token 增加退化 | 按字符计费，无质量退化 |
| 格式保留 | 可能破坏 Markdown 格式标记 | 支持 `tag_handling=html` 保留格式标签（API 支持，示例代码未体现，可作为可选增强参数） |
| 成本 | 翻译 50 万英文字符 ≈ 消耗 ~12.5 万 tokens（中文更高），按模型定价计费 | 免费额度 50 万字符/月（具体以 [deepl.com](https://www.deepl.com/pro-api) 官网实时说明为准），超出 $25/百万字符 |
| 延迟 | 需完整 LLM 推理（1~5s） | API 响应通常 < 500ms |

#### 解决的具体场景

| 场景 | 用户原话示例 | 当前系统表现 | +DeepL 后 |
|---|---|---|---|
| 英文论文翻译 | "帮我把这段英文摘要翻译成中文" | LLM 翻译，术语可能不一致 | DeepL 高质量翻译，术语统一 |
| 笔记翻译存档 | "把这篇笔记翻译成英文，存为新笔记" | LLM 翻译 → `create_note_tool` | DeepL 翻译 → `create_note_tool`（质量更高） |
| 结合 RAG 跨语言检索 | "我上传了一份英文 PDF，帮我总结要点" | RAG 检索 + LLM 中文总结 | 可先 DeepL 翻译关键段落 → 更精准的中文总结 |
| 结合邮件发送 | "把这篇笔记翻译成英文发到我邮箱" | LLM 翻译 → `send_email` | DeepL 翻译 → `send_email`（术语更准确） |

#### 实现方式

封装为 LangChain `@tool`，放入新的 `translate` 工具组：

```python
# app/ai_service/agent_tools.py 内新增（或独立文件 translate_tool.py）
import httpx
from langchain_core.tools import tool

_DEEPL_MAX_CHARS = 5000

@tool
async def translate_text(text: str, target_lang: str, source_lang: str = "") -> str:
    """使用 DeepL 将文本翻译为目标语言（质量优于 LLM 原生翻译）。

    Args:
        text: 要翻译的文本（最多 5000 字符/次，超出自动截断并提示）
        target_lang: 目标语言代码（如 ZH, EN, JA, KO, DE, FR）
        source_lang: 源语言代码（可选，留空自动检测）
    """
    api_key = os.getenv("DEEPL_API_KEY")
    if not api_key:
        return "翻译服务未配置（缺少 DEEPL_API_KEY）"
    # Free 与 Pro 端点不同，通过环境变量区分（默认 Free）
    base_url = os.getenv("DEEPL_API_URL", "https://api-free.deepl.com/v2/translate")
    truncated = len(text) > _DEEPL_MAX_CHARS
    if truncated:
        text = text[:_DEEPL_MAX_CHARS]
    params = {
        "text": text,
        "target_lang": target_lang.upper(),
    }
    if source_lang:
        params["source_lang"] = source_lang.upper()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            base_url, data=params,
            headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
        )
        resp.raise_for_status()
        result = resp.json()
    translations = result.get("translations", [])
    if not translations:
        return "翻译结果为空"
    output = translations[0]["text"]
    if truncated:
        output += f"\n\n[提示：原文超过 {_DEEPL_MAX_CHARS} 字符，已截断]"
    return output
```

- **工具组**：`translate`（新增至 `agent.yaml` `tool_groups`）
- **依赖**：零新增（已有 `httpx>=0.28.0`）
- **异步**：原生 `httpx.AsyncClient`，完全兼容
- **Token 影响**：工具描述 ~150 tokens，翻译结果由 API 返回（不消耗模型 token 生成翻译）

#### 兼容性确认

| 维度 | 状态 |
|---|---|
| API 类型 | REST（POST），`httpx` 直接调用 ✅ |
| API Key | 需要 `DEEPL_API_KEY`（[deepl.com/pro-api](https://www.deepl.com/pro-api) 注册） |
| 免费额度 | **50 万字符/月**（DeepL API Free，无需信用卡；具体额度以 [deepl.com](https://www.deepl.com/pro-api) 官网实时说明为准） |
| 付费方案 | Pro：$5.49/月底费 + $25/百万字符 |
| 中文支持 | ✅ 支持 ZH（简/繁）↔ EN/JA/KO/DE/FR 等 31 种语言 |
| 异步兼容 | 纯 HTTP 调用，`httpx.AsyncClient` ✅ |
| 项目依赖 | 零新增（`httpx` 已在 `requirements.txt`） |

#### 实施成本

~0.3 天（注册 API Key + 封装工具 + 加入工具组 + 联调），**直接集成中 ROI 最高**。

---

### 4.2 #2 Wolfram Alpha — 精确数学/科学计算 API（推荐）

#### 是什么

Wolfram Alpha 是全球最大的计算知识引擎，覆盖数学求解、单位换算、物理/化学计算、数据统计、地理/天文计算等数千个领域。提供专门的 **LLM API**（返回结构化 JSON，针对 LLM 消费优化）和 **Short Answers API**（返回简短文字答案）。

#### 为什么不用 LLM / Python REPL

| 维度 | LLM 原生 | Python REPL（MCP #5） | Wolfram Alpha API |
|---|---|---|---|
| 数学求解 | 经常出错（尤其微积分、方程组） | 需用户/LLM 写 sympy 代码 | 自然语言直接求解 |
| 单位换算 | 大数/复合单位常出错 | 可做但需写代码 | "100 km/h in m/s" 直接出结果 |
| 科学数据 | 可能幻觉（元素周期表、天体数据等） | 无内置数据库 | 覆盖完整科学数据库 |
| 使用门槛 | 低（自然语言） | 高（需写代码） | 低（自然语言） |
| 延迟 | 1~5s | 依赖代码复杂度 | ~2s（Full Results）/ <500ms（Short Answers） |

#### 解决的具体场景

| 场景 | 用户原话示例 | 当前系统表现 | +Wolfram Alpha 后 |
|---|---|---|---|
| 数学求解 | "帮我解这个方程 x² + 5x + 6 = 0" | LLM 可能算错 | Wolfram 精确求解 + 步骤 |
| 单位换算 | "100 千米/小时等于多少米/秒" | LLM 可能算错 | 精确换算 |
| 科学计算 | "水的摩尔质量是多少" | LLM 可能幻觉 | 精确科学数据 |
| 结合笔记 | "算一下这道物理题，把解题过程记到笔记里" | LLM 计算不可靠 → 笔记可能含错误 | Wolfram 精确计算 → `create_note_tool` 存正确过程 |

#### 实现方式

封装为 LangChain `@tool`，使用 **Short Answers API**（返回简短文字，token 消耗最低）：

```python
@tool
async def wolfram_calculate(query: str) -> str:
    """使用 Wolfram Alpha 进行精确的数学计算、单位换算和科学查询。
    适用于：解方程、求导、积分、单位换算、科学数据查询等。
    当 LLM 自身计算不确定时，优先调用本工具获取可靠结果。

    Args:
        query: 计算查询（英文效果最佳，如 "solve x^2+5x+6=0"、"100 km/h in m/s"）
    """
    app_id = os.getenv("WOLFRAM_APP_ID")
    if not app_id:
        return "计算服务未配置（缺少 WOLFRAM_APP_ID）"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.wolframalpha.com/v1/result",
            params={"appid": app_id, "i": query},
        )
        if resp.status_code == 400:
            return f"Wolfram Alpha 无法理解查询: {query}"
        resp.raise_for_status()
        return resp.text
```

- **工具组**：`compute`（新增至 `agent.yaml` `tool_groups`）
- **依赖**：零新增（已有 `httpx`）
- **异步**：原生 `httpx.AsyncClient` ✅
- **Token 影响**：工具描述 ~200 tokens；Short Answers 返回通常 < 100 字符

#### 兼容性确认

| 维度 | 状态 |
|---|---|
| API 类型 | REST（GET），`httpx` 直接调用 ✅ |
| API Key | 需要 `WOLFRAM_APP_ID`（[developer.wolframalpha.com](https://developer.wolframalpha.com) 注册） |
| 免费额度 | **2,000 次/月**（非商业，Short Answers API；具体额度以 [wolframalpha.com](https://products.wolframalpha.com/api) 官网实时说明为准） |
| LLM API | 有专门针对 LLM 优化的 API（返回结构化 JSON），可后续升级 |
| 中文支持 | ⚠️ 查询建议用英文（中文支持有限），工具描述中需注明 |
| 异步兼容 | 纯 HTTP 调用 ✅ |
| 项目依赖 | 零新增 |

#### 实施成本

~0.5 天（注册 AppID + 封装工具 + 联调 + 提示词指引）。

---

### 4.3 #3 Edge TTS — 语音合成 / 笔记朗读（推荐）

#### 是什么

`edge-tts` 是一个 Python 库，调用微软 Edge 在线 TTS 服务将文本转为高质量神经语音 MP3。支持 100+ 语言（含中文"晓晓""云扬"等多款神经语音），**完全免费、无需 API Key、原生异步**。

#### 解决的具体场景

| 场景 | 用户原话示例 | 当前系统表现 | +Edge TTS 后 |
|---|---|---|---|
| 笔记朗读 | "把这篇笔记读给我听" | 只能文字展示 | TTS 生成 MP3 → 返回音频文件 |
| 语言学习 | "用英文朗读这段笔记" | 无语音能力 | DeepL 翻译 → Edge TTS 英文朗读 |
| 通勤/运动复习 | "把今日待回顾的笔记生成音频" | 只能屏幕阅读 | `get_today_reviews_tool` → 逐篇 TTS → 合并 MP3 |
| 结合邮件 | "把笔记转成音频发到我邮箱" | 无此能力 | TTS → 音频附件 → `send_email` |

#### 实现方式

封装为 LangChain `@tool`，放入 `tts` 工具组：

```python
@tool
async def text_to_speech(text: str, voice: str = "zh-CN-XiaoxiaoNeural") -> str:
    """将文本转换为语音 MP3 文件。
    支持中英文等多种语言，可用于笔记朗读、语言学习等场景。

    Args:
        text: 要转换的文本（最多 2000 字符/次）
        voice: 语音名称（默认 zh-CN-XiaoxiaoNeural；
               英文可选 en-US-JennyNeural；完整列表可调用 list_voices）
    """
    import edge_tts
    text = text[:2000]  # 保护上下文窗口
    # 存储到 data/tts/（与 §5.2 tts_router 端点一致，服务器重启不丢文件）
    output_dir = os.path.join("data", "tts")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"tts_{uuid4().hex[:8]}.mp3")
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)
    # 返回文件路径（前端通过 tts_router 专属端点下载）
    return json.dumps({"audio_url": f"/api/download/tts/{os.path.basename(output_file)}",
                       "duration_estimate": f"~{len(text)//10}s"})
```

- **工具组**：`tts`（新增至 `agent.yaml` `tool_groups`）
- **依赖**：新增 `edge-tts`（`pip install edge-tts`，传递依赖 aiohttp / certifi / tabulate 等约 13 个包，`pip` 自动安装）
- **异步**：原生 `asyncio`，`Communicate.save()` 为异步方法 ✅
- **Token 影响**：工具描述 ~150 tokens；返回 JSON 元数据（不消耗模型 token 生成音频）

#### 兼容性确认

| 维度 | 状态 |
|---|---|
| Python 包 | `edge-tts`（PyPI，MIT 协议）✅ |
| API Key | **不需要**（完全免费，无需注册） |
| 中文语音 | ✅ `zh-CN-XiaoxiaoNeural`（晓晓）/ `zh-CN-YunxiNeural`（云扬）等多款 |
| 英文语音 | ✅ `en-US-JennyNeural` / `en-GB-SoniaNeural` 等 |
| 异步兼容 | 原生 `asyncio` ✅（与项目 FastAPI 事件循环完全兼容） |
| 网络要求 | 需联网（访问微软 Edge TTS 服务器），国内通常可直连 ⚠️ |
| 输出格式 | MP3（可前端直接播放） |
| 字幕生成 | 支持同步生成 SRT/WebVTT 字幕（`SubMaker` 类） |

#### 实施成本

~0.5 天（安装依赖 + 封装工具 + 音频下载路由 + 联调）。

---

## 五、实施路线

### 5.1 分阶段计划

```
Phase 1（1 天内）  DeepL 翻译工具
                 ├─ 注册 DeepL API Free Key
                 ├─ 封装 translate_text 工具
                 ├─ agent.yaml 新增 translate 工具组
                 └─ 联调（翻译 → create_note_tool → 邮件/PPT）

Phase 2（1~2 天） Wolfram Alpha + Edge TTS
                 ├─ 注册 Wolfram Alpha AppID
                 ├─ 封装 wolfram_calculate 工具
                 ├─ pip install edge-tts
                 ├─ 封装 text_to_speech 工具
                 ├─ agent.yaml 新增 compute / tts 工具组
                 └─ 端到端联调
```

> **工具组路由决策（C1）**：`translate` / `compute` / `tts` 三组参照 `ppt` 组模式——**不加入 `default_groups`，仅通过 `keyword_rules` 关键词触发加载**（与 `ppt` 组同理：工具 schema 越少幻觉率越低）。完整关键词规则：
>
> ```yaml
> tool_routing:
>   keyword_rules:
>     translate:    # 翻译意图
>       - "翻译"
>       - "翻译成"
>       - "translate"
>       - "英文翻译成中文"
>       - "中文翻译成英文"
>     compute:      # 计算意图
>       - "计算"
>       - "求解"
>       - "解方程"
>       - "单位换算"
>     tts:          # 语音意图
>       - "朗读"
>       - "读给我听"
>       - "转成语音"
>       - "转成音频"
>       - "念给我听"
> ```

### 5.2 改动范围

| 文件 | 改动 | 估算 |
|---|---|---|
| `requirements.txt` | 新增 `edge-tts`（DeepL / Wolfram 零新增依赖） | 1 行 |
| `config/agent.yaml` | 新增 3 个工具组 + `keyword_rules`（见上方完整词表） | ~30 行 |
| `app/ai_service/agent_tools.py` | 新增 3 个 `@tool` 函数 | ~100 行 |
| `app/routers/tts_router.py` | **新增**：TTS 音频下载端点（参照 `ppt_router.py` 模式：文件存 `data/tts/` + 专属 GET 端点 + 前端下载卡片） | ~30 行 |
| `main.py` | 注册 `tts_router`（`app.include_router(tts_router.router, ...)`，参照 `ppt_router` 注册方式） | 1 行 |
| `.env` / `.env.example` | 新增 `DEEPL_API_KEY` + `WOLFRAM_APP_ID` | 2 行 |
| `prompts/main_prompt.txt` | 补充翻译/计算/语音工具使用指引 | ~5 行 |

**总计：~170 行新增**，1~2 天完成全部 3 个工具。

---

## 六、与现有工具 / MCP 工具的协同

```
┌──────────────────────────────────────────────────────────────┐
│                   外部 API 工具层                              │
│  DeepL（翻译）    Wolfram Alpha（计算）    Edge TTS（语音）     │
└─────────────────────────┬────────────────────────────────────┘
                          │ 翻译结果 / 计算结果 / 音频文件
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                   MCP 外部能力层                               │
│  Tavily（搜索）    Fetch（抓取）    Playwright（浏览器）        │
└─────────────────────────┬────────────────────────────────────┘
                          │ 搜索结果 / 网页内容
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                   原生工具处理层                                │
│  create_note_tool / update_note_tool / send_email / PPT       │
└──────────────────────────────────────────────────────────────┘
```

**典型端到端链路**：

| 链路 | 工具调用序列 |
|---|---|
| 翻译→笔记 | `translate_text` → `create_note_tool` |
| 搜索→翻译→笔记 | `tavily_search`（英文结果）→ `translate_text` → `create_note_tool` |
| 计算→笔记 | `wolfram_calculate` → LLM 整理 → `create_note_tool` |
| 笔记→朗读 | `get_note_content_tool` → `text_to_speech` → 返回音频 |
| 回顾→音频 | `get_today_reviews_tool` → 逐篇 `text_to_speech` → 合并 MP3 |
| 翻译→邮件 | `translate_text` → `send_email`（翻译后发送） |
| 搜索→计算→笔记 | `tavily_search` → `wolfram_calculate` → `create_note_tool` |

---

## 七、风险与规避

| # | 风险 | 等级 | 规避措施 |
|---|---|---|---|
| 1 | **DeepL 免费额度耗尽** | 🟢 低 | 50 万字符/月 ≈ 10 万词/月，个人学习使用通常充足；超限后 LLM 翻译降级兜底 |
| 2 | **Wolfram Alpha 中文理解差** | 🟡 中 | 工具描述中注明"建议使用英文查询"；Agent 可在调用前用 LLM 将中文查询翻译为英文 |
| 3 | **Edge TTS 网络不可达** | 🟡 中 | 国内通常可直连微软服务器；降级策略：返回"语音服务暂不可用" + 文字替代 |
| 4 | **工具数膨胀 token** | 🟢 低 | 当前 12 内部 + 3 MCP（Tavily 白名单 2 + Fetch 1）= 15 工具；新增 3 个外部 API 工具后总计 18，描述合计增量 ~500 tokens，仍在 qwen3-max function calling 能力范围内 |
| 5 | **Wolfram 免费额度耗尽** | 🟢 低 | 2,000 次/月，个人使用充足；超限后降级为 Python REPL 计算或 LLM 估算 |

---

## 八、排除项说明

| 候选 API | 排除理由 |
|---|---|
| **OCR（Google Vision / Tesseract）** | 多模态处理器已将图片/视频送视觉模型理解（[multimodal_processor.py](../app/ai_service/multimodal_processor.py)），视觉模型的文字识别能力已足够，独立 OCR 为冗余能力 |
| **Mermaid 图表渲染** | LLM 可生成 Mermaid 语法，渲染可通过前端组件或本地 `mermaid-cli` 完成，无需外部 API；且使用频率较低 |
| **Semantic Scholar** | 学术论文检索，与 Tavily（通用搜索）+ Fetch（URL 抓取）有功能重叠；MCP 文档 §1.2 列有"学术/论文检索"能力缺口但尚未指定具体 API，可远期评估 |
| **Google / Microsoft 翻译** | 翻译质量公认低于 DeepL；DeepL API Free 免费额度（50 万字符/月）已足够个人使用 |
| **Azure TTS** | Edge TTS 使用相同的微软神经语音引擎，质量一致，但完全免费且无需 API Key；Azure TTS 无额外收益 |
| **日历/提醒 API** | 与现有 `review_service` 间隔重复回顾功能重叠，且非学习助手核心需求 |
| **图片生成（DALL-E / SD）** | 与学习助手定位关联度低，且 MCP 文档未列为优先级 |

---

## 九、结论

1. **Phase 1 推荐**：DeepL 翻译工具 —— 0.3 天完成，零新增依赖，立即解锁"高质量翻译 → 笔记 → 邮件/PPT"链路。
2. **Phase 2 推荐**：Wolfram Alpha（精确计算）+ Edge TTS（语音朗读）—— 1~1.5 天完成，补全"计算可靠性"和"音频学习"两项能力空白。
3. **不接**：OCR（视觉模型已覆盖）、Mermaid 渲染（本地可解决）、与已有工具/MCP 功能重叠的服务。

**一句话**：DeepL + Wolfram Alpha + Edge TTS，3 个工具 ~130 行代码，1~2 天完成，补全翻译/计算/语音三项 LLM 原生能力短板，与 12 个内部工具 + 5 个 MCP 工具形成完整能力矩阵。

---

## 十、与 MCP 推荐文档的分工对照

| 能力 | MCP 方案 | 直接 API 方案（本文档） | 推荐选择 |
|---|---|---|---|
| 联网搜索 | Tavily ✅（已配置，白名单 2 工具） | — | MCP |
| 网页抓取 | Fetch ✅（已配置，`mcp<2` 固定） | — | MCP |
| 浏览器自动化 | Playwright（待 Phase 2） | — | MCP |
| 代码执行 | Python REPL（待 Phase 3） | — | MCP |
| **翻译** | 无现成 MCP Server | **DeepL API** ✅ | 直接 API |
| **数学计算** | Python REPL（需写代码） | **Wolfram Alpha**（自然语言）✅ | 直接 API（体验更好） |
| **语音合成** | 无现成 MCP Server | **Edge TTS** ✅ | 直接 API |

**分工原则**：通用信息获取（搜索/抓取/浏览器）走 MCP；专项能力（翻译/计算/语音）走直接 API——前者标准化程度高、MCP 生态成熟；后者需要精细控制、API 简单、直接调用更轻量。

> **当前进度**：MCP Phase 1 已在工作区实现（`agent.yaml` 已配置 Tavily + Fetch，`default_groups` 已含 `mcp`，`requirements.txt` 已加 `langchain-mcp-adapters>=0.3.2`），**尚未提交**——代码基准 commit 不含 MCP，实施前需先提交 MCP 代码并更新基准至最新 commit。本文档推荐的外部 API 工具尚未实施，可按 Phase 1（DeepL）→ Phase 2（Wolfram Alpha + Edge TTS）路线推进。

> **TTS 前端消费机制（C3）**：音频文件通过 `tts_router.py` 专属 GET 端点提供下载（参照 `ppt_router.py:32` 的 PPT 下载模式）。SSE 事件中 `text_to_speech` 工具返回 `audio_url` 字段，前端收到后渲染下载卡片/内联播放器（与 PPT 下载卡片交互一致）。

---

## 十一、审查修订记录（v1.0 → v1.1）

| # | 优先级 | 问题 | 修订位置 |
|---|---|---|---|
| A1 | 🔴 | TTS `audio_url` 指向不存在的路由 `/api/download/tts/xxx`，§5.2 改动范围表漏列音频下载路由 | §5.2 新增 `app/routers/tts_router.py` 行（~30 行），参照 `ppt_router.py` 模式 |
| A2 | 🔴 | 代码基准 fe1f5ca 不含 MCP（未提交），与"MCP Phase 1 已落地"描述矛盾 | §10 进度段补注"尚未提交"，提示实施前需先提交并更新基准 |
| B1 | 🟡 | §4.1 "翻译 50 万字符 ≈ 消耗 ~25K tokens"严重低估（50 万英文字符 ≈ 12.5 万 tokens） | §4.1 成本行重写为 ~12.5 万 tokens，并注明中文更高 |
| B2 | 🟡 | §4.1/§4.2 免费额度写死数字，与 MCP 文档"以官网为准"惯例不一致 | DeepL / Wolfram 免费额度均补注"以官网实时说明为准" |
| B3 | 🟡 | §4.3 edge-tts "~50KB，无重依赖"不成立（实际依赖 aiohttp 等 ~13 个包） | §4.3 改为"传递依赖 aiohttp / certifi / tabulate 等约 13 个包" |
| B4 | 🟡 | §8 "Semantic Scholar…MCP 文档已将其列为远期评估项"为虚假引用 | 改为"MCP 文档 §1.2 列有学术/论文检索能力缺口但尚未指定具体 API" |
| C1 | 🟢 | translate / compute / tts 三组是否进 default_groups 未明确 | §5.1 补"工具组路由决策"段：参照 ppt 组模式，keyword_rules 触发，不进 default_groups；附完整关键词规则 |
| C2 | 🟢 | DeepL 示例代码：`auth_key` 应走 Header、`base_url` 硬编码 Free 端点、截断无提示 | §4.1 代码重写：Authorization Header + `DEEPL_API_URL` 环境变量 + 截断提示 |
| C3 | 🟢 | TTS 前端消费机制未描述（SSE 事件如何携带 audio_url） | §10 补"TTS 前端消费机制"段：参照 PPT 下载卡片模式 |
| D1 | 🟢 | §5.2 改动范围漏 `main.py`——新增 `tts_router.py` 后需注册路由 | §5.2 新增 `main.py` 行（1 行，`app.include_router`） |
| D2 | 🟢 | §4.3 代码示例用 `tempfile.mkdtemp`（临时目录），与 §5.2 `data/tts/` 存储方案不一致 | §4.3 代码改为 `data/tts/` + `os.makedirs`，与端点路径对齐 |
| D3 | 🟢 | §4.1 表格称"支持 `tag_handling=html`"但代码未体现 | §4.1 表格补注"可作为可选增强参数" |
