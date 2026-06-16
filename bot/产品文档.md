# 明策（MingCe）— 全景投资决策系统

> **项目定位**：从"看新闻"到"做决策"的一站式 A 股投资决策系统。  
> **英文名**：MingCe — Clear Strategy  
> **版本**：v3.0 · 2026-06-15  
> **仓库**：`market-daily-bot/`（日报系统）+ `MakingMoney/`（策略引擎）→ 已融合

---

## 一、产品概述

### 1.1 一句话介绍

> 每天 5 条推送，覆盖盘前→盘中→收盘，结合宏观五维分析 + 量化策略信号 + AI 解读，帮你看清市场、做出决策。

### 1.2 核心能力

| 能力 | 说明 | 来源 |
|:-----|:------|:------|
| 🗞️ **多维日报** | 08:00→09:10→11:35→15:10 四个时段，金/油/汇/债/G 五维全覆盖 | market-daily-bot |
| 📈 **策略信号** | 27个量化策略覆盖自选股，给出买卖持有建议及置信度 | MakingMoney |
| 🧠 **AI 解读** | 大师兄经济分析框架，三层传导（宏观→行业→个股），纯中文输出 | LLM (Qwen3-8B) |
| 🛡️ **三级风控** | 单股上限30% / 日亏3%预警5%熔断 / T+1限制 | MakingMoney |
| 🤖 **飞书交互** | @机器人查持仓/信号/自选股，无需打开任何 App | feishu_bot_handler |
| 🔄 **自动调度** | APScheduler + launchd，交易日自动执行，非交易日跳过 | 双系统 |

### 1.3 解决的问题

| 用户痛点 | 明策方案 |
|:---------|:---------|
| 不知道每天市场发生了什么 | 08:00/09:10/11:35/15:10固定推送 |
| 不知道自己的自选股现在该不该动 | 27策略信号注入日报 + @机器人随时查 |
| 看不懂专业财经数据 | LLM 大师兄用大白话解读五维数据 |
| 信息太多无从下手 | 精选 5 条/日，非交易日自动休息 |
| 看了新闻不知道怎么做决策 | 从新闻到信号到建议，一条龙 |

---

## 二、每日推送时间线

| 时间 | 内容 | 形式 | 策略信号 |
|:-----|:------|:-----|:---------|
| **08:00** 🏙️ | **隔夜全球简报**：美股/黄金/原油/汇率/美债/BDI | 五维卡片 | ❌ |
| **09:10** ☀️ | **早盘准备**：A股盘前指数+板块热点+昨日回顾 | 综合卡片 | ✅ 预览 |
| **11:35** 🌤️ | **午间复盘**：上午盘面+板块轮动+异动提醒 | 综合卡片 | ✅ 预览 |
| **15:10** 🏁 | **收盘总结**：全天数据+五维分析+策略信号+AI解读 | 完整卡片 | ✅ **完整** |
| **15:35** 📊 | **基金监控**：基金净值变化跟踪 | 基金卡片 | ❌ |

> 非交易日不推送，自动显示 🏖️ 标记

---

## 三、系统架构

### 3.1 整体架构

```
                        ┌──── 飞书群 ────┐
                        │ 每日推送 · 机器人 │
                        └───────┬───────┘
                                │ 飞书 API
                    ┌───────────▼───────────┐
                    │   market-daily-bot     │  ← 日报主系统
                    │    (port 8000)         │
                    │  FastAPI + APScheduler │
                    └───────┬───────┬───────┘
                            │       │
              ┌─────────────┘       └─────────────┐
              ▼                                    ▼
    ┌──────────────────┐               ┌────────────────────┐
    │   服务层          │               │   MakingMoney      │
    │  ┌────────────┐  │   subprocess  │   策略引擎          │
    │  │ 数据采集    │  │◄─────────────►│  ┌──────────────┐  │
    │  │ data_      │  │     JSON      │  │ QLib预测器   │  │
    │  │ fetcher.py │  │               │  │ 27个策略     │  │
    │  ├────────────┤  │               │  │ 三级风控     │  │
    │  │ LLM分析    │  │               │  │ 模拟交易     │  │
    │  │ llm_       │  │               │  └──────────────┘  │
    │  │ service.py │  │               └────────────────────┘
    │  ├────────────┤  │                       
    │  │ 飞书卡片   │  │               ┌────────────────────┐
    │  │ feishu_   │  │               │  飞书中转API        │
    │  │ service.py │  │  POST /api/   │  MakingMoney →      │
    │  ├────────────┤  │  send_message │  market-daily-bot   │
    │  │ 策略适配器 │  │               └────────────────────┘
    │  │ strategy_ │  │
    │  │ adapter   │  │               ┌────────────────────┐
    │  ├────────────┤  │               │  定时任务调度        │
    │  │ 组合管理   │  │               │  APScheduler(主)    │
    │  │ portfolio_│  │               │  launchd(辅)        │
    │  │ manager   │  │               └────────────────────┘
    │  └────────────┘  │
    └──────────────────┘
```

