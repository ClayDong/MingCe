# ────────────────────────────────────────────────────────────
# 明策 (MingCe) — 全景投资决策系统 Dockerfile
# 基于 python:3.10-slim，合并两个子项目到一个容器
#   - market-daily-bot/  (主系统 / FastAPI + uvicorn)
#   - MakingMoney/      (策略引擎 / Flask + QLib)
#
# 构建（从 workspace/ 作为 build context）:
#   cd /Users/dong/workspace
#   docker build -t mingce:latest -f news/market-daily-bot/Dockerfile .
#
# 运行:
#   docker run -d --name mingce \
#     -p 8000:8000 \
#     -v mingce_data:/app/data \
#     -e DEEPSEEK_API_KEY=*** \
#     -e FEISHU_APP_ID=xxx \
#     -e FEISHU_APP_SECRET=*** \
#     -e FEISHU_CHAT_ID=xxx \
#     mingce:latest
# ────────────────────────────────────────────────────────────

FROM python:3.10-slim AS builder

LABEL maintainer="MingCe Team"
LABEL description="明策 (MingCe) — 全景投资决策系统"
LABEL version="3.0.0"

# 安装编译依赖（pyqlib/lightgbm 需要 gcc）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# ── 复制依赖清单 ──────────────────────────────────────
COPY news/market-daily-bot/requirements-combined.txt \
     news/market-daily-bot/requirements-lock.txt ./

# ── 安装 Python 依赖 ──────────────────────────────────
# 先用 lock 文件安装（精确版本），再补 pyqlib
RUN pip install --no-cache-dir -r requirements-lock.txt && \
    pip install --no-cache-dir "pyqlib @ git+https://github.com/microsoft/qlib.git@d5379c520f66a39953bad76234a7019a72796fd0" && \
    pip install --no-cache-dir lightgbm>=4.0

# ── 第二阶段：精简运行镜像 ────────────────────────────
FROM python:3.10-slim AS runtime

LABEL maintainer="MingCe Team"
LABEL description="明策 (MingCe) — 全景投资决策系统"
LABEL version="3.0.0"

# 运行时需要 git（pyqlib 可能在启动时检查）
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 从 builder 复制已安装的 site-packages
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# ── 复制项目代码 ──────────────────────────────────────
# 主系统 → /app
COPY news/market-daily-bot/ ./

# 策略引擎 → /app/MakingMoney/
# strategy_adapter.py 通过 MAKINGMONEY_DIR 环境变量定位
COPY MakingMoney/ /app/MakingMoney/

# ── 环境变量 ──────────────────────────────────────────
# 让 strategy_adapter.py 通过环境变量而非硬编码路径找到 MakingMoney
ENV MAKINGMONEY_DIR=/app/MakingMoney
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

# 创建必要的运行时目录
RUN mkdir -p /app/data /app/logs

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" || exit 1

# 启动 supervisor（自动管理 uvicorn 进程）
CMD ["python", "run_server.py"]
