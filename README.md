<div align="center">

# 明策（MingCe）— 全景投资决策系统

**从看新闻到做决策 · 每天 5 条推送 · 飞书智能助手**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.137%2B-009688)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](https://github.com/ClayDong/MingCe/pulls)

</div>

---

## 📋 项目简介

**明策（MingCe）** 是一个面向 A 股投资者的全景投资决策系统。它将**宏观五维分析**、**量化策略信号**和 **LLM 大师兄解读**融合到飞书群聊中，每天 4 个时段自动推送，解决散户「信息过载」和「决策困难」的核心痛点。

### 核心能力

| 能力 | 说明 |
|:-----|:------|
| 🗞️ **多维日报** | 08:00→09:10→11:35→15:10 四个时段，金/油/汇/债/G 五维全覆盖 |
| 📈 **策略信号** | 18 个量化策略，覆盖趋势/均值回归/动量/波动率/轮动/情绪等 |
| 🧠 **AI 解读** | LLM 基于大师兄经济分析框架，三层传导（宏观→行业→个股） |
| 🛡️ **三级风控** | 单股上限30% / 日亏3%预警5%熔断 / T+1限制 |
| 🤖 **飞书交互** | @机器人查持仓/信号/自选股，无需打开 App |
| 🔄 **自动调度** | APScheduler，交易日自动执行，非交易日跳过 |

### 解决问题

| 用户痛点 | 明策方案 |
|:---------|:---------|
| 不知道每天市场发生了什么 | 08:00/09:10/11:35/15:10 固定推送 |
| 不知道自选股该不该操作 | 18 策略信号 + @机器人随时查询 |
| 看不懂专业财经数据 | LLM 大师兄用大白话解读五维数据 |
| 信息太多无从下手 | 精选 5 条/日，非交易日自动休息 |

---

## 🏛️ 系统架构

```
                      ┌──── 飞书群 ────┐
                      │ 每日推送 · 机器人 │
                      └───────┬───────┘
                              │ 飞书 API
                  ┌───────────▼───────────┐
                  │        bot/            │  ← 日报主系统
                  │  FastAPI + APScheduler │
                  │  Port 8000             │
                  └───────┬───────┬───────┘
                          │       │
            ┌─────────────┘       └─────────────┐
            ▼                                    ▼
  ┌──────────────────┐               ┌────────────────────┐
  │   数据采集层       │  HTTP/        │     engine/         │
  │   新浪 / akshare   │  subprocess   │     策略引擎         │
  │   4 层数据回退     │◄────────────►│  QLib三级回退       │
  │   数据质量监控     │               │  18个量化策略       │
  └──────────────────┘               │  三级风控           │
                                      └────────────────────┘
```

### 双系统说明

- **`bot/`** — 日报主系统：FastAPI + APScheduler，负责数据采集、日报生成、飞书推送、LLM 分析
- **`engine/`** — 策略引擎：18 个量化策略 + QLib 三级回退预测器 + 模拟交易

---

## 🚀 快速开始

### 前置条件

- Python 3.10+
- 飞书应用（[创建指南](https://open.feishu.cn/app)）
- LLM API（支持 OpenAI 协议，如 [SiliconFlow](https://siliconflow.cn/)）

### 安装

```bash
# 1. 克隆项目
git clone git@github.com:ClayDong/MingCe.git
cd MingCe

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填写飞书 App ID/Secret、LLM API Key 等

# 3. 安装依赖
# bot（主系统）
cd bot && pip install -r requirements.txt && cd ..

# engine（策略引擎）
cd engine && pip install -r requirements.txt && cd ..
```

### 启动

```bash
# 方式一：启动策略微服务 + 主系统
cd engine && bash run_signal_service.sh &    # 策略服务 :8765
cd bot && python3 run_server.py              # 主系统 :8000

# 方式二：直接启动（含 subprocess 回退）
cd bot && python3 run_server.py

# 验证
curl http://localhost:8000/health
```

---

## 📅 推送时间线

| 时间 | 内容 | 策略信号 |
|:-----|:------|:---------|
| **08:00** 🏙️ | 隔夜全球简报：美股/黄金/原油/汇率/美债/BDI | ❌ |
| **09:10** ☀️ | 早盘准备：A股盘前+板块热点+昨日回顾 | ✅ 预览 |
| **11:35** 🌤️ | 午间复盘：上午盘面+板块轮动+异动提醒 | ✅ 预览 |
| **15:10** 🏁 | 收盘总结：全天数据+五维分析+策略信号+AI解读 | ✅ 完整 |
| **15:35** 📊 | 基金监控：基金净值变化跟踪 | ❌ |

> 非交易日不推送，自动标记 🏖️

---

## 🤖 飞书指令

在飞书群 @机器人 发送以下指令：

| 指令 | 功能 | 示例 |
|:-----|:------|:------|
| `关注 <代码>` | 添加自选股 | `关注 600519` |
| `取消关注 <代码>` | 移除自选股 | `取消关注 600519` |
| `持仓 <代码> <数量>` | 记录持仓 | `持仓 300750 100` |
| `移除持仓 <代码>` | 删除持仓 | `移除持仓 300750` |
| `我的组合` | 查看持仓+信号 | `我的组合` |
| `信号 <代码>` | 查看个股信号 | `信号 600519` |
| `帮助` | 显示所有指令 | `帮助` |

---

## 🗂️ 项目结构

```
MingCe/
├── bot/                        # 日报主系统
│   ├── app/
│   │   ├── main.py            # FastAPI 应用入口 + 定时任务
│   │   └── routers/
│   │       └── v1.py          # API v1 路由
│   ├── config/
│   │   └── settings.py        # pydantic-settings 配置
│   ├── core/
│   │   ├── database.py        # SQLite 异步数据库
│   │   ├── cache.py           # 文件缓存
│   │   └── data_quality.py    # 数据质量验证
│   ├── services/
│   │   ├── data_fetcher.py    # 数据采集（1855行）
│   │   ├── report_generator.py# 日报生成
│   │   ├── feishu_service.py  # 飞书卡片推送
│   │   ├── llm_service.py     # LLM 分析
│   │   ├── strategy_adapter.py# 策略信号适配器
│   │   ├── alert_service.py   # 告警服务
│   │   └── decision_engine.py # 决策引擎
│   ├── models/
│   │   └── schemas.py         # Pydantic 数据模型
│   ├── tests/                 # 133 个测试用例
│   ├── Dockerfile
│   ├── requirements.txt
│   └── requirements-lock.txt
├── engine/                    # 策略引擎
│   ├── qlib_vnpy_platform/
│   │   └── core/
│   │       ├── strategies.py           # 29 个策略（原始）
│   │       ├── strategies_optimized.py # 18 个核心策略（优化版）
│   │       ├── main_engine.py          # 主引擎
│   │       ├── signal_router.py        # 信号融合
│   │       ├── risk_manager.py         # 三级风控
│   │       ├── backtest.py             # 回测引擎
│   │       └── regime_detector.py      # 市场状态识别
│   ├── signal_service.py     # HTTP 微服务
│   ├── get_strategy_signals.py# CLI 入口
│   ├── run_signal_service.sh
│   └── requirements.txt
├── docs/
│   ├── 产品文档.md
│   └── 技术文档.md
├── .env.example              # 环境变量模板
├── .gitignore
└── README.md
```

---

## 📊 量化策略

18 个核心策略，覆盖 6 大类别：

| 类别 | 策略 | 说明 |
|:-----|:-----|:------|
| **趋势跟踪** | MA交叉、MACD、布林带突破、SAR抛物线 | 捕捉趋势行情 |
| **均值回归** | RSI超买超卖、KDJ、均值回归、MFI资金流 | 震荡市高抛低吸 |
| **动量** | 动量策略、VWAP、OBV能量潮 | 跟随资金流向 |
| **突破** | 双轨突破(Dual Thrust)、海龟交易、支撑阻力 | 突破确认入场 |
| **轮动/情绪** | 行业轮动、情绪周期、龙头战法 | 板块轮动+游资 |
| **主动交易** | 波段操作、价值投资 | 中长期配置 |

### QLib 三级回退

```
Level 1: QLib (full)     → 需 qlib 包 + CN 数据下载
Level 2: sklearn          → Alpha158因子 + GradientBoosting ← 默认
Level 3: Rule-based      → MA交叉 + 布林带 + RSI
```

---

## 🧪 测试

```bash
cd bot
python3 -m pytest tests/ -v
# 133 passed
```

---

## 🐳 Docker 部署

```bash
# 构建
cd /path/to/MingCe
docker build -t mingce:latest -f bot/Dockerfile .

# 运行
docker run -d --name mingce \
  -p 8000:8000 \
  --env-file bot/.env \
  mingce:latest
```

---

## 📝 环境变量

参见 `.env.example`，关键变量：

| 变量 | 必填 | 说明 |
|:-----|:----:|:------|
| `FEISHU_APP_ID` | ✅ | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | ✅ | 飞书应用 App Secret |
| `FEISHU_CHAT_ID` | ✅ | 推送目标群 Chat ID |
| `LLM_BASE_URL` | ✅ | LLM API 地址 |
| `LLM_MODEL` | ✅ | LLM 模型名 |
| `LLM_API_KEY` | ✅ | LLM API 密钥 |
| `MAKINGMONEY_DIR` | ❌ | 策略引擎路径，缺省自动推算 |

---

## 🤝 贡献指南

欢迎提交 Issue 和 PR！

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/amazing`)
3. 提交修改 (`git commit -m 'feat: add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing`)
5. 提交 Pull Request

---

## 📄 许可证

MIT License

---

### 项目名称说明

**明策（MingCe）** = 明智的决策。愿景是让每位投资者都能获得清晰、及时、有依据的市场判断。
