# 安装配置指南

本文档详细说明**明策（MingCe）全景投资决策系统**的安装、配置与启动步骤。

---

## 目录

- [前置条件](#前置条件)
- [克隆项目](#克隆项目)
- [项目结构概览](#项目结构概览)
- [环境变量配置](#环境变量配置)
- [依赖安装](#依赖安装)
- [启动步骤](#启动步骤)
- [验证](#验证)
- [Docker 部署](#docker-部署)
- [常见问题](#常见问题)

---

## 前置条件

| 依赖 | 版本要求 | 说明 |
|:-----|:---------|:-----|
| **Python** | ≥ 3.10 | 推荐 3.10–3.12，不支持 3.13+（部分依赖未兼容） |
| **pip** | ≥ 24.0 | 随 Python 安装，建议升级到最新 |
| **飞书应用** | — | 需在 [飞书开放平台](https://open.feishu.cn/app) 创建企业自建应用 |
| **LLM API** | — | 支持 OpenAI 协议的服务，如 [SiliconFlow](https://siliconflow.cn/) |
| **Git** | ≥ 2.30 | 用于克隆项目 |

### 可选依赖

| 组件 | 用途 |
|:-----|:------|
| Docker | 容器化部署 |
| QLib | 量化因子计算与模型预测（Level 1 回退，编译耗时较长） |
| LightGBM | QLib 依赖，需单独安装 |

---

## 克隆项目

```bash
git clone git@github.com:ClayDong/MingCe.git
cd MingCe
```

确认项目根目录结构：

```
MingCe/
├── bot/                        # 日报主系统（FastAPI + APScheduler）
│   ├── app/
│   │   ├── main.py            # FastAPI 应用入口 + 定时任务调度
│   │   └── routers/
│   │       └── v1.py          # API v1 路由
│   ├── config/
│   │   └── settings.py        # pydantic-settings 配置加载
│   ├── core/                   # 数据库 / 缓存 / 数据质量
│   ├── services/               # 数据采集 / 日报生成 / 飞书推送 / LLM 分析
│   ├── models/                 # Pydantic 数据模型
│   ├── tests/                  # 133 个测试用例
│   ├── Dockerfile
│   ├── requirements.txt
│   └── requirements-lock.txt
├── engine/                    # 策略引擎（18 个量化策略）
│   ├── qlib_vnpy_platform/    # QLib 回测与信号生成
│   ├── signal_service.py      # HTTP 微服务
│   ├── run_signal_service.sh
│   └── requirements.txt
├── docs/                      # 文档
├── .env.example               # 环境变量模板
└── README.md                  # 项目总览
```

---

## 环境变量配置

### ⚠️ 重要：.env 文件位置

**`.env` 文件必须放在 `bot/` 目录下**，而不是项目根目录。

这是因为 `bot/config/settings.py` 使用 `pydantic-settings` 加载 `.env`，其默认工作目录是 `bot/`。

```bash
# 正确做法：从模板复制到 bot/ 目录
cp .env.example bot/.env

# 然后编辑 bot/.env
vim bot/.env
```

`.env` 已加入 `.gitignore`，不会提交到版本控制。

### 关键变量说明

#### 🔴 必填项

| 变量 | 说明 | 获取方式 |
|:-----|:------|:---------|
| `FEISHU_APP_ID` | 飞书应用 App ID | 飞书开放平台 → 应用 → 凭证与基础信息 |
| `FEISHU_APP_SECRET` | 飞书应用 App Secret | 同上 |
| `FEISHU_CHAT_ID` | 推送目标群 Chat ID | 飞书群设置 → 更多 → 群二维码 → 查看群信息（`oc_` 开头） |
| `LLM_BASE_URL` | LLM API 地址 | 如 `https://api.siliconflow.cn/v1` |
| `LLM_MODEL` | LLM 模型名 | 如 `Qwen/Qwen3-8B` |
| `LLM_API_KEY` | LLM API 密钥 | 从 LLM 服务商获取 |

#### 🟡 推荐配置

| 变量 | 默认值 | 说明 |
|:-----|:--------|:------|
| `DEBUG` | `false` | 开启后输出更详细的日志 |
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `8000` | 服务端口 |
| `SQLITE_DB_PATH` | `./data/market_daily.db` | 数据库路径（相对于 `bot/`） |
| `CACHE_DIR` | `./data/cache` | 缓存目录 |
| `SIGNAL_SERVICE_URL` | `http://127.0.0.1:8765` | 策略微服务地址 |

#### 🟢 可选配置

| 变量 | 说明 |
|:-----|:------|
| `DEEPSEEK_API_KEY` | DeepSeek 官方密钥，作为 LLM_API_KEY 的回退 |
| `ALERT_WEBHOOK_URL` | 日报生成失败时的飞书 Webhook 告警 |
| `MAKINGMONEY_DIR` | 策略引擎路径，缺省时自动从项目结构推算 |

### 完整 .env 示例

```ini
# ── 调试模式 ──
DEBUG=false

# ── 飞书应用配置（必填） ──
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=your_feishu_app_secret_here
FEISHU_CHAT_ID=oc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ── LLM 分析服务（必填） ──
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=Qwen/Qwen3-8B
LLM_API_KEY=sk-your-api-key-here

# ── 策略引擎路径 ──
MAKINGMONEY_DIR=../engine

# ── 策略微服务地址（可选） ──
SIGNAL_SERVICE_URL=http://127.0.0.1:8765
SIGNAL_SERVICE_TIMEOUT=30

# ── 关键链路告警 Webhook（可选） ──
ALERT_WEBHOOK_URL=

# ── 数据库与缓存 ──
SQLITE_DB_PATH=./data/market_daily.db
CACHE_DIR=./data/cache

# ── 服务端口 ──
HOST=0.0.0.0
PORT=8000
```

---

## 依赖安装

本项目分两个子系统，各自有独立的依赖。

### 方式一：分别安装（推荐）

```bash
# 1. 安装 bot 依赖（日报主系统）
cd bot
pip install -r requirements.txt
cd ..

# 2. 安装 engine 依赖（策略引擎）
cd engine
pip install -r requirements.txt
cd ..
```

### 方式二：一次安装所有依赖

使用合并后的依赖文件（适用于 Docker 构建或全新环境）：

```bash
cd bot
pip install -r requirements-combined.txt
```

### 方式三：使用锁定版本（可复现）

```bash
cd bot
pip install -r requirements-lock.txt
```

### 可选：安装 QLib（Level 1 回退）

QLib 编译耗时较长，仅在需要使用 QLib 完整预测能力时安装：

```bash
pip install pyqlib
# 或从源码安装（Dockerfile 中的方式）
pip install git+https://github.com/microsoft/qlib.git@d5379c520f66a39953bad76234a7019a72796fd0
```

### 安装测试依赖

```bash
cd bot
pip install -r requirements-dev.txt
```

---

## 启动步骤

### 启动方式一：完整启动（策略微服务 + 主系统）

此方式启动策略引擎作为独立 HTTP 微服务，bot 通过 HTTP 调用获取信号。

```bash
# 终端 1：启动策略微服务（端口 8765）
cd engine
bash run_signal_service.sh &

# 终端 2：启动日报主系统（端口 8000）
cd bot
python3 run_server.py
```

### 启动方式二：仅启动主系统（含 subprocess 回退）

不启动策略微服务时，bot 会自动通过 subprocess 调用策略引擎。

```bash
cd bot
python3 run_server.py
```

### 启动方式三：直接启动 uvicorn

```bash
cd bot
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --loop uvloop
```

### 启动方式四：开发模式（热重载）

```bash
cd bot
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 验证

### 1. 健康检查

```bash
curl http://localhost:8000/health
```

预期返回：

```json
{
  "status": "ok",
  "timestamp": "2026-06-16T10:00:00",
  "db": "connected",
  "scheduler": "running",
  "version": "3.0.0"
}
```

### 2. 查看运行指标

```bash
curl http://localhost:8000/api/metrics
```

### 3. 发送测试消息到飞书

```bash
curl -X POST http://localhost:8000/api/report/test
```

### 4. 手动触发日报生成

```bash
# 生成早盘报告
curl -X POST "http://localhost:8000/api/report/generate?version=morning"

# 生成午间复盘
curl -X POST "http://localhost:8000/api/report/generate?version=noon"

# 生成收盘总结
curl -X POST "http://localhost:8000/api/report/generate?version=close"
```

### 5. 运行测试

```bash
cd bot
python3 -m pytest tests/ -v
# 预期: 133 passed
```

### 6. 查看调度任务状态

服务启动后，APScheduler 自动注册以下定时任务：

| 时间 | 任务 | 版本标识 |
|:-----|:------|:---------|
| 08:00 | 隔夜全球简报 | `early` |
| 09:10 | 早盘准备 | `morning` |
| 11:35 | 午间复盘 | `noon` |
| 15:10 | 收盘总结（含策略信号） | `close` |
| 15:35 | 基金监控 | `fund_monitor` |

> 非交易日自动跳过，推送内容标记 🏖️

---

## Docker 部署

### 构建镜像

```bash
cd /path/to/MingCe
docker build -t mingce:latest -f bot/Dockerfile .
```

### 运行容器

```bash
docker run -d --name mingce \
  -p 8000:8000 \
  --env-file bot/.env \
  -v mingce_data:/app/bot/data \
  mingce:latest
```

- `--env-file bot/.env`：加载环境变量（**注意：指向 `bot/.env`**）
- `-v mingce_data:/app/bot/data`：持久化数据库和缓存

### 查看容器日志

```bash
docker logs -f mingce
```

---

## 常见问题

### Q1: 启动时报错 `ModuleNotFoundError: No module named 'xxx'`

**原因**：未安装依赖或虚拟环境未激活。

**解决**：

```bash
cd bot
pip install -r requirements.txt
```

如果使用虚拟环境，确保已激活：

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Q2: `.env` 文件放在哪里？

**必须放在 `bot/` 目录下**（`bot/.env`），而不是项目根目录。

如果误放在根目录，settings.py 无法自动加载。验证方法：

```bash
ls -la bot/.env   # 确认存在
```

### Q3: 启动后健康检查返回 `"status": "degraded"`

**原因**：SQLite 数据库连接失败，通常是目录权限问题。

**解决**：

```bash
# 确保 data 目录存在且可写
cd bot
mkdir -p data data/cache
```

### Q4: 飞书消息推送失败

**检查项**：

1. `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 是否正确
2. 飞书应用是否已发布且有群聊权限
3. 机器人是否已加入目标群聊
4. `FEISHU_CHAT_ID` 是否正确（以 `oc_` 开头）

### Q5: LLM 分析返回空或报错

**检查项**：

1. `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY` 是否正确
2. API Key 是否有余额
3. 网络是否能访问 LLM API 地址（如有代理需要额外配置）

### Q6: 策略信号获取失败

**可能原因**：

1. 策略微服务未启动（`SIGNAL_SERVICE_URL` 配置为 HTTP 模式时）
2. `MAKINGMONEY_DIR` 路径不正确
3. 策略引擎依赖未安装（如 `akshare`、`tushare`）

**排查**：

```bash
# 测试策略引擎是否可直接运行
cd engine
python3 get_strategy_signals.py --symbol SZ002594
```

### Q7: `akshare` 报网络错误

**原因**：akshare 部分数据源需要访问新浪财经等接口，可能受网络限制。

**解决**：确保服务器能访问外网。如使用代理，需在环境变量中配置 `HTTP_PROXY` / `HTTPS_PROXY`。

### Q8: APScheduler 任务未执行

**原因**：时区配置错误。

**解决**：在 `.env` 中设置正确的时区（默认 `Asia/Shanghai`）：

```ini
TZ=Asia/Shanghai
```

### Q9: Docker 构建过程中 QLib 卡住

**原因**：QLib 从 GitHub 源码构建，编译耗时较长（可能 10 分钟以上）。

**解决**：耐心等待，或先注释掉 Dockerfile 中 QLib 的安装行，后续手动安装。

### Q10: 如何查看实时日志？

```bash
# bot 日志
cd bot
tail -f logs/supervisor.log
tail -f logs/uvicorn_*.log

# 策略引擎日志
cd engine
tail -f qlib_vnpy_platform/logs/platform_*.log
```

---

## 参考

- [README.md](../README.md) — 项目总览与快速开始
- [产品文档](./product-overview.md) — 产品功能详述
- [技术文档](./tech-notes.md) — 技术方案与架构细节
- [飞书开放平台](https://open.feishu.cn/app) — 创建飞书应用
- [SiliconFlow](https://siliconflow.cn/) — LLM API 服务商（推荐）
