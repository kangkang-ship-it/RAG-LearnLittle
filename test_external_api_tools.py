"""
外部 API 工具（DeepL 翻译 / Wolfram Alpha 计算 / Edge TTS 语音）测试脚本

用法: python test_external_api_tools.py

验证内容：
1. 路由/注册表集成：
   - translate/compute/tts 三个工具组从 agent.yaml 正确注册
   - keyword_rules 关键词命中（"翻译成"/"解方程"/"读给我听"）与不命中（普通问候）
   - create_agent_tools 按组解析出对应工具（纯增量，不影响内置工具）
2. 工具调用：
   - translate_text / wolfram_calculate：已配置 API Key 时真实调用；未配置时返回"未配置"降级提示
   - text_to_speech：真实生成 MP3（无需 Key）→ 文件落盘 data/tts/{user_id}/ + 返回下载 JSON
3. TTS 下载端点（HTTP 层，参照 ppt_router 安全模型）：
   - 合法 file_id + 本人 token → 200 audio/mpeg
   - 非法 file_id 格式 → 400；他人 token → 404；无 token → 401
4. 回归：内置工具组解析不受影响

说明：
- text_to_speech 需要联网（微软 Edge TTS 服务）
- DEEPL_API_KEY / WOLFRAM_APP_ID 可留空：走"未配置"降级分支验证
- 测试结束自动清理生成的测试音频（data/tts/test_tts_user/）
"""

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Windows 控制台 UTF-8 输出
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from app.ai_service.agent_runner import resolve_tool_groups
from app.ai_service.agent_tools import create_agent_tools
from app.ai_service.tool_registry import init_tool_registry, tool_registry
from app.utils.auth_utils import create_access_token

TEST_USER = "test_external_api_user"
EXPECTED = {
    "translate": ["translate_text"],
    "compute": ["wolfram_calculate"],
    "tts": ["text_to_speech"],
}


def report(name: str, ok: bool, detail: str = "") -> bool:
    """单条断言输出（✅/❌），返回是否通过"""
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))
    return ok


async def call_tool(tool, args: dict) -> str:
    """调用工具并返回字符串结果"""
    result = await tool.ainvoke(args)
    content = result[0] if isinstance(result, tuple) else result
    return str(content)


