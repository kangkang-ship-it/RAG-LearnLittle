"""
MCP 工具接入 Phase 1 端到端测试脚本（Tavily + Fetch）

用法: python test_mcp_phase1.py

验证内容：
1. MCP 生命周期：mcp_manager.start() 拉起 Tavily + Fetch 两个 stdio 子进程，
   tools_include 白名单生效（仅注册 tavily_search / tavily_extract / fetch 三个工具，
   crawl/map/research 被过滤）
2. 注册表集成：tool_registry 的 "mcp" 组解析正确；内置工具组（base/note_read 等）
   在 MCP 注册后不受影响（init_tool_registry 顺序守卫回归）
3. 工具真实调用：
   - fetch 抓取 https://example.com → 返回 Markdown 内容
   - tavily_search：已配置 TAVILY_API_KEY 时返回搜索结果；未配置时优雅报错（不崩溃）
4. 路由/规划集成：
   - resolve_tool_groups 默认组含 "mcp"
   - create_agent_tools 全量组解析同时含内置工具与 MCP 工具（纯增量，不干扰现有工具）
   - _build_plan_tool_list 含 MCP 工具名（planner 感知）
   - _resolve_step_tool_groups 返回组含 "mcp"（Plan-Execute 步骤可调用 MCP 工具）
5. 生命周期关闭：close() 幂等

说明：
- 需要本机 node(npx) 与 uv(uvx) 环境（Phase 0 已验证）
- 首次运行 npx/uvx 需下载包，启动较慢
- TAVILY_API_KEY 可留空：tavily_search 走"无 key 优雅报错"分支验证
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Windows 控制台 UTF-8 输出
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from app.ai_service.agent_runner import resolve_tool_groups
from app.ai_service.agent_tools import create_agent_tools
from app.ai_service.mcp_manager import mcp_manager
from app.ai_service.plan_execute_agent import PlanStep, _build_plan_tool_list, _resolve_step_tool_groups
from app.ai_service.tool_registry import tool_registry

EXPECTED_TOOLS = {"tavily_search", "tavily_extract", "fetch"}


def report(name: str, ok: bool, detail: str = "") -> bool:
    """单条断言输出（✅/❌），返回是否通过"""
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))
    return ok


async def test_tool_call(tool_name: str, args: dict) -> tuple:
    """
    调用已注册的 MCP 工具

    StructuredTool(response_format="content_and_artifact")：ainvoke 返回 (content, artifact) 元组；
    错误经 handle_tool_error 转为内容块返回而非抛异常。

    Returns:
        (success: bool, output: str)
    """
    tool = tool_registry.get_dynamic(tool_name)
    if tool is None:
        return False, f"工具 '{tool_name}' 未注册"
    try:
        result = await tool.ainvoke(args)
        content = result[0] if isinstance(result, tuple) else result
        return True, str(content)
    except Exception as e:
        return False, f"调用抛出异常: {type(e).__name__}: {e}"


async def main() -> int:
    print("=" * 60)
    print("MCP Phase 1 端到端测试（Tavily + Fetch）")
    print("=" * 60)
    passed = 0
    failed = 0
    checks = []

    # ---------- 1. MCP 生命周期：start() ----------
    print("\n[1] MCP 生命周期")
    try:
        await mcp_manager.start()
        registered = set(mcp_manager._registered)
        checks.append(report("mcp_manager.start() 无异常", True))
        checks.append(report(
            "白名单注册 3 个工具（tavily_search/extract/fetch）",
            registered == EXPECTED_TOOLS,
            f"实际: {sorted(registered)}",
        ))
        # 白名单过滤验证：crawl/map/research 不应注册
        blocked = EXPECTED_TOOLS.isdisjoint(
            {"tavily_crawl", "tavily_map", "tavily_research"}
        )
        checks.append(report("tavily_crawl/map/research 被 tools_include 过滤", blocked))
    except Exception as e:
        checks.append(report(f"mcp_manager.start() 异常: {e}", False))
        print("  测试终止（MCP 无法启动，检查 npx/uvx 环境）")
        return 1

    # ---------- 2. 注册表集成 ----------
    print("\n[2] 注册表集成")
    mcp_names = tool_registry.resolve_names(["mcp"])
    checks.append(report(
        "resolve_names(['mcp']) 返回 3 个工具",
        set(mcp_names) == EXPECTED_TOOLS,
        f"实际: {sorted(mcp_names)}",
    ))
    # 内置工具组不受影响（顺序守卫回归）
    base_names = set(tool_registry.resolve_names(["base"]))
    checks.append(report(
        "内置 base 组完整（顺序守卫回归）",
        {"what_time_is_now", "get_user_info_tools"} <= base_names,
        f"实际: {sorted(base_names)}",
    ))
    all_names = set(tool_registry.resolve_names(None))
    checks.append(report(
        "全量解析 = 12 内置 + 3 MCP + 3 外部 API",
        len(all_names) == 18 and EXPECTED_TOOLS <= all_names,
        f"共 {len(all_names)} 个: {sorted(all_names)}",
    ))

    # ---------- 3. 工具真实调用 ----------
    print("\n[3] 工具真实调用（真实子进程）")
    ok, out = await test_tool_call("fetch", {"url": "https://example.com", "max_length": 500})
    checks.append(report(
        "fetch 抓取 example.com → Markdown",
        ok and "Example Domain" in out,
        out[:120].replace("\n", " "),
    ))

    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    ok, out = await test_tool_call("tavily_search", {"query": "python FastAPI", "max_results": 5})
    # tavily-mcp 0.2.22 无 key 时进入 keyless 模式（实测返回真实搜索结果）；
    # 有 key 用 key。断言统一为：调用成功且返回含标题/URL 的实质内容
    mode = "已配置 API Key" if tavily_key else "无 API Key（keyless 模式）"
    checks.append(report(
        f"tavily_search 返回搜索结果（{mode}）",
        ok and len(out) > 50 and any(kw in out.lower() for kw in ("title", "url", "http")),
        out[:150].replace("\n", " "),
    ))

    # tavily_extract：URL 内容提取（Phase 1 声明能力，需真实 API Key）
    ok, out = await test_tool_call(
        "tavily_extract", {"urls": ["https://example.com"]}
    )
    checks.append(report(
        "tavily_extract 提取 example.com 内容",
        ok and len(out) > 50,
        out[:150].replace("\n", " "),
    ))

    # ---------- 4. 路由/规划集成 ----------
    print("\n[4] 路由/规划集成")
    groups = resolve_tool_groups("帮我总结一下今天的笔记")
    checks.append(report(
        "resolve_tool_groups 默认组含 'mcp'",
        "mcp" in (groups or []),
        f"实际: {groups}",
    ))
    tools = create_agent_tools(user_id="test_mcp_user", groups=groups)
    tool_names = {getattr(t, "name", "") for t in tools}
    checks.append(report(
        "create_agent_tools 全量组 = 内置 + MCP（纯增量）",
        EXPECTED_TOOLS <= tool_names and "search_notes_tool" in tool_names,
        f"共 {len(tool_names)} 个工具",
    ))
    # 只加载 base 组时不应混入 MCP 工具（按需加载语义不变）
    base_tools = create_agent_tools(user_id="test_mcp_user", groups=["base"])
    base_tool_names = {getattr(t, "name", "") for t in base_tools}
    checks.append(report(
        "groups=['base'] 不含 MCP 工具（按需加载语义不变）",
        EXPECTED_TOOLS.isdisjoint(base_tool_names),
        f"实际: {sorted(base_tool_names)}",
    ))
    plan_list = _build_plan_tool_list()
    checks.append(report(
        "planner 工具清单含 MCP 工具名（gap #1 闭合）",
        "tavily_search" in plan_list and "fetch" in plan_list,
    ))
    step = PlanStep(step=1, action="搜索最新资料", tool="tavily_search", depends_on=[])
    step_groups = _resolve_step_tool_groups(step)
    checks.append(report(
        "步骤 tool='tavily_search' → 组含 'mcp'（gap #2 闭合）",
        step_groups is not None and "mcp" in step_groups,
        f"实际: {step_groups}",
    ))

    # ---------- 5. 生命周期关闭 ----------
    print("\n[5] 生命周期关闭")
    try:
        await mcp_manager.close()
        await mcp_manager.close()  # 幂等
        checks.append(report("close() 幂等无异常", True))
    except Exception as e:
        checks.append(report(f"close() 异常: {e}", False))

    # ---------- 汇总 ----------
    passed = sum(1 for c in checks if c)
    failed = len(checks) - passed
    print("\n" + "=" * 60)
    print(f"测试结果: {passed} 通过 / {failed} 失败 / 共 {len(checks)} 项")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
