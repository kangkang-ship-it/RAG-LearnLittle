"""重新上传简历 PDF 并测试 RAG"""
import sys, io, json, os, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests

BASE = "http://127.0.0.1:8000/api/v1"

# 登录
resp = requests.post(f"{BASE}/auth/login", json={"username": "admin", "password": "admin1234"})
token = resp.json()["data"]["access_token"]
headers = {"Authorization": f"Bearer {token}"}
print("登录成功")

# 查找简历 PDF
pdf_candidates = glob.glob(r"C:\Users\HANXI\Desktop\*\*简历*.pdf")
if not pdf_candidates:
    pdf_candidates = glob.glob(r"C:\Users\HANXI\Desktop\**\*简历*.pdf", recursive=True)

if not pdf_candidates:
    print("未找到简历 PDF，请手动通过前端上传")
    sys.exit(1)

pdf_path = pdf_candidates[0]
print(f"找到简历: {pdf_path}")
print(f"文件大小: {os.path.getsize(pdf_path)} bytes")

# 上传
print("\n上传中...")
filename = os.path.basename(pdf_path)
with open(pdf_path, "rb") as f:
    files = {"file": (filename, f, "application/pdf")}
    resp = requests.post(f"{BASE}/knowledge/upload", files=files, headers=headers, stream=True)
    print(f"HTTP 状态: {resp.status_code}")
    
    doc_id = None
    for line in resp.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            data = json.loads(line[6:])
            et = data.get("event_type", "")
            if et == "completed":
                doc_id = data.get("document_id")
                print(f"  完成! doc_id={doc_id}")
            elif et == "processing":
                stage = data.get("stage", "")
                progress = data.get("progress", 0)
                msg = data.get("message", "")
                print(f"  [{progress}%] {stage}: {msg}")
            elif et == "error":
                print(f"  错误: {data.get('message')}")

# 等待向量写入完成
import time
time.sleep(2)

# 测试 RAG 查询
print("\n" + "=" * 60)
print("测试 RAG 查询: '韩玺的简历内容'")
resp = requests.post(f"{BASE}/chat/rag", json={"query": "韩玺的简历内容", "top_k": 3, "use_hyde": False}, headers=headers)
rag_data = resp.json().get("data", {})
print(f"  回答长度: {len(rag_data.get('answer', ''))} 字符")
print(f"  来源数: {len(rag_data.get('sources', []))}")
if rag_data.get("answer"):
    # 检查是否还有乱码
    answer = rag_data["answer"]
    garbage_ratio = sum(1 for c in answer if ord(c) > 0xFFFF or (ord(c) < 32 and c not in '\n\r\t')) / max(len(answer), 1)
    print(f"  乱码比例: {garbage_ratio:.1%}")
    print(f"  回答内容:\n    {answer[:600]}")

# 测试 Agent 对话
print("\n" + "=" * 60)
print("测试 Agent 对话: '韩玺的简历内容'")
resp = requests.post(f"{BASE}/chat/query", json={"message": "韩玺的简历内容"}, headers=headers, stream=True)
full_response = ""
for line in resp.iter_lines(decode_unicode=True):
    if line and line.startswith("data: "):
        evt = json.loads(line[6:])
        t = evt.get("type", "")
        if t == "thinking":
            print(f"  [思考] {evt.get('stage')}: {evt.get('content')}")
        elif t == "response":
            full_response += evt.get("content", "")
        elif t == "done":
            sources = evt.get("sources", [])
            print(f"  来源数: {len(sources)}")

print(f"\n  回答长度: {len(full_response)} 字符")
print(f"  回答内容:\n    {full_response[:600]}")

print("\n测试完成!")
