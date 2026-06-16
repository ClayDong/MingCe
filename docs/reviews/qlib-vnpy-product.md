# QLib + VNPY 量化交易整合平台 — 产品文档

> 版本：v2.0 | 更新日期：2026-05-22

---

## 一、产品概述

### 1.1 产品定位

QLib + VNPY 量化交易整合平台是一套面向 A 股市场的**多策略量化交易系统**，核心能力包括：

- **29 种技术分析策略**：覆盖趋势跟踪、均值回归、动量突破、形态识别、舆情分析等主流量化方法论
- **模拟交易（Paper Trading）**：每策略独立 10 万元资金池，从当下时间节点开始，严格按策略信号执行
- **历史回测**：含样本外检验、参数敏感性分析、过拟合风险评估
- **LLM + QLib 双引擎信号融合**：大语言模型舆情分析与机器学习模型预测加权融合
- **全链路风控**：单股持仓上限、行业集中度限制、日亏损熔断、T+1 限制
- **市场状态识别**：自动检测趋势/震荡/高波动/中性市场，动态推荐适配策略

### 1.2 核心原则

| 原则 | 说明 |
|------|------|
| 独立资金池 | 每个策略拥有独立的 10 万元初始资金，互不干扰 |
| 严格信号执行 | 买入/卖出完全由策略信号驱动，不受情绪干扰 |
| 交易成本真实 | 佣金 0.03%、印花税 0.05%（卖出）、滑点 0.1% |
| 从当下开始 | 模拟交易从当前时间节点起步，不使用历史数据填充 |

---

## 二、系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        用户入口层                            │
│  run.py (CLI) │ daily_strategy_monitor.py │ feishu_bot      │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│                      核心引擎层                              │
│  MainEngine ── Scheduler ── StrategyMonitor                 │
│      │            │              │                          │
│      ▼            ▼              ▼                          │
│  TradingEngine  定时扫描     策略扫描+日报                    │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│                      信号决策层                              │
│  SignalRouter ── RiskManager ── QLibModel                   │
│  (信号融合)      (风控拦截)     (ML预测)                     │
│       │               │                                      │
│       ▼               ▼                                      │
│  LLManalyzer    NewsFetcher                                  │
│  (LLM分析)       (新闻获取)                                   │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│                      策略执行层                              │
│  PaperTradingEngine ── BacktestEngine ── StrategySimulator  │
│  (模拟交易)            (历史回测)        (策略模拟)           │
│       │                    │                │                │
│       ▼                    ▼                ▼                │
│  29种策略 (strategies.py)                                   │
│  + MarketRegimeDetector (市场状态识别)                       │
│  + StrategySelector (策略选择器)                             │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│                      数据服务层                              │
│  DataBridge (AKShare主 / Tushare备)                         │
│  SentimentAnalyzer ── ImpactAnalyzer                        │
│  缓存层 (Parquet + JSON)                                    │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 模块依赖关系

```
MainEngine
  ├── DataBridge          # 数据获取与缓存
  ├── NewsFetcher         # 新闻资讯获取
  ├── LLManalyzer         # LLM 分析引擎
  ├── SignalRouter        # 信号融合路由
  ├── RiskManager         # 风控管理
  ├── TradingEngine       # 交易执行引擎
  ├── QLibModel           # QLib 机器学习模型
  ├── Scheduler           # 定时任务调度
  └── StrategyMonitor     # 策略监控与报告

PaperTradingEngine        # 独立模拟交易引擎
  ├── DataBridge
  └── 29种策略 (STRATEGY_REGISTRY)

BacktestEngine            # 独立回测引擎
  └── 29种策略

StrategySimulator         # 独立策略模拟器
  ├── DataBridge
  └── 29种策略
```

---

## 三、核心模块详解

### 3.1 策略体系（29 种）

#### 3.1.1 技术指标策略（17 种）