### 3.2 数据流

```
        定时触发
            │
    ┌───────▼────────┐
    │  数据采集层      │
    │  新浪财经(个股)  │
    │  akshare(指数/   │
    │  宏观/板块)     │
    │  4层数据回退    │
    └───────┬────────┘
            │
    ┌───────▼────────┐
    │  日报组装(五维)  │  ← 金/油/汇/债/G
    └───────┬────────┘
            │
    ┌───────▼────────┐          ┌────────────────┐
    │  LLM 大师兄解读  │←────────│ 策略信号注入    │
    │  (Qwen3-8B)    │          │  MakingMoney    │
    └───────┬────────┘          │  27策略扫描     │
            │                   └────────────────┘
    ┌───────▼────────┐
    │  卡片渲染+推送  │
    │  飞书消息卡片   │
    └───────┬────────┘
            │
    ┌───────▼────────┐
    │   飞书群        │
    └────────────────┘
```

### 3.3 双系统融合方案

| 组件 | 所在项目 | 融合方式 |
|:-----|:---------|:---------|
| **数据采集** | market-daily-bot | 主系统，新浪/akshare |
| **日报生成** | market-daily-bot | 主系统，APScheduler 调度 |
| **LLM 分析** | market-daily-bot | Qwen3-8B via SiliconFlow |
| **飞书通知** | market-daily-bot | tenant_access_token，已调通 |
| **策略信号** | MakingMoney | 跨 venv subprocess（strategy_adapter） |
| **风控** | MakingMoney | 策略内置，不独立推送 |
| **QLib 预测** | MakingMoney | Alpha158因子 + sklearn/GradientBoosting回退 |
| **定时调度** | market-daily-bot | APScheduler 主，launchd 辅 |
| **飞书机器人** | market-daily-bot | @指令查询持仓/信号 |

---

## 四、核心模块详情

### 4.1 数据采集 — `services/data_fetcher.py`

| 维度 | 数据 | 数据源 | 回退 |
|:-----|:-----|:-------|:-----|
| 金 | 黄金/白银 | 期货历史数据 | 新浪 |
| 油 | 布伦特/WTI/国内期货 | 期货历史数据 | 新浪 |
| 汇 | 美元指数/主要汇率 | akshare | 新浪 |
| 债 | 美债收益率/Shibor/LPR | akshare | — |
| G | VIX/BDI/加密货币/北向 | akshare + CoinGecko | — |
| A股指数 | 各大指数行情 | akshare | 新浪 |
| 美股指数 | 标普/道指/纳指 | 新浪逐只获取 | — |
| 自选股K线 | 个股日线 | 新浪财经 API | 腾讯API / yfinance |
| 板块轮动 | 行业板块涨跌 | akshare | — |

### 4.2 LLM 分析 — `services/llm_service.py`

- **模型**：`Qwen/Qwen3-8B`（SiliconFlow API）
- **知识库**：大师兄投资框架（`xhs-economics-analyst/` SKILL.md）
- **分析框架**：
  - 五维矩阵：金→油→汇→债→G 的联动关系
  - 三层传导：宏观事件→行业影响→个股映射
  - 操作建议：仓位方向（加仓/减仓/持有）+ 明确理由
- **超时**：60秒
- **降级**：LLM不可用时自动走结构化数据模板

### 4.3 策略引擎 — MakingMoney

#### 27个策略分类

