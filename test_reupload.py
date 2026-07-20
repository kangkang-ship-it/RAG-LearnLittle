"""删除旧文档并重新上传 PDF"""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests

BASE = "http://127.0.0.1:8000/api/v1"

# 登录
resp = requests.post(f"{BASE}/auth/login", json={"username": "admin", "password": "admin1234"})
token = resp.json()["data"]["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# 删除旧文档 (ID=5 是韩玺的简历.pdf)
print("删除旧文档 ID=5...")
resp = requests.delete(f"{BASE}/knowledge/documents/5", headers=headers)
print(f"  状态: {resp.status_code} - {resp.json()}")

# 也删除 ID=1,2 (chunks=0 的旧测试文档)
for doc_id in [1, 2]:
    resp = requests.delete(f"{BASE}/knowledge/documents/{doc_id}", headers=headers)
    print(f"  删除 ID={doc_id}: {resp.status_code}")

# 重新上传 PDF
print("\n重新上传 韩玺的简历.pdf...")
pdf_path = "data/uploads/ea475f05-dfbd-4815-819b-73ea582f78f3"
import os
# 找到实际文件
for f in os.listdir(pdf_path):
    if "简历" in f or "resume" in f.lower():
        filepath = os.path.join(pdf_path, f)
        print(f"  找到文件: {filepath}")
        with open(filepath, "rb") as fh:
            files = {"file": (f, fh, "application/pdf")}
            resp = requests.post(f"{BASE}/knowledge/upload", files=files, headers=headers, stream=True)
            print(f"  上传状态: {resp.status_code}")
            for line in resp.iter_lines(decode_unicode=True):
                if line and line.startswith("data: "):
                    data = json.loads(line[6:])
                    et = data.get("event_type", "")
                    if et == "completed":
                        print(f"  完成! doc_id={data.get('document_id')}, msg={data.get('message')}")
                    elif et == "processing":
                        print(f"  进度: {data.get('progress')}% - {data.get('stage')}")
                    elif et == "error":
                        print(f"  错误: {data.get('message')}")
        break
else:
    print("  未找到简历 PDF 文件，请手动上传")

print("\n完成!")