| 策略 Key | 名称 | 核心逻辑 | 适用市场 |
|----------|------|----------|----------|
| `ma_cross` | 均线交叉 | MA5 上穿 MA20 买入，下穿卖出 | 趋势市场 |
| `macd` | MACD 金叉死叉 | MACD 柱状图由负转正买入，由正转负卖出 | 趋势市场 |
| `rsi` | RSI 超买超卖 | RSI 低于 30 买入，高于 70 卖出 | 震荡市场 |
| `bollinger` | 布林带突破 | 触及下轨买入，触及上轨卖出 | 震荡市场 |
| `kdj` | KDJ 金叉死叉 | K 上穿 D 且 J<20 买入，K 下穿 D 且 J>80 卖出 | 震荡市场 |
| `momentum` | 动量策略 | N 日涨幅超阈值买入，跌幅超阈值卖出 | 趋势市场 |
| `dual_thrust` | Dual Thrust | N 日高低价范围突破 | 高波动市场 |
| `turtle` | 海龟交易 | 突破 N 日最高价买入，跌破 M 日最低价卖出 | 趋势市场 |
| `mean_reversion` | 均值回归 | Z-Score 超过阈值反向操作 | 震荡市场 |
| `ma_alignment` | 均线多头排列 | 短中长期均线多头排列买入，空头排列卖出 | 趋势市场 |
| `volume_breakout` | 量价突破 | 放量突破高点买入，缩量跌破低点卖出 | 趋势市场 |
| `volatility_breakout` | 波动率突破 | 价格突破布林带宽度一定比例时交易 | 高波动市场 |
| `trend_following` | 趋势跟踪 | ADX 判断趋势强度 + DI 方向交易 | 趋势市场 |
| `gap` | 缺口回补 | 跳空缺口回补时交易 | 震荡市场 |
| `three_soldiers` | 三白兵三乌鸦 | 连续三根阳线买入，连续三根阴线卖出 | 趋势市场 |
| `support_resistance` | 支撑阻力 | 突破阻力位买入，跌破支撑位卖出 | 通用 |
| `obv` | OBV 能量潮 | OBV 与价格背离时产生信号 | 通用 |

#### 3.1.2 进阶策略（6 种）

| 策略 Key | 名称 | 核心逻辑 | 风格 |
|----------|------|----------|------|
| `macd_multitimeframe` | MACD 多时间框架 | 日线+周线 MACD 共振 | 趋势市场 |
| `vwap` | VWAP 策略 | 价格在 VWAP 上方做多，下方做空 | 日内/短线 |
| `sar` | SAR 抛物线 | SAR 趋势转折点交易 | 趋势市场 |
| `mfi` | MFI 资金流 | MFI 超卖买入，超买卖出 | 震荡市场 |
| `sentiment_news` | 舆情策略 | 新闻情感连续正面买入，负面卖出 | 消息驱动 |
| `sentiment_contrarian` | 舆情反转 | 极度负面后转正面逆向买入 | 逆向投资 |

#### 3.1.3 私募/游资风格策略（6 种）

| 策略 Key | 名称 | 核心逻辑 | 风格 |
|----------|------|----------|------|
| `sentiment_cycle` | 情绪周期 | 恐惧买入→贪婪卖出 | 游资核心 |
| `sector_rotation` | 行业轮动 | 低估值+高景气轮动 | 机构核心 |
| `prosperity` | 景气度投资 | 高增长+放量确认 | 私募核心 |
| `band_operation` | 波段操作 | 低吸高抛，一年≤10 次 | 私募核心 |
| `value_investment` | 价值投资 | ROE+PE+分红筛选，长期持有 | 机构核心 |
| `dragon_head` | 龙头战法 | 涨停突破确认，快进快出 | 游资核心 |

### 3.2 模拟交易系统（Paper Trading）

#### 3.2.1 设计原则

- **独立资金池**：每个策略拥有独立的 10 万元初始资金
- **从当下开始**：不使用历史数据填充，从当前时间节点开始运行
- **每日运行一次**：同一交易日不重复执行，通过 `last_run` 字段去重
- **持久化存储**：账户状态保存为 JSON 文件（`data/paper_trading/` 目录）

#### 3.2.2 交易成本模型