| 类别 | 策略数 | 代表策略 |
|:-----|:-------|:---------|
| 趋势跟踪 | 6 | MA交叉、MACD、布林带突破、唐奇安通道 |
| 均值回归 | 5 | RSI回归、布林带回归、KDJ超卖 |
| 动量策略 | 4 | 动量因子、OBV能量潮、量价配合 |
| 波动率策略 | 3 | ATR通道、标准差通道、波动率均值回归 |
| 轮动策略 | 3 | 大小盘轮动、板块轮动 |
| 风控策略 | 3 | 最大回撤、波动率控制、尾部风险对冲 |
| 综合策略 | 3 | 多因子融合、信号投票、情绪周期 |

#### QLib 预测器（三级回退）

```
Level 1: QLib (full)     → 需 qlib 包 + CN 数据下载
Level 2: sklearn          → Alpha158因子 + GradientBoosting ← 当前使用
Level 3: Rule-based      → MA交叉 + 布林带 + RSI
```

#### 三级风控

| 级别 | 规则 | 响应 |
|:-----|:-----|:-----|
| 事前 | 单股≤30%、行业集中度≤40% | 下单前拦截 |
| 事中 | 日亏损3%预警、5%熔断 | 预警推送/自动暂停 |
| 事后 | 最大回撤检查、T+1卖出限制 | 限制卖出 |

### 4.4 飞书消息 — `services/feishu_service.py`

- **鉴权**：tenant_access_token（自动刷新）
- **卡片类型**：指数卡 / 五维卡 / 策略信号卡 / ETF卡 / 基金卡 / 异动提醒卡
- **内容**：100% 中文，无英文残留
- **渠道**：中转API（`/api/send_message`）让 MakingMoney 复用

### 4.5 飞书机器人 — `services/feishu_bot_handler.py`

| 指令 | 功能 | 示例 |
|:-----|:------|:-----|
| `关注 <代码>` | 添加自选股 | `关注 600519` |
| `取消关注 <代码>` | 移除自选股 | `取消关注 600519` |
| `持仓 <代码> <数量>` | 记录持仓 | `持仓 300750 100` |
| `移除持仓 <代码>` | 删除持仓 | `移除持仓 300750` |
| `我的组合` | 查看持仓+信号 | `我的组合` |
| `信号 <代码>` | 查看个股信号 | `信号 600519` |
| `帮助` | 显示所有指令 | `帮助` |

---

## 五、部署指南

### 5.1 环境要求

- macOS 12+（launchd 定时任务）
- Python 3.10+（market-daily-bot）/ Python 3.12+（MakingMoney）
- Node.js（lark-cli 备用通道，非必需）
- 依赖安装：

```bash
# market-daily-bot
cd .
pip install -r requirements.txt

# MakingMoney
cd ../engine
source venv/bin/activate
pip install -r requirements.txt
```

### 5.2 启动

```bash
# 方式一：Supervisor（推荐，自动重启）
cd .
python3 run_server.py

# 方式二：直接启动
cd .
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 查看状态
python3 ../engine/manage.py status
```

### 5.3 环境变量（.env）

| 变量 | 说明 | 示例 |
|:-----|:------|:-----|
| `FEISHU_APP_ID` | 飞书应用ID | `cli_a960bd384978dcdd` |
| `FEISHU_APP_SECRET` | 飞书应用密钥 | 飞书开放平台获取 |
| `FEISHU_CHAT_ID` | 推送目标群ID | `oc_599b2776ddd142e49fa2b22aac449c3b` |
| `LLM_BASE_URL` | LLM API地址 | `https://api.siliconflow.cn/v1` |
| `LLM_MODEL` | LLM模型 | `Qwen/Qwen3-8B` |
| `LLM_API_KEY` | LLM API密钥 | SiliconFlow 密钥 |

---

## 六、运维管理

### 6.1 一键管理

```bash
cd ../engine
python3 manage.py status     # 查看系统状态
python3 manage.py test       # 运行测试
python3 manage.py report     # 手动推送日报
python3 manage.py signals    # 手动推送策略信号
```

### 6.2 定时任务管理

```bash
# market-daily-bot (APScheduler，自动运行)
# 已注册：08:00 / 09:10 / 11:35 / 15:10 / 15:35

# MakingMoney (launchd，备用)
launchctl list | grep makingmoney
launchctl start com.makingmoney.daily_trade_report  # 手动触发
bash ../engine/setup_cron.sh # 重装
```

### 6.3 健康检查

```bash
curl http://localhost:8000/health
# 返回: {"status":"ok","scheduler":"running","db":"connected"}
```

### 6.4 日志

