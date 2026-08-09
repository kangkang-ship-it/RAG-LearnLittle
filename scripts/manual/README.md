# 手动验证脚本（非 CI 测试）

此目录收纳从项目根目录移入的调试/手工验证脚本。**它们不是单元测试**：
依赖真实 MySQL/Redis、真实 LLM/外部 API，CI 不会执行（正式测试在 `tests/` 下）。

> ⚠️ 运行前需准备：`.env` 已配置（DB/Redis/API Key）、MySQL/Redis 已启动。

## 各脚本用途与处置建议

| 文件 | 用途 | 处置建议 |
| :--- | :--- | :--- |
| `test_mcp_phase1.py` | MCP 工具接入的集成验证（真实拉起 tavily/fetch server） | 保留供 MCP 改动后手工回归；有价值场景可转 pytest（mock stdio server） |
| `test_external_api_tools.py` | 外部 API 工具（DeepL/Wolfram/TTS）联调 | 同上 |
| `test_plan_execute.py` | Plan-and-Execute 混合路由验证 | 同上（注意其中「重复输出修复」场景） |
| `test_repeat_fix.py` | Agent 重复输出修复的回归验证 | **建议转 pytest**：内容纯逻辑可复用，是踩坑沉淀 |
| `test_aspose_renderer.py` | 遗留 Aspose 云端渲染引擎验证（已降级 python-pptx） | 随 `ppt_renderer_aspose.py` 死代码一并删除 |
| `repro_tmp.py` / `verify_tz_tmp.py` | 一次性问题复现/时区验证 | 问题已解决，可删除 |
| `test_img_tmp.png` | 调试用图片样本 | 可删除（正式样本放 `tests/fixtures/`） |
| `verify_katex_tmp.js` | 前端 KaTeX 渲染验证（原 `front/` 下） | 可删除 |