| 费用项 | 买入 | 卖出 | 说明 |
|--------|------|------|------|
| 佣金 | 0.03% | 0.03% | 按成交金额计算 |
| 印花税 | — | 0.05% | 仅卖出时收取 |
| 滑点 | 0.1%（加价） | 0.1%（折价） | 买入价=价格×1.001，卖出价=价格×0.999 |

#### 3.2.3 执行流程

```
每日运行 → 获取行情数据 → 策略生成信号 → 判断信号类型
    │                                          │
    │         ┌────────────────────────────────┤
    │         │                                │
    │    信号=1 且无持仓                  信号=-1 且有持仓
    │         │                                │
    │    全仓买入（扣除佣金）            全仓卖出（扣除佣金+印花税）
    │         │                                │
    │    avg_cost = 总成本/数量           计算盈亏并清仓
    │         │                                │
    └─────────┴────────────────────────────────┘
                          │
                    保存账户状态 → 记录净值曲线
```

#### 3.2.4 关键指标计算

- **未实现盈亏**：考虑卖出时的全部交易成本
  ```
  卖出价 = 当前价 × (1 - 滑点)
  收入 = 卖出价 × 持仓量
  净收入 = 收入 - 佣金 - 印花税
  未实现盈亏 = 净收入 - 平均成本 × 持仓量
  ```
- **平均成本**：包含佣金的总成本/持仓量
- **最大回撤**：基于净值曲线的峰值回撤计算
- **胜率**：盈利卖出次数/总卖出次数

### 3.3 回测引擎（BacktestEngine）

#### 3.3.1 功能特性

| 功能 | 说明 |
|------|------|
| 标准回测 | 单策略全量历史回测 |
| 多策略对比 | 同时运行多策略并排序 |
| 样本外检验 | 70/30 训练/测试分割，评估过拟合风险 |
| 参数敏感性分析 | 变动参数 ±20%，评估策略稳定性 |
| 完整验证 | 一键执行：全量回测 + 样本外 + 敏感性分析 |

#### 3.3.2 回测指标

| 指标 | 计算方式 |
|------|----------|
| 总收益率 | (最终资金 - 初始资金) / 初始资金 |
| 年化收益率 | 总收益率 × 252 / 交易天数 |
| 最大回撤 | 峰值到谷底的最大跌幅 |
| 夏普比率 | (平均日收益 / 日收益标准差) × √252 |
| 卡尔玛比率 | 总收益率 / 最大回撤 |
| 胜率 | 盈利交易次数 / 总交易次数 |
| 盈亏比 | 总盈利 / 总亏损 |
| 平均持仓天数 | 所有交易对的平均持仓天数 |

#### 3.3.3 过拟合风险评估

| 收益衰减率 | 风险等级 | 建议 |
|------------|----------|------|
| < 15% | 低 | 策略在样本外表现稳定，可考虑实盘 |
| 15%-30% | 中 | 策略存在一定过拟合风险，建议谨慎 |
| 30%-50% | 中高 | 策略过拟合风险较高，不建议实盘 |
| > 50% | 高 | 策略过拟合风险高，不建议实盘 |

### 3.4 信号融合系统（SignalRouter）

#### 3.4.1 融合逻辑

```
QLib 预测分数 ──→ 归一化到 [-1, 1] ──→ × 权重(0.6) ──┐
                                                         ├──→ 加权求和 ──→ 方向判断
LLM 分析结果 ──→ 信号×置信度 ──→ × 权重(0.4) ──┘
                                                         │
                                                    ┌────┴────┐
                                                    │ 阈值判断 │
                                                    └────┬────┘
                                                         │
                                              ┌──────────┼──────────┐
                                              │          │          │
                                          score>0.2   -0.2≤score≤0.2  score<-0.2
                                              │          │          │
                                            BUY        HOLD        SELL
```

#### 3.4.2 仓位计算

- **有止损价**：基于风险预算计算（单笔风险 = 总资金 × 2%）
- **无止损价**：默认最大仓位 = 总资金 × 30%
- **风险系数调整**：
  - 日亏损 > 3%：仓位减半
  - 日亏损 > 5%：熔断（仓位为 0）
  - 信号风险等级 HIGH：仓位 × 0.3
  - 信号风险等级 MEDIUM：仓位 × 0.7

