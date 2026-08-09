# ========== RAG LearnLittle 后端镜像（多阶段构建） ==========
# 构建: docker build -t raglearn-backend .
# 可选预下载重排序模型（约 1GB，需能访问 HuggingFace）:
#   docker build --build-arg PRELOAD_MODELS=true -t raglearn-backend .
# 注意: 国内网络无法访问 HuggingFace 时保持 PRELOAD_MODELS=false（默认），
#   将本地模型缓存目录挂载为卷: -v $HOME/.cache/huggingface:/root/.cache/huggingface

# ---- 阶段 1: 安装 Python 依赖 ----
FROM python:3.12-slim AS builder

WORKDIR /app

# 系统库: libmagic（python-magic）、ffmpeg（视频抽帧）、构建工具（部分 wheel 需编译）
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libmagic1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 使用锁定版本安装（requirements.lock 由 pip freeze 生成，保证可复现）
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock

# 可选: 预下载重排序模型到镜像（HF_HUB_OFFLINE 在运行时由 main.py 强制开启，
# 模型必须在本地缓存中存在；此处构建期联网下载一次）
ARG PRELOAD_MODELS=false
RUN if [ "$PRELOAD_MODELS" = "true" ]; then \
        python -c "from sentence_transformers import CrossEncoder; CrossEncoder('BAAI/bge-reranker-v2-m3')"; \
    fi

# ---- 阶段 2: 运行时镜像 ----
FROM python:3.12-slim AS runtime

WORKDIR /app

# 运行时系统库（不装构建工具，控制镜像体积）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libmagic1 ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    # MCP server 运行时: uvx（mcp-server-fetch）+ npx（tavily-mcp）
    && pip install --no-cache-dir uv \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 阶段复制已安装的依赖与可选模型缓存
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /root/.cache/huggingface /root/.cache/huggingface

# 应用代码（.dockerignore 已排除 .venv/data/logs/front/node_modules）
COPY . .

# 非 root 运行
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data /app/logs /app/media \
    && chown -R appuser:appuser /app
USER appuser

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PORT=8000

EXPOSE 8000

# 健康检查（/health 为存活探针；/ready 为就绪探针，由编排层使用）
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

# 生产启动方式（reload 必须关闭；workers 单进程部署，多 worker 需先改造限流/scheduler）
# 启动前先执行数据库迁移（init_db 内部也会执行，此处提前执行保证迁移在服务暴露前完成）
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000 --no-access-log"]
