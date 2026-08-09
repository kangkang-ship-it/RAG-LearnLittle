# -*- coding: utf-8 -*-
"""复现：深度思考 + 附件 → 超时？三组对照计时"""
import asyncio, json, time, io, os
from PIL import Image

BASE = "http://127.0.0.1:8000/api/v1"

async def main():
    import httpx
    async with httpx.AsyncClient(timeout=180) as client:
        # 登录
        r = await client.post(f"{BASE}/auth/login", json={"username": "admin", "password": "admin1234", "device_id": "repro", "device_name": "repro"})
        token = r.json()["data"]["access_token"]
        H = {"Authorization": f"Bearer {token}"}

        # 生成测试图（大一点，接近真实场景：1600x1200 渐变图）
        img = Image.new("RGB", (1600, 1200))
        px = img.load()
        for x in range(1600):
            for y in range(1200):
                px[x, y] = (x % 256, y % 256, (x+y) % 256)
        buf = io.BytesIO(); img.save(buf, format="JPEG", quality=92)
        files = {"file": ("gradient.jpg", buf.getvalue(), "image/jpeg")}
        r = await client.post(f"{BASE}/chat/files", headers=H, files=files)
        fid = r.json()["data"]["file_id"]
        print(f"上传: {fid[:8]} ({buf.tell()//1024}KB)")

        # 三组测试
        cases = [
            ("A: 带图 + 深度思考", {"message": "描述这张图片", "attachment_ids": [fid], "enable_thinking": True}),
            ("B: 带图 + 普通",       {"message": "描述这张图片", "attachment_ids": [fid], "enable_thinking": False}),
            ("C: 无图 + 深度思考",   {"message": "介绍一下你自己", "enable_thinking": True}),
        ]
        for label, body in cases:
            t0 = time.time()
            r = await client.post(f"{BASE}/chat/query", headers=H, json=body)
            t_http = time.time() - t0
            content = r.text
            # 解析事件
            events = [json.loads(l[6:]) for l in content.splitlines() if l.startswith("data: ")]
            errors = [e for e in events if e.get("type") == "error"]
            resp_len = sum(len(e.get("content","")) for e in events if e.get("type") == "response")
            t_total = time.time() - t0
            status = "ERROR" if errors else "OK"
            print(f"{label}: 总耗时={t_total:.1f}s HTTP={t_http:.1f}s response字长={resp_len} 事件数={len(events)} -> {status}")
            if errors:
                print(f"   error: {errors[0].get('content','')[:100]}")
            # 检查是否超时
            if any("超时" in e.get("content","") for e in errors):
                print(f"   !! 超时确认")
            await asyncio.sleep(2)  # 间隔

asyncio.run(main())