### 3.5 风控系统（RiskManager）

#### 3.5.1 风控规则

| 规则 | 参数 | 动作 |
|------|------|------|
| 单股持仓上限 | 30% | 超限则调整仓位或拒绝 |
| 日亏损预警 | 3% | 发出警告，仓位减半 |
| 日亏损熔断 | 5% | 拒绝所有新订单 |
| 最低置信度 | 0.4 | 低于阈值的信号被拒绝 |
| 行业集中度上限 | 40% | 超限则拒绝买入 |
| 最大持仓数 | 20 | 达到上限拒绝新买入 |
| T+1 限制 | 当日买入不可卖出 | 拒绝卖出 |
| 交易时段检查 | 9:30-11:30, 13:00-15:00 | 非交易时段拒绝（实盘模式） |

#### 3.5.2 风险等级评估

| 等级 | 条件 |
|------|------|
| LOW | 日亏损 < 1.5% |
| MEDIUM | 1.5% ≤ 日亏损 < 3% |
| HIGH | 3% ≤ 日亏损 < 5% |
| CRITICAL | 日亏损 ≥ 5%（熔断触发） |

### 3.6 市场状态识别（MarketRegimeDetector）

| 市场状态 | 判定条件 | 推荐策略 |
|----------|----------|----------|
| trending | 趋势强度 > 0.6 且波动率 < 3% | MA交叉、MACD、动量、海龟、Dual Thrust 等 |
| mean_reverting | 均值回归得分 > 0.6 | RSI、布林带、均值回归、KDJ 等 |
| volatile | 波动率 > 3% | 布林带、海龟、Dual Thrust |
| neutral | 其他 | 全部策略 |

### 3.7 数据服务（DataBridge）

#### 3.7.1 数据源

| 数据源 | 优先级 | 说明 |
|--------|--------|------|
| AKShare | 主数据源 | 免费，实时行情 + 历史数据 |
| Tushare | 备用数据源 | 需 Token，数据质量高 |
| 模拟数据 | 兜底 | API 均不可用时生成随机数据 |

#### 3.7.2 缓存策略

| 时段 | 缓存时间 | 说明 |
|------|----------|------|
| 交易日 9:00-15:00 | 1 小时 | 保证数据时效性 |
| 其他时间 | 6 小时 | 减少不必要的 API 调用 |

#### 3.7.3 健康检查

- 自动检测主数据源可用性
- 失败后 5 分钟内跳过主数据源直接使用备用
- 支持手动触发健康检查

### 3.8 LLM 分析引擎（LLManalyzer）

#### 3.8.1 分析模式

| 模式 | 用途 | 输出 |
|------|------|------|
| 标准分析 | 综合技术面+消息面 | signal/confidence/target_price/stop_loss/risk_level |
| 交易策略分析 | 针对个股的策略推荐 | recommended_strategy/entry_condition/exit_condition |
| 新闻情感分析 | 新闻对股价影响 | sentiment/impact_level/stock_impact_factor |

#### 3.8.2 容错机制

- API Key 无效时自动降级为 HOLD 信号
- JSON 解析失败时尝试修复（去除代码块包裹、提取 JSON）
- 超时后返回默认 HOLD 信号

### 3.9 舆情分析系统（SentimentAnalyzer + ImpactAnalyzer）

#### 3.9.1 情感分析引擎

- 基于金融领域情感词典（利好词 40+、利空词 40+）
- 支持程度副词加权（如"重大利好"权重 2.5）
- 支持否定词翻转（如"不看好"→ 负面）
- 输出：情感极性 + 归一化分数 + 强度等级

#### 3.9.2 影响因子分析

- 媒体权重：权威财经媒体（证券时报、中证报等）权重 1.5
- 历史影响系数：基于历史案例统计正/负面消息对不同周期的影响
- 综合影响分数 = 情感分数 × 媒体权重 × 历史影响系数

---

## 四、配置说明

### 4.1 配置文件路径

