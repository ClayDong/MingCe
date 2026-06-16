# 部署运维指南

> **版本**: 1.0  
> **更新日期**: 2026-06-16  
> **适用范围**: 明策系统全服务模块

---

## 目录

1. [Docker 部署](#1-docker-部署)
2. [Supervisor 进程管理](#2-supervisor-进程管理)
3. [日志管理](#3-日志管理)
4. [性能优化](#4-性能优化)
5. [监控与告警](#5-监控与告警)
6. [故障恢复](#6-故障恢复)
7. [版本更新策略](#7-版本更新策略)

---

## 1. Docker 部署

### 1.1 多阶段构建

项目采用 **多阶段构建（Multi-stage Build）** 方案，最终镜像仅包含运行所需的最小依赖，显著减小镜像体积。

#### Dockerfile 结构说明

以下为典型的多阶段 Dockerfile 示例：

```dockerfile
# ===== 阶段一：依赖安装 =====
FROM python:3.11-slim AS builder

WORKDIR /app

# 安装系统编译依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 拷贝依赖声明文件
COPY requirements.txt .

# 将 Python 包安装到本地目录，供最终阶段拷贝
RUN pip install --user --no-cache-dir -r requirements.txt

# ===== 阶段二：最终运行镜像 =====
FROM python:3.11-slim

WORKDIR /app

# 仅安装运行时系统依赖（不安装编译工具）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 阶段拷贝已编译的依赖
COPY --from=builder /root/.local /root/.local

# 确保本地 bin 在 PATH 中
ENV PATH=/root/.local/bin:$PATH

# 拷贝应用代码
COPY . .

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["python", "run_server.py"]
```

**构建命令：**

```bash
# 构建镜像
docker build -t mingce-server:latest .

# 查看镜像大小
docker images mingce-server:latest
```

**关键优化点：**

| 优化项 | 说明 |
|--------|------|
| `python:3.11-slim` | 基于 Debian slim 基础镜像，体积约 120MB |
| 分离依赖安装与代码拷贝 | 利用 Docker 层缓存，仅 requirements.txt 变化时才重新安装依赖 |
| `--user` 安装 | 将 Python 包安装到用户目录，便于多阶段拷贝 |
| `HEALTHCHECK` | 容器级健康检查，与 `/health` 端点配合 |

### 1.2 Docker Compose（推荐）

```yaml
# docker-compose.yml
version: '3.8'

services:
  mingce-server:
    build: .
    container_name: mingce-server
    restart: always
    ports:
      - "8000:8000"
    volumes:
      - ./logs:/app/logs
      - ./data:/app/data
      - ./config:/app/config
    environment:
      - TZ=Asia/Shanghai
      - PYTHONUNBUFFERED=1
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "3"
```

**启动命令：**

```bash
# 后台启动
docker compose up -d

# 查看日志
docker compose logs -f

# 重启服务
docker compose restart

# 重新构建并启动
docker compose up -d --build
```

### 1.3 生产环境部署建议

- 使用 **Docker Swarm** 或 **Kubernetes** 管理多副本部署
- 通过反向代理（Nginx / Caddy）对外暴露服务，处理 SSL 终止
- 将配置文件、数据目录通过 volume 挂载到宿主机，避免容器重启丢失数据

---

## 2. Supervisor 进程管理

### 2.1 机制说明

项目使用 `run_server.py` 作为入口脚本，配合 **Supervisor** 实现进程管理，提供以下能力：

- ✅ **自动重启**：进程异常退出后自动拉起
- ✅ **健康检查**：定期探测 `/health` 端点
- ✅ **指数退避**：连续重启失败时，等待时间逐步增加，防止空转

### 2.2 Supervisor 配置

```ini
; /etc/supervisor/conf.d/mingce-server.conf

[program:mingce-server]
command=python /app/run_server.py
directory=/app
user=www-data
autostart=true
autorestart=true
startretries=5
startsecs=10

; 日志配置
stdout_logfile=/var/log/supervisor/mingce-server-stdout.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=5
stderr_logfile=/var/log/supervisor/mingce-server-stderr.log
stderr_logfile_maxbytes=50MB
stderr_logfile_backups=5

; 环境变量
environment=
    PYTHONUNBUFFERED=1,
    TZ=Asia/Shanghai

; 信号处理
stopsignal=INT
stopwaitsecs=30
```

### 2.3 run_server.py 自动重启逻辑

`run_server.py` 内置了 **健康检查 + 指数退避** 逻辑（伪代码示意）：

```python
# run_server.py 核心逻辑

import time
import requests
import subprocess

MAX_RETRIES = 10
BASE_DELAY = 1       # 初始等待 1 秒
MAX_DELAY = 300      # 最大等待 300 秒（5 分钟）
HEALTH_URL = "http://localhost:8000/health"


def start_server():
    """启动 uvicorn 服务进程"""
    return subprocess.Popen([
        "uvicorn", "main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--workers", "4",
        "--log-config", "config/logging.yaml",
    ])


def health_check():
    """健康检查，返回 True 表示服务正常"""
    try:
        resp = requests.get(HEALTH_URL, timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def run_with_backoff():
    """主循环：启动 → 健康检查 → 失败时指数退避重试"""
    retry_count = 0

    while retry_count < MAX_RETRIES:
        process = start_server()
        wait_time = 0

        # 等待进程启动并进入稳定状态
        while True:
            time.sleep(5)

            # 检查进程是否还活着
            if process.poll() is not None:
                # 进程已退出
                retry_count += 1
                delay = min(BASE_DELAY * (2 ** (retry_count - 1)), MAX_DELAY)
                print(f"进程退出 (code={process.returncode}), "
                      f"{delay}s 后重试 (第 {retry_count} 次)")
                time.sleep(delay)
                break

            # 健康检查
            if health_check():
                retry_count = 0  # 正常则重置计数
                wait_time = 0
            else:
                wait_time += 5
                if wait_time >= 30:
                    print("服务无响应超过 30s，重启进程")
                    process.terminate()
                    retry_count += 1
                    delay = min(BASE_DELAY * (2 ** (retry_count - 1)), MAX_DELAY)
                    time.sleep(delay)
                    break

    print("重试次数已达上限，退出")
    sys.exit(1)


if __name__ == "__main__":
    run_with_backoff()
```

**指数退避算法：**

| 重试次数 | 等待时间 |
|----------|----------|
| 1 | 1s |
| 2 | 2s |
| 3 | 4s |
| 4 | 8s |
| 5 | 16s |
| 6 | 32s |
| 7 | 64s |
| 8 | 128s |
| 9+ | 300s（上限） |

### 2.4 Supervisor 管理命令

```bash
# 重新加载配置
sudo supervisorctl reread
sudo supervisorctl update

# 启动 / 停止 / 重启
sudo supervisorctl start mingce-server
sudo supervisorctl stop mingce-server
sudo supervisorctl restart mingce-server

# 查看状态
sudo supervisorctl status mingce-server

# 查看所有进程状态
sudo supervisorctl status
```

---

## 3. 日志管理

### 3.1 Loguru 日志轮转

项目使用 **Loguru** 作为日志框架，支持按文件大小和时间自动轮转。

#### 配置示例

```python
# config/logging_config.py

from loguru import logger
import sys

# 移除默认 handler
logger.remove()

# 控制台输出（INFO 及以上）
logger.add(
    sys.stdout,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
           "<level>{level: <8}</level> | "
           "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
           "<level>{message}</level>",
)

# 文件日志（DEBUG 及以上），按大小轮转
logger.add(
    "logs/mingce-{time:YYYY-MM-DD}.log",
    level="DEBUG",
    rotation="200 MB",       # 每 200MB 轮转一次
    retention="30 days",     # 保留 30 天
    compression="zip",       # 轮转后压缩
    enqueue=True,            # 线程安全队列写日志
    backtrace=True,          # 异常堆栈追踪
    diagnose=True,           # 诊断信息
)

# 错误日志单独输出
logger.add(
    "logs/mingce-error-{time:YYYY-MM-DD}.log",
    level="ERROR",
    rotation="100 MB",
    retention="60 days",
    compression="zip",
)
```

#### 轮转策略建议

| 参数 | 建议值 | 说明 |
|------|--------|------|
| `rotation` | 200 MB | 单个日志文件上限，避免单文件过大 |
| `retention` | 30 天 | 日志保留时长，可按法规要求调整 |
| `compression` | zip | 轮转后自动压缩，节省磁盘空间 |
| `enqueue` | True | 异步写日志，避免阻塞业务逻辑 |

### 3.2 Uvicorn 日志清理策略

Uvicorn 默认会产生大量访问日志，需要单独管理以避免磁盘空间被占满。

#### 方案一：使用 loguru 接管 uvicorn 日志

```python
# main.py 启动时
from loguru import logger
import logging

# 移除所有默认 handler
logging.getLogger("uvicorn").handlers.clear()
logging.getLogger("uvicorn.access").handlers.clear()

# 通过 loguru 的 intercept 机制捕获标准 logging
class InterceptHandler(logging.Handler):
    def emit(self, record):
        logger_opt = logger.opt(depth=6, exception=record.exc_info)
        logger_opt.log(record.levelname, record.getMessage())

logging.getLogger("uvicorn").addHandler(InterceptHandler())
logging.getLogger("uvicorn.access").addHandler(InterceptHandler())
```

#### 方案二：通过 logging 配置文件管理

```yaml
# config/logging.yaml
version: 1
disable_existing_loggers: false

formatters:
  default:
    format: "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

handlers:
  default:
    class: logging.handlers.RotatingFileHandler
    filename: logs/uvicorn.log
    maxBytes: 104857600  # 100 MB
    backupCount: 5
    formatter: default
  access:
    class: logging.handlers.RotatingFileHandler
    filename: logs/uvicorn-access.log
    maxBytes: 104857600  # 100 MB
    backupCount: 3
    formatter: default

loggers:
  uvicorn:
    handlers: [default]
    level: INFO
    propagate: false
  uvicorn.access:
    handlers: [access]
    level: INFO
    propagate: false
```

**建议策略：**

1. 访问日志保留 **3 个备份文件**（约 400 MB 上限）
2. 应用日志保留 **30 天**，按大小轮转
3. 设置 crontab 或 systemd timer 每日清理超期日志

```bash
# crontab 日志清理示例（每日凌晨 3 点执行）
0 3 * * * find /app/logs -name "*.log" -mtime +30 -delete
0 3 * * * find /app/logs -name "*.zip" -mtime +60 -delete
```

---

## 4. 性能优化

### 4.1 uvloop 加速

**uvloop** 是 libuv 的 Python 封装，可替代 asyncio 默认的事件循环，提升异步 I/O 性能。

#### 安装

```bash
pip install uvloop
```

#### 启用方式

```python
# main.py 或 run_server.py 入口处

import uvloop
import asyncio

# 设置 uvloop 为默认事件循环策略
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
```

**性能收益：**

| 场景 | 默认 asyncio | uvloop | 提升比例 |
|------|-------------|--------|----------|
| HTTP 请求（RPS） | ~8,000 | ~15,000 | ~87% |
| TCP 连接处理 | ~12,000 | ~22,000 | ~83% |
| 子进程通信 | ~3,000 | ~4,500 | ~50% |

> 注意：uvloop 仅适用于 Unix/Linux/macOS 平台。Windows 部署需保持默认 asyncio。

### 4.2 缓存 TTL 配置

合理的缓存策略可大幅降低数据库与外部 API 的调用频率。

#### 关键缓存配置项

```python
# config/cache_config.py

CACHE_CONFIG = {
    # 数据字典缓存（部门、ID 映射等）
    "dictionary": {
        "ttl": 3600,           # 1 小时
        "max_size": 500,
    },
    # 外部数据源查询缓存
    "external_query": {
        "ttl": 300,            # 5 分钟
        "max_size": 1000,
    },
    # 用户 Token 缓存
    "auth_token": {
        "ttl": 1800,           # 30 分钟
        "max_size": 10000,
    },
    # 计算结果缓存（报表、统计等）
    "computation": {
        "ttl": 600,            # 10 分钟
        "max_size": 200,
    },
    # 飞书 API 响应缓存
    "feishu_api": {
        "ttl": 60,             # 1 分钟
        "max_size": 500,
    },
}
```

**TTL 调优原则：**

- **高频读、低频写** → TTL 可适当延长（如数据字典）
- **实时性要求高** → TTL 缩短或直接透传（如实时监控数据）
- **外部 API 限流严重** → 适当延长 TTL 减少调用次数

### 4.3 HTTP 微服务替代 subprocess

早期版本部分功能通过 `subprocess` 调用外部脚本实现，性能和可靠性均不理想。建议迁移为 HTTP 微服务架构。

#### 对比

| 方案 | 可靠性 | 性能 | 可观测性 | 维护成本 |
|------|--------|------|----------|----------|
| `subprocess` | 低（进程泄露、僵尸进程） | 低（每次调起新进程） | 低 | 高 |
| HTTP 微服务 | 高（独立生命周期） | 高（长驻进程） | 高（标准指标采集） | 中 |
| 消息队列（Celery/RQ） | 最高 | 高（异步+worker池） | 高 | 中高 |

#### 迁移示例

```python
# ❌ 旧方案：subprocess
import subprocess
result = subprocess.run(
    ["python", "external/report_generator.py", "--id", str(report_id)],
    capture_output=True, text=True, timeout=30
)
data = json.loads(result.stdout)

# ✅ 新方案：HTTP 微服务
import httpx

async def generate_report(report_id: int) -> dict:
    async with httpx.AsyncClient(base_url="http://report-worker:8001") as client:
        resp = await client.get(f"/report/{report_id}", timeout=30)
        resp.raise_for_status()
        return resp.json()
```

**建议分阶段迁移：**

1. 将计算密集型任务独立为 HTTP 微服务
2. 使用 `httpx` 异步客户端保持非阻塞调用
3. 后续可进一步引入 Celery 处理异步任务

---

## 5. 监控与告警

### 5.1 健康检查端点 `/health`

所有服务实例均暴露 `/health` 端点，用于负载均衡器、容器编排平台和监控系统的健康检测。

#### 端点定义

```python
# routers/health.py

from fastapi import APIRouter
from datetime import datetime
import psutil

router = APIRouter()


@router.get("/health")
async def health_check():
    """综合健康检查"""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "checks": {
            "database": await check_database(),
            "feishu_api": await check_feishu_api(),
            "external_sources": await check_external_sources(),
            "cache": await check_cache(),
        },
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_usage_percent": psutil.disk_usage("/").percent,
        },
    }


async def check_database() -> dict:
    """检查数据库连接"""
    try:
        # 执行轻量查询验证连接
        # await db.execute("SELECT 1")
        return {"status": "ok", "latency_ms": 5}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def check_feishu_api() -> dict:
    """检查飞书 API 连通性"""
    try:
        # await feishu_client.ping()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def check_external_sources() -> dict:
    """检查外部数据源状态"""
    # 逐个检查数据源
    return {"status": "ok", "sources": {}}


async def check_cache() -> dict:
    """检查缓存服务"""
    try:
        # await cache.ping()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

#### 监控集成

```bash
# Prometheus 告警规则示例
groups:
  - name: mingce-server
    rules:
      - alert: ServerDown
        expr: probe_success{job="mingce-server"} == 0
        for: 1m
        annotations:
          summary: "明策服务 {{ $labels.instance }} 宕机"

      - alert: HealthCheckFailed
        expr: health_status{job="mingce-server"} != 1
        for: 30s
        annotations:
          summary: "明策服务健康检查不通过"
```

### 5.2 飞书告警（alert_service.py）

项目内置 `alert_service.py`，通过 **飞书 Webhook** 发送告警通知。

#### 配置

```python
# config/alert_config.py

ALERT_CONFIG = {
    "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx",
    "secret": "your-signing-secret",       # 可选，用于签名验证
    "notify_levels": ["ERROR", "CRITICAL"],
    "rate_limit": 60,                       # 同一告警 60 秒内不重复发送
    "mention_all_on_critical": True,        # 严重告警 @所有人
}
```

#### 告警级别定义

| 级别 | 颜色 | 说明 | 示例场景 |
|------|------|------|----------|
| INFO | 蓝 | 通知 | 服务重启、版本更新 |
| WARNING | 黄 | 警告 | 响应时间超阈值、连接数接近上限 |
| ERROR | 橙 | 错误 | 数据库连接失败、飞书 API 调用超限 |
| CRITICAL | 红 | 严重 | 数据源完全不可用、磁盘已满 |

#### 触发方式

```python
# 在代码中触发告警
from services.alert_service import alert_manager

# 发送错误告警
await alert_manager.send_alert(
    level="ERROR",
    title="数据库连接异常",
    message="主数据库连接超时，已切换至只读副本",
    source="db_monitor",
)

# 发送严重告警（自动 @所有人）
await alert_manager.send_alert(
    level="CRITICAL",
    title="数据源完全不可用",
    message="财务数据源连续 5 次健康检查失败",
    source="external_source_monitor",
)
```

#### 飞书消息卡片示例

```json
{
    "msg_type": "interactive",
    "card": {
        "config": { "wide_screen_mode": true },
        "header": {
            "title": { "tag": "plain_text", "content": "🚨 [CRITICAL] 数据源完全不可用" },
            "template": "red"
        },
        "elements": [
            { "tag": "markdown", "content": "**服务**: 明策系统\n**来源**: external_source_monitor\n**时间**: 2026-06-16 14:30:00\n**详情**: 财务数据源连续 5 次健康检查失败" },
            { "tag": "hr" },
            { "tag": "note", "elements": [{ "tag": "plain_text", "content": "请在 15 分钟内处理" }] }
        ]
    }
}
```

### 5.3 数据质量看板

数据质量监控是明策系统的核心运维能力之一，建议构建以下维度的监控看板：

| 指标 | 说明 | 告警阈值 |
|------|------|----------|
| 数据完整率 | 必填字段非空比例 | < 99.5% 告警 |
| 数据及时性 | 数据更新延迟时间 | > 30 分钟告警 |
| 数据一致性 | 跨源数据匹配成功率 | < 98% 告警 |
| 数据源可用性 | 各数据源健康检查通过率 | < 95% 告警 |
| ETL 任务成功率 | 数据管线的成功执行比例 | < 99% 告警 |

**推荐工具：**

- **Prometheus + Grafana**：时序指标采集与可视化
- **自定义数据质量检查脚本**：定时执行并上报结果到飞书

---

## 6. 故障恢复

### 6.1 进程崩溃

**现象**：服务进程突然退出，Supervisor 自动重启。

**自动恢复流程：**

```
进程退出
    ↓
Supervisor 检测到进程终止（exit code ≠ 0）
    ↓
触发 autorestart，重新拉起进程
    ↓
run_server.py 执行内置健康检查
    ↓
┌── 健康检查通过 ──→ 服务恢复正常
└── 健康检查失败 ──→ 指数退避重试
```

**处理步骤：**

```bash
# 1. 查看进程状态
sudo supervisorctl status mingce-server

# 2. 查看退出日志
sudo supervisorctl tail mingce-server stderr

# 3. 查看应用日志定位原因
tail -100 /app/logs/mingce-error-*.log

# 4. 手动重启（如需）
sudo supervisorctl restart mingce-server
```

### 6.2 数据库损坏

**现象**：查询报错、数据不一致、数据库连接失败。

**恢复步骤：**

```bash
# 1. 立即切换至只读副本（如有）
# 数据库连接字符串已在配置中预置

# 2. 备份当前数据库文件
cp /app/data/mingce.db /app/data/mingce.db.bak.$(date +%Y%m%d_%H%M%S)

# 3. 尝试修复
sqlite3 /app/data/mingce.db ".recover" | sqlite3 /app/data/mingce_recovered.db

# 4. 验证修复后的数据完整性
sqlite3 /app/data/mingce_recovered.db "PRAGMA integrity_check;"

# 5. 替换并重启服务
mv /app/data/mingce_recovered.db /app/data/mingce.db
sudo supervisorctl restart mingce-server
```

**预防措施：**

- 主数据库开启 WAL 模式（Write-Ahead Logging）
- 配置定时自动备份（每日全量 + 每小时增量）
- 数据库文件挂载在持久化存储上，避免容器重启导致数据丢失

### 6.3 飞书 Token 过期

**现象**：飞书 API 调用返回 `token expired` 或 `access token invalid`。

**自动恢复流程：**

```python
# services/feishu_client.py — 自动刷新 Token

class FeishuClient:
    def __init__(self):
        self._token = None
        self._token_expires_at = 0
        self._refresh_lock = asyncio.Lock()

    async def _ensure_token(self):
        """确保 Token 有效，自动在过期前 5 分钟刷新"""
        if time.time() < self._token_expires_at - 300:
            return

        async with self._refresh_lock:
            # 双重检查锁
            if time.time() < self._token_expires_at - 300:
                return
            await self._refresh_token()

    async def _refresh_token(self):
        """调用飞书 API 刷新 tenant_access_token"""
        resp = await self._http_client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": APP_ID,
                "app_secret": APP_SECRET,
            },
        )
        data = resp.json()
        self._token = data["tenant_access_token"]
        self._token_expires_at = time.time() + data["expire"]  # expire 单位为秒
        logger.info("飞书 Token 已刷新")

    async def request(self, method, path, **kwargs):
        """统一的 API 请求方法，自动处理 Token 过期"""
        await self._ensure_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._token}"

        resp = await self._http_client.request(method, path, headers=headers, **kwargs)

        # Token 过期，尝试刷新后重试一次
        if resp.status_code == 401:
            data = resp.json()
            if data.get("code") == 99991663:  # token expired
                await self._refresh_token()
                headers["Authorization"] = f"Bearer {self._token}"
                resp = await self._http_client.request(method, path, headers=headers, **kwargs)

        return resp
```

**人工介入步骤：**

```bash
# 1. 检查飞书应用的 Token 配置是否过期
# 在飞书开发者后台查看应用有效期

# 2. 手动触发 Token 刷新（调试用）
curl -X POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal \
  -H "Content-Type: application/json" \
  -d '{"app_id": "YOUR_APP_ID", "app_secret": "YOUR_APP_SECRET"}'

# 3. 重启飞书客户端模块（如需要）
# 无需重启整个服务，仅刷新 Token 即可
```

### 6.4 数据源挂掉

**现象**：外部数据源不可用，数据采集/查询失败。

**分级响应策略：**

| 数据源重要程度 | 操作 | 说明 |
|----------------|------|------|
| 🔴 核心数据源 | 立即告警 + 切换备用源 | 财务数据、核心指标数据 |
| 🟡 重要数据源 | 告警 + 缓存兜底 | 部门组织结构、标签数据 |
| 🟢 一般数据源 | 记录日志 + 跳过 | 辅助参考数据 |

**实现策略：**

```python
# services/external_source.py — 断路器模式

class ExternalSourceCircuitBreaker:
    """断路器模式，防止故障传播"""

    def __init__(self, name: str, failure_threshold: int = 3, recovery_timeout: int = 60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.state = "closed"  # closed / open / half-open
        self.last_failure_time = 0

    async def call(self, func, *args, **kwargs):
        """安全调用外部数据源"""
        if self.state == "open":
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = "half-open"
            else:
                raise CircuitBreakerOpenError(f"数据源 {self.name} 断路器已打开")

        try:
            result = await func(*args, **kwargs)
            if self.state == "half-open":
                self.state = "closed"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
                logger.error(f"数据源 {self.name} 断路器已打开（连续 {self.failure_count} 次失败）")
                # 发送告警
                await alert_manager.send_alert(
                    level="ERROR",
                    title=f"数据源断路器打开",
                    message=f"{self.name} 连续 {self.failure_count} 次调用失败，已熔断",
                )
            raise
```

**手动恢复：**

```bash
# 1. 确认数据源已恢复
curl -I https://external-data-source.example.com/health

# 2. 重置断路器（API 端点）
curl -X POST http://localhost:8000/admin/reset-circuit-breaker?source=finance

# 3. 或重启服务清除状态
sudo supervisorctl restart mingce-server
```

### 6.5 通用故障检查清单

当任意故障发生时，按以下顺序排查：

```
1. 服务是否存活？
   → sudo supervisorctl status mingce-server

2. 磁盘空间是否足够？
   → df -h

3. 内存使用是否正常？
   → free -h

4. CPU 负载是否过高？
   → top -bn1 | head -20

5. 日志中是否有异常信息？
   → tail -100 /app/logs/mingce-error-*.log

6. 外部依赖是否正常？
   → curl http://localhost:8000/health

7. 数据库是否正常？
   → sqlite3 /app/data/mingce.db "PRAGMA integrity_check;"
```

---

## 7. 版本更新策略

### 7.1 蓝绿切换（推荐生产环境）

**原理**：维护两套完全独立的环境（蓝/绿），新版先部署到非活跃环境，测试通过后切换流量。

```
┌─────────────┐      ┌─────────────┐
│   蓝环境     │      │   绿环境     │
│   v1.0.0     │      │   v1.1.0     │
│   (活跃)     │      │   (非活跃)   │
└──────┬───────┘      └──────┬───────┘
       │                    │
       └──────────┬─────────┘
                  │
          ┌───────┴────────┐
          │   负载均衡器     │
          │   (Nginx)       │
          └────────────────┘
```

#### 实施步骤

```bash
# 1. 部署新版本到非活跃环境
docker compose -f docker-compose.green.yml up -d --build

# 2. 执行健康检查
curl http://localhost:8001/health

# 3. 执行冒烟测试
python tests/smoke_test.py --base-url http://localhost:8001

# 4. 切换流量（Nginx 修改 upstream）
# 将默认上游从 blue 改为 green
# nginx -s reload

# 5. 验证新环境
curl http://mingce.example.com/health

# 6. 如有问题，立即回滚
# 将 nginx upstream 切回 blue
# nginx -s reload

# 7. 确认稳定后，回收旧环境
docker compose -f docker-compose.blue.yml down
```

### 7.2 原地升级（适合小型/非关键服务）

直接停止旧版本，启动新版本。配合 Supervisor 实现自动重启。

```bash
# 1. 拉取最新代码
cd /app
git fetch origin
git checkout v1.1.0

# 2. 更新依赖（如有变更）
pip install -r requirements.txt --no-cache-dir

# 3. 重启服务
sudo supervisorctl restart mingce-server

# 4. 验证
curl http://localhost:8000/health
```

### 7.3 版本更新清单

每次版本发布前，请确认以下事项：

| 检查项 | 说明 | 完成 |
|--------|------|------|
| □ 数据库迁移脚本 | Django Alembic / SQL 迁移文件已就绪 | ☐ |
| □ 依赖变更 | requirements.txt / pyproject.toml 已更新 | ☐ |
| □ 配置文件 | 新增配置项已有默认值 | ☐ |
| □ 健康检查 | `/health` 端点覆盖新模块 | ☐ |
| □ 回滚方案 | 明确回滚步骤和版本号 | ☐ |
| □ 告警规则 | 新指标已配置告警阈值 | ☐ |
| □ 飞书通知 | 版本发布前通知相关方 | ☐ |
| □ 数据备份 | 数据库和配置文件已备份 | ☐ |

### 7.4 快速回滚

```bash
# 若使用蓝绿部署
# 切换 nginx upstream 回旧版本
# nginx -s reload

# 若使用原地升级
# 1. 切回上一个 Git 标签
git checkout v1.0.0

# 2. 重启服务
sudo supervisorctl restart mingce-server

# 3. 如需回滚数据库
# 恢复数据库备份
cp /backups/mingce-$(date -d "1 day ago" +%Y%m%d).db /app/data/mingce.db

# 4. 验证
curl http://localhost:8000/health
```

---

## 附录

### A. 环境变量参考

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `TZ` | Asia/Shanghai | 时区 |
| `PYTHONUNBUFFERED` | 1 | Python 日志不缓冲 |
| `UVICORN_PORT` | 8000 | 服务端口 |
| `UVICORN_WORKERS` | 4 | Worker 进程数 |
| `LOG_LEVEL` | INFO | 日志级别 |
| `DATABASE_URL` | sqlite:///data/mingce.db | 数据库连接串 |
| `REDIS_URL` | - | Redis 连接串（可选） |
| `FEISHU_APP_ID` | - | 飞书应用 ID |
| `FEISHU_APP_SECRET` | - | 飞书应用密钥 |
| `ALERT_WEBHOOK_URL` | - | 飞书告警 Webhook |

### B. 常用端口

| 端口 | 用途 | 备注 |
|------|------|------|
| 8000 | 明策 Web 服务 | 主服务端口 |
| 8001 | 非活跃环境（蓝绿部署） | 仅蓝绿部署时启用 |
| 9090 | Prometheus Metrics | 如需采集指标 |
| 6379 | Redis | 可选缓存服务 |

### C. 故障处理快速命令速查

```bash
# 查看服务状态
sudo supervisorctl status mingce-server

# 查看实时日志
tail -f /app/logs/mingce-$(date +%Y-%m-%d).log

# 查看错误日志
tail -100 /app/logs/mingce-error-*.log

# 健康检查
curl http://localhost:8000/health | jq .

# 磁盘空间
df -h /app

# 内存使用
free -h

# 进程资源
top -p $(pgrep -f run_server.py)

# 容器日志（Docker 部署时）
docker logs --tail 100 mingce-server
```