| 日志 | 路径 | 说明 |
|:-----|:-----|:------|
| Supervisor | `logs/supervisor.log` | 进程守护日志 |
| uvicorn | `logs/uvicorn_*.log` | HTTP请求+应用日志 |
| cron(MakingMoney) | `logs/cron_*.log` | launchd定时任务日志 |

### 6.5 已知限制

| 限制 | 影响 | 状态 |
|:-----|:-----|:------|
| DeepSeek 官方密钥过期 | 使用 SiliconFlow Qwen3-8B 回退 | ⚠️ 待恢复 |
| 东方财富全线封锁 | 美股/北向/VIX/美元指数数据缺失 | ⚠️ 暂无替代 |
| QLib 未安装（网络超时） | 使用 sklearn 回退（精度略低） | ⚠️ 可手动安装 |
| VNPY 未安装（C编译超时） | TradingEngine 内存模拟 | ⚠️ 可手动安装 |
| FEISHU_APP_SECRET 被脱敏 | .env中密钥占位符，需手动补回 | ⚠️ 需用户操作 |

---

## 七、项目文件结构

### 7.1 主系统：market-daily-bot

```
market-daily-bot/
├── app/
│   └── main.py                          # FastAPI + APScheduler (655行)
├── config/
│   └── settings.py                      # Pydantic配置
├── core/
│   ├── cache.py                         # 文件缓存
│   ├── data_quality.py                  # 数据质量验证
│   ├── database.py                      # SQLite
│   └── utils.py                         # 工具函数
├── models/
│   └── schemas.py                       # 数据模型
├── services/
│   ├── data_fetcher.py                  # 数据采集 (53函数)
│   ├── decision_engine.py               # 决策引擎
│   ├── feishu_bot_handler.py            # 飞书机器人
│   ├── feishu_service.py                # 飞书消息卡片 (26函数)
│   ├── fund_monitor.py                  # 基金监控
│   ├── llm_service.py                   # LLM大师兄分析
│   ├── portfolio_manager.py             # 组合管理
│   ├── report_generator.py              # 日报生成
│   └── strategy_adapter.py              # 🆕 策略信号适配器
├── data/                                # SQLite + 缓存
├── logs/                                # 日志
├── tests/                               # 单元测试
├── .env                                 # 环境变量
├── run_server.py                        # Supervisor启动
└── 产品文档.md                           # ← 当前文档
```

### 7.2 策略引擎：MakingMoney

```
MakingMoney/
├── qlib_vnpy_platform/
│   ├── config/
│   │   ├── __init__.py                  # 配置加载器
│   │   └── settings.yaml                # 主配置 (134行)
│   └── core/
│       ├── main_engine.py               # 主引擎 (714行)
│       ├── data_bridge.py               # 数据桥接 (4层回退)
│       ├── strategies.py                # 27个策略 (1647行)
│       ├── signal_router.py             # 信号融合
│       ├── risk_manager.py              # 三级风控 (239行)
│       ├── qlib_predictor.py            # 🆕 QLib预测器
│       ├── feishu_notifier.py           # 飞书通知 (中转API)
│       ├── scheduler.py                 # 调度器 (线程)
│       ├── llm_analyzer.py              # LLM分析
│       ├── backtest.py                  # 回测引擎
│       ├── strategy_monitor_pkg/        # 🆕 监控模块 (重构)
│       │   ├── base_monitor.py
│       │   ├── report_formatter.py
│       │   ├── feishu_output.py
│       │   └── console_output.py
│       └── ... (19个核心文件)
├── get_strategy_signals.py              # 🆕 策略信号CLI入口
├── manage.py                            # 🆕 一键管理
├── setup_cron.sh                        # 🆕 launchd安装
├── run_*.sh                             # Shell入口脚本
├── feishu_config.json                   # 飞书配置
└── .env                                 # 环境变量
```

---

## 八、版本历史

| 版本 | 日期 | 变更 |
|:-----|:-----|:------|
| v1.0 | 2026-05 | News 原始版，东方财富数据源 |
| v1.5 | 2026-06初 | 数据源切换新浪+腾讯，全中文化 |
| v2.0 | 2026-06中 | News+MakingMoney 融合，飞书机器人，29策略 |
| **v3.0** | **2026-06-15** | **明策发布**：QLib预测器(三级回退) / 双系统整合 / 开盘策略信号 / 代码重构 / launchd调度 / 管理工具 |