```
qlib_vnpy_platform/config/settings.yaml
```

### 4.2 配置项说明

```yaml
llm:
  api_key: "your-api-key"        # LLM API 密钥
  base_url: "https://api.xxx"    # API 基础 URL
  model: "model-name"            # 标准分析模型
  thinking_model: "thinking-model" # 深度思考模型
  max_tokens: 4096               # 最大 Token 数
  temperature: 0.3               # 生成温度
  timeout: 60                    # 超时时间（秒）

qlib:
  provider_uri: ~/.qlib/qlib_data/cn_data  # QLib 数据路径
  region: cn                      # 市场区域
  auto_init: true                 # 自动初始化

data:
  primary_source: akshare         # 主数据源
  fallback_source: tushare        # 备用数据源
  cache_dir: ./data/cache         # 缓存目录
  history_days: 365               # 默认历史天数
  update_interval: 60             # 更新间隔（秒）

news:
  source: eastmoney               # 新闻来源
  max_news: 10                    # 最大新闻数
  cache_hours: 2                  # 缓存时间（小时）

risk:
  max_single_position: 0.3        # 单股持仓上限
  daily_loss_warning: 0.03        # 日亏损预警线
  daily_loss_circuit_breaker: 0.05 # 日亏损熔断线
  max_single_loss: 0.02           # 单笔最大亏损
  min_confidence: 0.4             # 最低信号置信度
  max_sector_concentration: 0.4   # 行业集中度上限
  max_holdings: 20                # 最大持仓数

signal:
  weight_qlib: 0.6                # QLib 信号权重
  weight_llm: 0.4                 # LLM 信号权重
  buy_threshold: 0.2              # 买入阈值
  sell_threshold: -0.2            # 卖出阈值
  base_risk_ratio: 0.02           # 基础风险比例

trading:
  mode: paper                     # 交易模式 (paper/live)
  commission_rate: 0.0003         # 佣金率
  slippage: 0.001                 # 滑点
  min_lot_size: 100               # 最小交易单位
  default_symbol: SZ002594        # 默认股票代码

watchlist:
  default_stocks:                 # 默认关注列表
    - SZ002594

logging:
  level: INFO                     # 日志级别
  rotation: 50 MB                 # 日志轮转大小
  retention: 30 days              # 日志保留时间
```

### 4.3 环境变量支持

配置文件中的 `${VAR_NAME}` 语法会自动解析环境变量，支持默认值 `${VAR_NAME:default}`。也可通过 `.env` 文件加载。

---

## 五、使用指南

### 5.1 命令行工具（run.py）

```bash
# 分析个股
python run.py analyze -s SZ002594

# 分析多只股票
python run.py analyze -s SZ002594,SH600519

# 不使用 LLM 分析
python run.py analyze -s SZ002594 --no-llm

# 不使用 QLib 预测
python run.py analyze -s SZ002594 --no-qlib

# 查看平台状态
python run.py status

# 添加关注股票
python run.py watch -s SZ002594,SH600519

# 查看历史数据
python run.py data -s SZ002594 --days 60

# 运行回测
python run.py backtest -s SZ002594 --days 365
```

### 5.2 模拟交易

```python
from qlib_vnpy_platform.core.paper_trading import PaperTradingEngine

engine = PaperTradingEngine(initial_capital=100000.0)

# 初始化所有策略（强制重置）
engine.init_all_strategies("SZ002594", force=True)

# 每日运行单个策略
result = engine.run_daily("ma_cross", "SZ002594")

# 每日运行所有策略
results = engine.run_daily_all("SZ002594")

# 查看汇总
summary = engine.get_summary("SZ002594")

# 查看单个账户
account = engine.get_account("ma_cross", "SZ002594")

# 重置所有账户
engine.reset_all()
```

### 5.3 历史回测

