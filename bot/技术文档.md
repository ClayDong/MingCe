# 明策（MingCe）技术文档

> **项目**：全景投资决策系统  
> **版本**：v3.0  
> **更新**：2026-06-15  
> **技术栈**：Python 3.10+ / FastAPI / APScheduler / QLib / sklearn / SQLite

---

## 一、技术架构总览

### 1.1 系统组件

```
┌──────────────────────────────────────────────────────────────────┐
│                       明策系统 (MingCe)                           │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  market-daily-bot (主系统)              MakingMoney (策略引擎)    │
│  ──────────────────────────             ──────────────────────   │
│  语言: Python 3.10+                     语言: Python 3.12+       │
│  框架: FastAPI + uvicorn                框架: 无 (纯Python)       │
│  调度: APScheduler (async)              调度: launchd + 线程      │
│  DB:   SQLite (aiosqlite)               DB:   JSON文件           │
│  LLM:  SiliconFlow API                  LLM:  LongCat API        │
│  数据: akshare + 新浪                    数据: akshare + yfinance  │
│  飞书: 直接API (tenant_token)            飞书: 中转API(8000)       │
│  守护: Supervisor                       守护: launchd            │
│  端口: 8000                             端口: 无 (CLI)           │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 进程模型

```
                        ┌─────────────────────┐
                        │  Supervisor          │  ← run_server.py
                        │  指数退避自动重启     │
                        └─────────┬───────────┘
                                  │ 子进程
                        ┌─────────▼───────────┐
                        │  uvicorn (worker=1)  │  ← FastAPI应用
                        │  PID: 81xxx          │
                        │  端口: 8000           │
                        └─────────┬───────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
          ▼                       ▼                       ▼
  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
  │ APScheduler  │    │  HTTP API        │    │  WebSocket(预留) │
  │ 6个定时任务   │    │  /api/*          │    │  实时推送        │
  │ async        │    │  /health         │    │                 │
  └──────────────┘    └──────────────────┘    └──────────────────┘
```

---

## 二、API 接口文档

### 2.1 健康检查

```
GET /health

Response:
{
  "status": "ok" | "degraded",
  "timestamp": "2026-06-15T18:00:00",
  "db": "connected" | "disconnected",
  "scheduler": "running" | "stopped",
  "version": "2.0.0"
}
```

### 2.2 手动触发日报

```
GET /api/report?version=close

Parameters:
  version: "early" | "morning" | "noon" | "close"

Response:
{
  "task_id": "...",
  "status": "queued",
  "message": "日报生成任务已提交",
  "version": "close"
}
```

### 2.3 任务状态查询

```
GET /api/task/{task_id}

Response:
{
  "task_id": "...",
  "status": "running" | "completed" | "failed",
  "version": "close",
  "error": null | "error message"
}
```

### 2.4 运行指标

```
GET /api/metrics

Response:
{
  "report_status": {
    "early": {"status": "completed", "created_at": "..."},
    "morning": {"status": "completed", ...},
    "noon": {...},
    "close": {...}
  },
  "today": "2026-06-15",
  "scheduler": {...}
}
```

### 2.5 获取策略信号（单个）

```
GET /api/strategy-signals?symbol=SZ002594

Response:
{
  "success": true,
  "data": {
    "symbol": "SZ002594",
    "stock_name": "比亚迪",
    "date": "2026-06-15",
    "price": 90.81,
    "change_pct": -0.86,
    "total_strategies": 18,
    "buy_count": 0,
    "sell_count": 0,
    "hold_count": 18,
    "buy_signals": [...],
    "sell_signals": [...],
    "hold_signals": [...],
    "consensus": {
      "signal": "HOLD",
      "confidence": 0.50,
      "description": "18个策略一致看平，暂无明确方向"
    }
  }
}
```

### 2.6 批量获取策略信号

```
GET /api/strategy-signals  (所有自选股)
POST /api/strategy-signals/batch  (指定股票列表)

POST body: {"symbols": ["SZ002594", "SH600519"]}

Response:
{
  "success": true,
  "data": [{...同上...}, {...}]
}
```

### 2.7 推送策略信号卡片

```
POST /api/strategy-signals/push?version=close

Response:
{"sent": true, "stocks": 3}
```

### 2.8 飞书消息中转

```
POST /api/send_message
Content-Type: application/json

Body (text):
{"msg_type": "text", "content": "消息内容"}

Body (markdown):
{"msg_type": "markdown", "content": "**加粗** 普通文本"}

Response:
{"sent": true, "msg_type": "text"}
```

---

## 三、定时任务细节

### 3.1 APScheduler 配置

- **调度器**：`AsyncIOScheduler`（异步）
- **时区**：`Asia/Shanghai`
- **错失执行**：`misfire_grace_time=600`（10分钟内补执行）
- **冲突处理**：`replace_existing=True`（重启后覆盖旧任务）

| 任务ID | 时间 | 函数 | 说明 |
|:-------|:-----|:-----|:-----|
| `early_report` | 08:00 cron | `scheduled_report("early")` | 隔夜全球 |
| `morning_report` | 09:10 cron | `scheduled_report("morning")` | 早盘 |
| `noon_report` | 11:35 cron | `scheduled_report("noon")` | 午间 |
| `close_report` | 15:10 cron | `scheduled_report("close")` | 收盘（含策略信号） |
| `fund_monitor` | 15:35 cron | `scheduled_fund_monitor()` | 基金 |

### 3.2 非交易日逻辑

```python
_CHINESE_HOLIDAYS = {
    "2026-01-01",     # 元旦
    "2026-01-28"...   # 春节等
}

def _is_trading_day() -> bool:
    today = date.today().isoformat()
    if today in _CHINESE_HOLIDAYS:
        return False
    return date.today().weekday() in (0, 1, 2, 3, 4)  # 周一至周五
```

非交易日日报自动标记 🏖️，不推送卡片。

### 3.3 launchd 备用调度（MakingMoney）

| 标签 | 时间 | 用于 |
|:-----|:-----|:-----|
| `com.makingmoney.daily_trade_report` | 交易日 16:00 | 策略交易报告 |
| `com.makingmoney.daily_monitor` | 交易日 16:30 | 策略监控 |
| `com.makingmoney.auto_report` | 交易日 17:00 | 全自动日报 |

当前已卸载（功能已合并到 15:10 收盘日报）。如需恢复：`bash ../engine/setup_cron.sh`

---

## 四、数据流详细说明

### 4.1 日报生成流程

```
scheduled_report("close")
    │
    ├── 1. 检查是否交易日
    │      └── 非交易日 → 标记 🏖️ → 结束
    │
    ├── 2. 数据采集 (data_fetcher.py)
    │      ├── 指数行情 (akshare)
    │      ├── 板块轮动 (akshare)
    │      ├── 五维数据 (期货/债/BDI/汇率)
    │      ├── 美股指数 (新浪逐只)
    │      └── 每个数据源有2-4层回退
    │
    ├── 3. 策略信号 (strategy_adapter.py)
    │      └── subprocess → MakingMoney/get_strategy_signals.py
    │          └── MainEngine.analyze_stock() → 27策略信号
    │
    ├── 4. LLM 分析 (llm_service.py)
    │      ├── 构建 LLM prompt（含五维数据+策略信号）
    │      ├── 调用 SiliconFlow API (Qwen3-8B)
    │      ├── 超时 60s → 降级模板
    │      └── 清洗输出（去英文/去思考链）
    │
    ├── 5. 卡片渲染 (feishu_service.py)
    │      └── 构建飞书消息卡片（全中文）
    │
    └── 6. 推送 (feishu_service.py)
           └── POST 飞书 API → tenant_access_token → 群消息
```

### 4.2 策略信号获取流程

```
strategy_adapter.get_signals(["SZ002594"])
    │
    ├── subprocess.run([
    │       "MakingMoney/venv/bin/python",
    │       "MakingMoney/get_strategy_signals.py",
    │       "--symbols", "SZ002594,SH600519,SZ300750"
    │   ], cwd="MakingMoney/")
    │
    ├── MakingMoney 侧：
    │   ├── DataBridge.fetch_stock_daily() → 新浪/腾讯/yfinance
    │   ├── QLibPredictor.predict() → Alpha158因子 → 信号
    │   ├── strategies.py → 27个策略逐只扫描
    │   ├── SignalRouter.fuse_signals() → 加权融合
    │   └── 输出 JSON 到 stdout
    │
    └── adapter 解析 JSON → 注入日报/返回 API
```

### 4.3 飞书通知链路

```
MakingMoney 各脚本
    │
    ├── FeishuOutput.send_message(text)
    │   └── POST http://localhost:8000/api/send_message
    │       ├── msg_type: "markdown"
    │       └── content: 消息文本
    │
    └── market-daily-bot 侧：
        ├── /api/send_message 端点
        ├── feishu_service.send_text_message() / send_card_message()
        ├── 自动获取 tenant_access_token（缓存2小时）
        └── POST 飞书 Open API → 群消息
```

---

## 五、数据源与缓存

### 5.1 数据源优先级

| 数据 | 主数据源 | 备用1 | 备用2 | 备用3 |
|:-----|:---------|:------|:------|:------|
| A股指数 | akshare | — | — | — |
| 板块轮动 | akshare | — | — | — |
| 北向资金 | akshare | — | — | — |
| 黄金/白银 | futures_foreign_hist | — | — | — |
| 原油 | futures_foreign_hist | — | — | — |
| BDI | macro_shipping_bdi | — | — | — |
| 美债利率 | bond_zh_us_rate | — | — | — |
| 美股指数 | 新浪逐只 | — | — | — |
| 个股K线 | 新浪财经 | 腾讯API | yfinance | 缓存 |
| 个股实时 | akshare spot | 新浪 | — | 缓存 |
| 加密货币 | CoinGecko | — | — | — |
| 美国CPI | akshare | — | — | — |
| A股新闻 | akshare news | — | — | — |

### 5.2 缓存策略

| 数据类型 | TTL | 实现 |
|:---------|:----|:-----|
| 市场指数 | 30分钟 | FileCache (JSON) |
| 板块数据 | 30分钟 | FileCache (JSON) |
| 全球宏观 | 60分钟 | FileCache (JSON) |
| 个股K线 | 60分钟 | FileCache (pickle) |
| 宏观经济 | 12小时 | FileCache (JSON) |
| 飞书token | 2小时 | 内存字典 |

### 5.3 数据质量验证

`core/data_quality.py` 实现了 6 个验证类：

| 验证器 | 检测 | 响应 |
|:-------|:-----|:-----|
| `PriceRangeValidator` | 价格超出正常范围 | 标记异常 |
| `VolumeValidator` | 成交量为零或突变 | 标记异常 |
| `MissingDataValidator` | 数据缺失率 > 0.1% | 告警+填充 |
| `StaleDataValidator` | 数据超过5天未更新 | 告警 |
| `PriceJumpValidator` | 单日涨跌 > 20% | 告警 |
| `CrossMarketValidator` | 跨市场数据不一致 | 告警 |

---

## 六、错误处理与降级

### 6.1 数据采集降级

```
data_fetcher.get_market_data()
    │
    ├── try: akshare.stock_zh_index_spot_em()
    │   └── 失败 → logger.warning
    │
    ├── try: 备用新浪 API
    │   └── 失败 → logger.warning
    │
    └── 全部失败 → 使用缓存数据（如果未过期）
         └── 也无缓存 → 返回 "暂无数据"
```

### 6.2 LLM 降级

```
llm_service.generate_commentary()
    │
    ├── try: SiliconFlow API (超时60s)
    │   ├── 成功 → 清洗输出 → 返回
    │   └── 失败 → logger.warning
    │
    ├── try: DeepSeek API 备用（密钥已过期）
    │   └── 失败 → logger.warning
    │
    └── 全部失败 → 结构化数据模板
         └── 不调用LLM，用预定义格式展示数据
```

### 6.3 飞书通知降级

```
feishu_notifier.send_markdown()
    │
    ├── try: 中转API (http://localhost:8000/api/send_message)
    │   └── 成功 → return True
    │
    └── try: lark-cli (本地 Node.js CLI)
        ├── 成功 → return True
        └── 全部失败 → logger.error("All methods failed")
```

### 6.4 策略信号降级

```
QLibPredictor.predict()
    │
    ├── Level 1: QLib (pip install qlib + CN data)
    │   └── 不可用 → Level 2
    │
    ├── Level 2: sklearn (Alpha158因子 + GradientBoosting)
    │   └── 不可用 → Level 3
    │
    └── Level 3: Rule-based (MA交叉 + 布林带 + RSI)
        └── 永远可用（无依赖）
```

---

## 七、代码规范

### 7.1 文件组织

- 每个 Python 文件均有模块 docstring（""" ... """）
- 公共函数均有 Args/Returns 注释
- 日志使用 `loguru` 的 `logger`
- 配置通过 `pydantic-settings` 从 `.env` 读取

### 7.2 命名约定

| 类型 | 约定 | 示例 |
|:-----|:-----|:-----|
| 文件名 | snake_case | `data_fetcher.py` |
| 类名 | PascalCase | `FileCache` |
| 函数名 | snake_case | `generate_daily_report()` |
| 变量名 | snake_case | `trade_data` |
| 常量 | UPPER_CASE | `CACHE_TTL_MARKET` |
| 异步函数 | 以 async 声明 | `async def get_tenant_token()` |

### 7.3 错误处理

- 自定义异常体系：`exceptions.py`（14个异常类）
- 所有外部调用用 try/except 包裹
- 错误不静默：至少 `logger.warning` 记录
- 关键链路降级：LLM→模板 / 数据源→备用 / 飞书→中转→lark-cli

---

## 八、测试

### 8.1 测试概况

| 项目 | 测试数 | 框架 |
|:-----|:-------|:-----|
| market-daily-bot | 133 | pytest |
| MakingMoney core | 12 | pytest |
| 集成测试 | 1 | pytest |

### 8.2 运行测试

```bash
# market-daily-bot
cd .
pytest tests/ -v

# MakingMoney
cd ../engine
source venv/bin/activate
pytest tests/ -v
python3 manage.py test
```

---

## 九、性能数据

| 指标 | 数据 | 说明 |
|:-----|:-----|:------|
| 日报生成时间（无LLM） | ~15秒 | 数据采集+组装 |
| 日报生成时间（含LLM） | ~35-50秒 | 含Qwen3-8B推理 |
| 策略信号扫描（3只） | ~10秒 | 跨venv subprocess开销 |
| 单次数据采集 | ~5-8秒 | 依赖API响应速度 |
| 飞书卡片推送 | <1秒 | tenant_token缓存 |
| 内存占用 | ~150MB | uvicorn单worker |
| 服务器启动时间 | ~3秒 | FastAPI初始化 |

---

## 十、运维手册

### 10.1 日常检查

```bash
# 1. 健康检查
curl http://localhost:8000/health

# 2. 今日报告状态
curl http://localhost:8000/api/metrics

# 3. 策略信号可用性
curl http://localhost:8000/api/strategy-signals

# 4. QLib 模式
python3 -c "from qlib_vnpy_platform.core.qlib_predictor import QLibPredictor; print(QLibPredictor().get_mode_name())"
```

### 10.2 故障恢复

| 症状 | 检查 | 修复 |
|:-----|:-----|:-----|
| 收不到日报 | `curl /health` 是否通，看看日志 | `python3 run_server.py` 重启 |
| 策略信号为空 | `curl /api/strategy-signals` | 检查 MakingMoney venv |
| 定时任务不执行 | 检查 scheduler 日志 | 重启 uvicorn |
| LLM 不输出 | 检查 API Key 是否有效 | 更新 .env |
| 飞书通知失败 | 检查 FEISHU_APP_SECRET | 从飞书开放平台重新获取 |

### 10.3 快速重启

```bash
# 完整重启
kill $(lsof -ti:8000) 2>/dev/null
sleep 2
cd .
python3 run_server.py &

# 验证
sleep 5 && curl http://localhost:8000/health
```