async def main() -> int:
    print("=" * 60)
    print("外部 API 工具测试（DeepL / Wolfram Alpha / Edge TTS）")
    print("=" * 60)
    checks = []

    # ---------- 1. 路由/注册表集成 ----------
    print("\n[1] 路由/注册表集成")
    init_tool_registry()
    for group, expected_names in EXPECTED.items():
        names = tool_registry.resolve_names([group])
        checks.append(report(
            f"工具组 '{group}' 注册正确",
            set(names) == set(expected_names),
            f"实际: {names}",
        ))

    cases = [
        ("帮我把这段英文翻译成中文", {"translate"}),
        ("帮我解这个方程 x²+5x+6=0", {"compute"}),
        ("把这篇文章读给我听", {"tts"}),
        ("你好", set()),  # 普通问候：不命中新组
    ]
    for msg, expected_groups in cases:
        groups = resolve_tool_groups(msg) or []
        hit = {g for g in expected_groups if g in groups}
        extra = set(expected_groups) - set(groups)
        checks.append(report(
            f"路由「{msg[:12]}…」",
            hit == expected_groups,
            f"组={groups}，缺={extra or '无'}",
        ))

    # ---------- 2. 工具调用 ----------
    print("\n[2] 工具调用")

    # 2.1 translate_text
    deepl_key = os.getenv("DEEPL_API_KEY", "").strip()
    tools = create_agent_tools(user_id=TEST_USER, groups=["translate"])
    tr = next((t for t in tools if t.name == "translate_text"), None)
    out = await call_tool(tr, {"text": "Hello world, this is a test.", "target_lang": "ZH"})
    if deepl_key:
        ok = "未配置" not in out and len(out) > 5
        checks.append(report("translate_text 真实翻译（已配置 Key）", ok, out[:80]))
    else:
        ok = "未配置" in out
        checks.append(report("translate_text 未配置 Key 时降级提示", ok, out[:80]))

    # 2.2 wolfram_calculate
    wolfram_key = os.getenv("WOLFRAM_APP_ID", "").strip()
    tools = create_agent_tools(user_id=TEST_USER, groups=["compute"])
    wc = next((t for t in tools if t.name == "wolfram_calculate"), None)
    out = await call_tool(wc, {"query": "solve x^2+5x+6=0"})
    if wolfram_key:
        ok = "未配置" not in out and len(out) > 2
        checks.append(report("wolfram_calculate 真实计算（已配置 Key）", ok, out[:80]))
    else:
        ok = "未配置" in out
        checks.append(report("wolfram_calculate 未配置 Key 时降级提示", ok, out[:80]))

    # 2.3 text_to_speech（无需 Key，真实生成）
    tools = create_agent_tools(user_id=TEST_USER, groups=["tts"])
    tts = next((t for t in tools if t.name == "text_to_speech"), None)
    out = await call_tool(tts, {"text": "你好，这是一段测试语音。"})
    file_id = ""
    audio_url = ""
    try:
        meta = json.loads(out)
        file_id = meta.get("file_id", "")
        audio_url = meta.get("audio_url", "")
    except json.JSONDecodeError:
        meta = {}
    audio_path = Path("data/tts") / TEST_USER / f"{file_id}.mp3"
    checks.append(report(
        "text_to_speech 生成 MP3 并落盘",
        bool(file_id) and audio_path.exists() and audio_path.stat().st_size > 0,
        f"{out[:80]}, 文件={audio_path.stat().st_size if audio_path.exists() else 0}B",
    ))
    checks.append(report(
        "audio_url 格式正确",
        audio_url == f"/api/v1/tts/{file_id}",
        audio_url,
    ))

    # ---------- 3. TTS 下载端点（HTTP 层，真实 uvicorn 子进程） ----------
    print("\n[3] TTS 下载端点")
    # TestClient 与 asyncio 事件循环冲突（get_current_user_id 的 Redis 黑名单检查），
    # 改用真实 uvicorn 子进程验证（本机需 Redis 在运行）
    import subprocess
    import time
    import httpx

    port = 8002
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(Path(__file__).resolve().parent),
    )
    my_token = create_access_token(TEST_USER)
    other_token = create_access_token("other_user")
    headers_ok = {"Authorization": f"Bearer {my_token}"}
    try:
        # 等待服务就绪（/health 立即可用，模型后台加载不阻塞）
        ready = False
        for _ in range(40):
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
                if r.status_code == 200:
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(1)
        if not ready:
            checks.append(report("uvicorn 子进程启动", False, "40s 内未就绪"))
        else:
            checks.append(report("uvicorn 子进程启动", True))
            with httpx.Client(timeout=10) as client:
                if file_id:
                    resp = client.get(f"http://127.0.0.1:{port}/api/v1/tts/{file_id}", headers=headers_ok)
                    checks.append(report(
                        "本人 token 下载 → 200 audio/mpeg",
                        resp.status_code == 200 and resp.headers.get("content-type", "").startswith("audio/mpeg"),
                        f"status={resp.status_code}, {len(resp.content)}B",
                    ))
                    resp = client.get(f"http://127.0.0.1:{port}/api/v1/tts/{file_id}", headers={"Authorization": f"Bearer {other_token}"})
                    checks.append(report("他人 token → 404（归属校验）", resp.status_code == 404, f"status={resp.status_code}"))
                    resp = client.get(f"http://127.0.0.1:{port}/api/v1/tts/{file_id}")
                    checks.append(report("无 token → 401", resp.status_code == 401, f"status={resp.status_code}"))
                resp = client.get(f"http://127.0.0.1:{port}/api/v1/tts/not-a-valid-id", headers=headers_ok)
                checks.append(report("非法 file_id → 400（防路径穿越）", resp.status_code == 400, f"status={resp.status_code}"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    # ---------- 4. 回归：内置工具组不受影响 ----------
    print("\n[4] 回归：内置工具组")
    t = create_agent_tools(user_id=TEST_USER, groups=["note_write"])
    checks.append(report(
        "note_write 组解析不变",
        {x.name for x in t} == {"create_note_tool", "update_note_tool"},
        f"实际: {sorted(x.name for x in t)}",
    ))
    t = create_agent_tools(user_id=TEST_USER, groups=["ppt"])
    checks.append(report("ppt 组解析不变", {x.name for x in t} == {"generate_ppt_tool"}, f"实际: {sorted(x.name for x in t)}"))

    # ---------- 清理测试音频 ----------
    shutil.rmtree(Path("data/tts") / TEST_USER, ignore_errors=True)

    # ---------- 汇总 ----------
    passed = sum(1 for c in checks if c)
    failed = len(checks) - passed
    print("\n" + "=" * 60)
    print(f"测试结果: {passed} 通过 / {failed} 失败 / 共 {len(checks)} 项")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