```python
from qlib_vnpy_platform.core.backtest import BacktestEngine
from qlib_vnpy_platform.core.strategies import get_strategy
from qlib_vnpy_platform.core.data_bridge import DataBridge

bridge = DataBridge()
df = bridge.fetch_stock_daily("SZ002594", days=365)

engine = BacktestEngine(initial_capital=1000000.0)

# 单策略回测
strategy = get_strategy("macd")
result = engine.run(df, strategy, "SZ002594")

# 多策略对比
from qlib_vnpy_platform.core.strategies import list_strategies
strategies = [get_strategy(info["key"]) for info in list_strategies()]
results = engine.run_multiple(df, strategies, "SZ002594")
comparison = engine.compare(results)

# 样本外检验
oos_result = engine.run_out_of_sample(df, strategy, "SZ002594")

# 参数敏感性分析
sensitivity = engine.run_sensitivity(df, strategy, "SZ002594", param_name="fast")

# 完整验证
validation = engine.full_validation(df, strategy, "SZ002594")
```

### 5.4 策略模拟器

```python
from qlib_vnpy_platform.core.strategy_simulator import StrategySimulator

sim = StrategySimulator(initial_capital=100000.0)

# 模拟单个策略
result = sim.simulate_strategy("macd", "SZ002594", days=365)

# 模拟所有策略
results = sim.simulate_all_strategies("SZ002594", days=365)
```

### 5.5 主引擎（完整流程）

```python
from qlib_vnpy_platform.core.main_engine import MainEngine

engine = MainEngine()

# 添加关注股票
engine.add_stock("SZ002594")

# 分析个股（含 LLM + QLib）
result = engine.analyze_stock("SZ002594", use_llm=True, use_qlib=True)

# 自动交易模式
result = engine.analyze_stock("SZ002594", auto_trade=True)

# 启动定时调度
engine.scheduler.configure(
    watch_list=["SZ002594"],
    scan_interval=300,       # 5 分钟扫描一次
    daily_report_time=(15, 10),  # 15:10 生成日报
    auto_trade=False,
)
engine.scheduler.start()

# 查看状态
status = engine.get_status()
```

---

## 六、数据存储

### 6.1 目录结构

```
data/
├── paper_trading/                    # 模拟交易账户数据
│   ├── ma_cross_SZ002594.json        # 各策略独立账户
│   ├── macd_SZ002594.json
│   └── ...
├── cache/
│   ├── stock_data/                   # 行情数据缓存（Parquet）
│   │   ├── daily_SZ002594.parquet
│   │   └── daily_SZ000001.parquet
│   └── news/                         # 新闻缓存（JSON）
│       ├── news_SZ002594.json
│       └── news_SZ000001.json
└── sentiment_history.json            # 舆情历史数据库

qlib_vnpy_platform/
├── data/
│   ├── daily_reports/                # 每日报告
│   ├── sentiment_reports/            # 舆情报告
│   ├── strategy_reports/             # 策略报告
│   └── trade_history.json            # 交易历史
└── logs/
    ├── platform_YYYY-MM-DD.log       # 平台日志
    └── trades_YYYY-MM-DD.log         # 交易日志
```

### 6.2 账户数据结构

```json
{
  "strategy_key": "ma_cross",
  "symbol": "SZ002594",
  "initial_capital": 100000.0,
  "cash": 52345.67,
  "position": 400,
  "avg_cost": 118.56,
  "last_price": 125.30,
  "position_value": 50120.00,
  "total_equity": 102465.67,
  "total_pnl": 2465.67,
  "total_pnl_pct": 2.47,
  "unrealized_pnl": 2310.32,
  "unrealized_pnl_pct": 4.87,
  "trades": [...],
  "trade_count": 8,
  "buy_count": 4,
  "sell_count": 4,
  "equity_history": [...],
  "created_at": "2026-05-22T09:30:00",
  "last_run": "2026-05-22",
  "last_signal": "BUY",
  "last_signal_value": 1
}
```

---

## 七、Bug 修复记录

### 7.1 已修复的关键 Bug

| # | Bug 描述 | 影响范围 | 修复方案 |
|---|----------|----------|----------|
| 1 | 未实现盈亏未扣除交易成本 | paper_trading.py | 卖出价考虑滑点，扣除佣金+印花税后计算净收入 |
| 2 | 平均成本未包含佣金 | paper_trading.py | avg_cost = 总成本(含佣金) / 数量 |
| 3 | 信号覆盖问题 | paper_trading.py | 仅在未执行交易时更新信号标签 |
| 4 | 回测未扣除印花税 | backtest.py | 开仓持仓计算加入印花税扣除 |
| 5 | 策略模拟器缺少印花税 | strategy_simulator.py | 新增 stamp_tax_rate 参数，卖出时扣除印花税 |

### 7.2 交易成本一致性

修复后，三个交易模块（PaperTrading / Backtest / StrategySimulator）的交易成本模型完全一致：

| 模块 | 佣金 | 印花税 | 滑点 | 平均成本含佣金 |
|------|------|--------|------|----------------|
| PaperTrading | ✅ 0.03% | ✅ 0.05% | ✅ 0.1% | ✅ |
| Backtest | ✅ 0.03% | ✅ 0.05% | ✅ 0.1% | ✅ |
| StrategySimulator | ✅ 0.03% | ✅ 0.05% | ✅ 0.1% | ✅ |

---

## 八、行业映射表

系统内置了以下股票的行业分类，用于行业集中度风控：

| 代码 | 行业 | 代码 | 行业 |
|------|------|------|------|
| SZ000001 | 银行 | SH600000 | 银行 |
| SZ000002 | 房地产 | SH601318 | 保险 |
| SH600519 | 白酒 | SZ000858 | 白酒 |
| SH600036 | 银行 | SZ002594 | 汽车 |
| SH601166 | 银行 | SH600016 | 银行 |
| SZ000333 | 家电 | SH600276 | 医药 |
| SH601888 | 旅游 | SZ300750 | 新能源 |
| SH600900 | 电力 | SH600028 | 石油 |
| SZ002415 | 安防 | SH600031 | 机械 |
| SH600585 | 水泥 | SZ000568 | 白酒 |

---

## 九、资产配置建议（AllocationManager）

基于大师兄操盘体系，推荐资产配置比例：

| 仓位 | 比例 | 说明 | 示例 |
|------|------|------|------|
| 稳健仓 | 30%-50% | 高分红、稳现金流、弱周期 | 长江电力、中国神华、贵州茅台 |
| 进攻仓 | 10%-15% | 高景气、国产替代、硬科技 | 半导体、AI、新能源车 |
| 指数仓 | 20%-30% | 宽基指数 | 沪深300(510300)、中证500(510500) |
| 现金仓 | 10%-20% | 预留现金，大跌抄底 | — |

风控纪律：
- 永远不满仓
- 单只股票不超过总资金 10%
- 止损必须执行
- 不追高、不炒题材、不赌消息

---

## 十、运行与部署

### 10.1 环境要求

- Python 3.10+
- 依赖包：见 `requirements.txt`

### 10.2 快速启动

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 API Key（编辑 settings.yaml 或设置环境变量）

# 运行分析
python run.py analyze -s SZ002594

# 运行模拟交易
python simulated_trading.py

# 启动实时监控
python realtime_monitor.py

# 启动飞书机器人
python feishu_bot_listener.py
```

### 10.3 定时任务

```bash
# 每日自动报告
bash run_daily_report.sh

# 每日交易报告
bash run_daily_trade_report.sh

# 综合报告
bash run_integrated_report.sh
```

---

## 十一、测试

### 11.1 测试文件

| 测试文件 | 覆盖范围 |
|----------|----------|
| test_bugfix_edge.py | Bug 修复边界条件测试 |
| test_config.py | 配置加载测试 |
| test_data_bridge.py | 数据桥接测试 |
| test_integration.py | 集成测试 |
| test_llm_analyzer.py | LLM 分析器测试 |
| test_log_manager.py | 日志管理测试 |
| test_risk_manager.py | 风控管理测试 |
| test_scheduler.py | 调度器测试 |
| test_signal_router.py | 信号路由测试 |
| test_trading_engine.py | 交易引擎测试 |

### 11.2 运行测试

```bash
cd qlib_vnpy_platform
pytest tests/ -v
```
