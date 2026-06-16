# QLib+VNPY 量化交易整合平台产品文档（可落地版）

---

# 一、产品概述

## 1.1 产品定位

本产品是一款基于 QLib（微软开源 AI 量化平台）与 VNPY（VeighNa，国内开源量化交易框架）原生功能整合的专业量化交易平台。核心原则：**不重新开发两款产品的核心模块，仅通过接口调用、功能打通、择优适配**，实现"实时数据抓取 → AI 模型分析 → 策略生成 → 实盘交易"的全闭环。

定位为"AI 驱动、轻量化部署、高适配性"的专业量化交易工具，覆盖个人专业投资者、小型量化团队及机构初级量化需求，兼顾策略研发效率与实盘落地能力，填补两款原生产品的功能短板，形成"AI 分析强、实盘对接稳、操作门槛适中"的差异化优势。

## 1.2 核心价值

| 维度 | 价值主张 | 对标现状 |
|------|---------|---------|
| 功能互补 | 打通 QLib 的 AI 因子优化、模型训练优势与 VNPY 的实盘交易、实时行情对接优势 | 单一产品"分析强但落地弱"或"落地强但分析弱" |
| 轻量化落地 | 仅通过接口整合与配置，无需二次开发核心功能 | 传统方案需自建交易系统，开发周期 3-6 个月 |
| AI 赋能交易 | 集成大模型分析模块，将实时行情、资讯数据与 QLib 量化因子结合 | 传统量化平台缺乏 NLP 资讯分析能力 |
| 高适配性 | 兼容国内主流交易所接口（CTP、XTP 等 40 余种），支持多标的、多策略并行 | 单一框架难以同时覆盖 AI 分析与实盘对接 |

## 1.3 核心目标

实现"实时数据抓取 → 数据清洗与因子提取 → 大模型分析 → 策略回测与优化 → 实盘买入/卖出执行 → 风险监控"的全流程自动化，同时通过对标行业同类产品，优化用户体验与功能完整性，成为一款"可直接部署、可灵活调整、可长期迭代"的专业量化交易整合工具。

---

# 二、核心基础：QLib 与 VNPY 优缺点分析及整合逻辑

## 2.1 两款产品核心优缺点拆解

| 维度 | QLib（微软开源） | VNPY（VeighNa） | 整合决策 |
|------|-----------------|-----------------|---------|
| **AI 模型** | ✅ 内置 LightGBM、GRU、Transformer、TFT 等十余种模型，支持 Auto-ML 与分布式训练 | ❌ 4.0 版 alpha 模块 AI 模型种类少、优化能力有限 | **择优：QLib** |
| **因子体系** | ✅ Alpha158/Alpha360 因子集深度集成，因子计算引擎性能领先 | ❌ 因子预处理功能缺失，参数优化需用户自行实现 | **择优：QLib** |
| **回测框架** | ✅ 自动化工作流，支持滚动窗口、样本外测试，评估指标专业 | ⚠️ 事件驱动型回测，多标的回测效率低 | **择优：QLib 为主，VNPY 补充实盘场景验证** |
| **实盘交易** | ❌ 无原生实盘交易接口，无法对接国内交易所 | ✅ 覆盖 40 余种交易接口（CTP、XTP、华鑫奇点等），支持多账户、多策略 | **择优：VNPY** |
| **实时行情** | ❌ 原生数据抓取能力弱，主要依赖脚本爬取 | ✅ 对接迅投研、RQData 等专业数据服务，实时行情 ≤1 秒 | **择优：VNPY** |
| **可视化** | ❌ 无原生 GUI，依赖 Jupyter Notebook | ✅ 成熟的 PyQt 可视化界面，全流程可视化监控 | **择优：VNPY** |
| **资讯整合** | ❌ 无资讯抓取能力 | ❌ 侧重行情与交易数据，缺乏资讯整合 | **补充：第三方资讯 API** |
| **本土化** | ❌ 英文社区为主，安装复杂（需 gcc 编译） | ✅ 中文社区活跃，机构用户超 600 家 | **择优：VNPY** |
| **数据预处理** | ✅ 专为金融数据设计的表达式计算引擎，运算性能领先 | ⚠️ 数据预处理薄弱 | **择优：QLib** |

## 2.2 核心整合逻辑

遵循"**有则择优、无则补充、无缝打通**"三大原则：

```
┌──────────────────────────────────────────────────────────────┐
│                    整合决策矩阵                               │
├─────────────────┬─────────────────┬──────────────────────────┤
│   功能领域       │  择优/补充       │  具体方案                │
├─────────────────┼─────────────────┼──────────────────────────┤
│ AI 模型训练      │ 择优→QLib       │ 调用 QLib Model 模块     │
│ 因子计算         │ 择优→QLib       │ 调用 QLib Handler 模块   │
│ 策略回测         │ 择优→QLib       │ 调用 QLib Workflow       │
│ 实盘交易         │ 择优→VNPY       │ 调用 VNPY Gateway        │
│ 实时行情         │ 择优→VNPY       │ 调用 VNPY DataGateway    │
│ 可视化界面       │ 择优→VNPY       │ 调用 VNPY Qt 界面        │
│ 资讯数据         │ 补充→第三方API   │ 东方财富/同花顺资讯接口   │
│ 大模型分析       │ 补充→LLM API    │ 字节大模型/OpenAI API    │
│ 数据格式转换     │ 补充→整合层     │ VNPY→QLib 数据桥接       │
│ 信号路由         │ 补充→整合层     │ QLib信号→VNPY订单引擎    │
└─────────────────┴─────────────────┴──────────────────────────┘
```

---

# 三、产品核心功能设计

## 3.1 实时数据抓取模块

### 3.1.1 功能概述

以 VNPY 的实时行情接口为核心，补充第三方资讯接口，实现"行情 + 资讯"双维度数据采集。

### 3.1.2 功能清单

| 功能 | 来源 | 具体实现 | 优先级 |
|------|------|---------|--------|
| 实时行情抓取 | VNPY | 调用 `BaseDataGateway.subscribe()` 订阅股票行情，支持 tick/分钟/日线级别，更新频率 ≤1 秒 | P0 |
| 历史数据同步 | VNPY | 调用 `BaseDataGateway.query_bar_history()` 获取历史 K 线，自动转换为 QLib 格式写入 QLib 数据目录 | P0 |
| 资讯抓取 | 补充 | 对接东方财富/同花顺 API，抓取公告、行业新闻、业绩预告、政策影响等，关联股票代码 | P1 |
| 数据清洗 | QLib | 调用 `qlib.data.dataset.handler.DataHandlerLP` 进行去重、补缺失值、异常值过滤 | P0 |
| 数据存储 | QLib + VNPY | QLib 使用 `qlib.data.cache` 分布式缓存，VNPY 使用 SQLite 本地数据库，双写保证一致性 | P1 |

### 3.1.3 VNPY → QLib 数据格式映射

这是整合层最核心的数据桥接逻辑，需将 VNPY 的行情数据结构转换为 QLib 的数据格式：

```
VNPY BarData 结构                    QLib 数据格式（CSV/二进制）
─────────────────────                ──────────────────────────
symbol: "000001.SZ"          →      instrument: "SZ000001"
datetime: datetime(2025,1,1)  →      datetime: "2025-01-01"
open_price: 10.5              →      $open: 10.5
high_price: 11.0              →      $high: 11.0
low_price: 10.2               →      $low: 10.2
close_price: 10.8             →      $close: 10.8
volume: 1000000               →      $volume: 1000000
turnover: 10800000            →      $factor: 0 (需计算)
open_interest: 0              →      (期货专用，A股忽略)
```

**关键转换规则：**
- 股票代码映射：VNPY 使用 `代码.交易所` 格式（如 `000001.SZ`），QLib 使用 `交易所代码` 格式（如 `SZ000001`）
- 复权因子：VNPY 提供原始行情，QLib 需要 `$factor` 字段进行复权计算
- 时间格式：VNPY 使用 Python `datetime`，QLib 使用 `YYYY-MM-DD` 字符串格式
- 数据粒度：VNPY 支持 tick 级别，QLib 日频数据为主，分钟频需使用 `qlib.contrib.data.handler` 扩展

### 3.1.4 数据流转时序

```
VNPY DataGateway          整合层 DataBridge           QLib DataHandler
     │                         │                           │
     │──subscribe(symbol)────→│                           │
     │                         │                           │
     │←──on_bar(bar_data)────│                           │
     │                         │──convert_format()──→     │
     │                         │──write_qlib_csv()──→     │
     │                         │                           │──reload()
     │                         │                           │──calc_factor()
```

## 3.2 AI 分析与策略生成模块

### 3.2.1 功能概述

以 QLib 的 AI 模型与因子优化能力为核心，将实时数据、资讯数据输入大模型进行综合分析，生成量化策略与买卖信号。

### 3.2.2 功能清单

| 功能 | 来源 | 具体实现 | 优先级 |
|------|------|---------|--------|
| 因子提取与优化 | QLib | 调用 `Alpha158/Alpha360` 因子集，通过 `qlib.contrib.model.*` 进行因子优化 | P0 |
| 模型训练 | QLib | 调用 `qlib.workflow.R` 记录实验，支持 LightGBM/Transformer/TFT 等模型 | P0 |
| 大模型分析 | 补充 | 对接 LLM API，输入行情数据 + 资讯文本，输出结构化分析结果 | P1 |
| 策略生成 | QLib + VNPY | QLib 的 topK 轮动策略 + VNPY 的 CtaTemplate 策略模板 | P0 |
| 策略回测 | QLib（主）+ VNPY（辅） | QLib 的 `backtest_executor` + VNPY 的 `BacktestingEngine` | P0 |
| 策略优化 | QLib | 调用 `qlib.workflow.online.SacredRecorder` + Auto-ML 超参搜索 | P1 |

### 3.2.3 QLib 模型调用链路

```
用户配置策略参数
       │
       ▼
┌─────────────────────────────────────────────┐
│  QLib Workflow (qlib.workflow)              │
│  ┌───────────┐  ┌──────────┐  ┌──────────┐ │
│  │ Dataset   │→ │ Model    │→ │ Record   │ │
│  │ Handler   │  │ Training │  │ & Signal │ │
│  └───────────┘  └──────────┘  └──────────┘ │
│       │              │              │        │
│  Alpha158因子    LightGBM/     预测分数      │
│  计算引擎        Transformer   (0~1)        │
└─────────────────────────────────────────────┘
       │
       ▼
  策略信号 (pred_score)
       │
       ▼
  整合层 SignalRouter → VNPY 交易引擎
```

**QLib 核心调用接口：**

```python
import qlib
from qlib.contrib.model.gbdt import LGBModel
from qlib.contrib.data.handler import Alpha158
from qlib.workflow import R

qlib.init(provider_uri="~/.qlib/qlib_data/cn_data")

with R.start(experiment_name="strategy_train"):
    dataset = DatasetH(
        handler=Alpha158(
            start_time="2020-01-01",
            end_time="2025-01-01",
            fit_start_time="2020-01-01",
            fit_end_time="2023-12-31",
        ),
        segments={
            "train": ("2020-01-01", "2023-12-31"),
            "valid": ("2024-01-01", "2024-06-30"),
            "test":  ("2024-07-01", "2025-01-01"),
        },
    )
    model = LGBModel(loss="mse", num_leaves=64, learning_rate=0.05)
    model.fit(dataset)
    pred = model.predict(dataset)
    R.save_objects(**{"pred.pkl": pred})
```

### 3.2.4 大模型分析集成方案

**Prompt 工程设计：**

```
系统角色：你是一位专业的量化分析师，需要结合技术面和消息面给出交易建议。

输入数据：
1. 当前行情：{stock_code} 最新价 {price}，涨跌幅 {change_pct}%
   5日均线 {ma5}，20日均线 {ma20}，成交量 {volume}
2. QLib 模型预测分数：{pred_score}（0~1，越高越看涨）
3. 近期资讯：
   - {news_1}
   - {news_2}
   - {news_3}

输出格式（严格 JSON）：
{
  "signal": "BUY" | "SELL" | "HOLD",
  "confidence": 0.0-1.0,
  "reason": "分析理由",
  "target_price": 目标价,
  "stop_loss": 止损价,
  "risk_level": "LOW" | "MEDIUM" | "HIGH"
}
```

**信号融合逻辑：**

```
QLib 预测分数 (pred_score)     LLM 分析结果 (signal + confidence)
         │                              │
         ▼                              ▼
   ┌───────────┐                 ┌───────────┐
   │ 分数阈值  │                 │ 信号映射  │
   │ >0.6: BUY │                 │ BUY: +1   │
   │ <0.4: SELL│                 │ SELL: -1  │
   │ 其他:HOLD │                 │ HOLD: 0   │
   └─────┬─────┘                 └─────┬─────┘
         │                              │
         └──────────┬───────────────────┘
                    ▼
           ┌─────────────────┐
           │  加权融合决策     │
           │  w_qlib=0.6     │
           │  w_llm=0.4      │
           │                 │
           │  final = w_qlib │
           │    * qlib_sig   │
           │    + w_llm      │
           │    * llm_sig    │
           └────────┬────────┘
                    ▼
           最终交易信号 (BUY/SELL/HOLD)
```

## 3.3 实盘交易模块

### 3.3.1 功能概述

以 VNPY 的实盘交易接口为核心，接收 QLib 与大模型输出的交易信号，实现自动交易执行。

### 3.3.2 功能清单

| 功能 | 来源 | 具体实现 | 优先级 |
|------|------|---------|--------|
| 交易信号对接 | 整合层 | `SignalRouter` 将 QLib/LLM 信号转换为 VNPY 订单请求 | P0 |
| 自动交易执行 | VNPY | 调用 `CtpGateway.send_order()` / `XtpGateway.send_order()` | P0 |
| 订单类型 | VNPY | 支持市价单（`OrderType.MARKET`）、限价单（`OrderType.LIMIT`） | P0 |
| 账户管理 | VNPY | 调用 `MainEngine` 的多账户管理，支持 CTP/XTP 等多接口 | P1 |
| 手动干预 | VNPY | 调用 `MainEngine.cancel_order()` / 手动下单接口 | P0 |
| 交易记录 | VNPY | 调用 `OmsEngine` 的订单/成交记录，同步至 QLib 数据库 | P1 |

### 3.3.3 信号到订单的转换逻辑

```
QLib/LLM 交易信号              VNPY 订单结构
─────────────────              ──────────────────────────────
stock_code: "SZ000001"  →     vt_symbol: "000001.SZ"
direction: "BUY"        →     Direction: Direction.LONG
signal_price: 10.80     →     price: 10.80 (限价) / 0 (市价)
volume: 1000            →     volume: 1000
stop_loss: 10.50        →     stop_price: 10.50 (止损单)
take_profit: 11.50      →     limit_price: 11.50 (止盈单)
confidence: 0.85        →     (用于仓位计算: 仓位=基础仓位*confidence)
```

**仓位计算公式：**

```
实际下单数量 = 基础仓位 × 信号置信度 × 风控系数

其中：
- 基础仓位 = 总资金 × 单笔风险比例(默认2%) / (入场价 - 止损价)
- 信号置信度 = QLib pred_score 与 LLM confidence 的加权融合值
- 风控系数 = min(1.0, 单股持仓上限/当前持仓) × min(1.0, 日亏损限额/当日已亏损)
```

### 3.3.4 A 股交易规则适配

| 规则 | 实现方式 |
|------|---------|
| T+1 交易 | 整合层记录买入日期，当日买入的股票不允许卖出信号通过 |
| 涨跌停限制 | VNPY Gateway 原生支持，订单价格超出涨跌停范围自动拒绝 |
| 最小交易单位 | 整合层将信号数量向下取整至 100 股的整数倍（1 手 = 100 股） |
| 集合竞价 | VNPY 支持集合竞价订单类型，整合层在 9:15-9:25 时段使用限价单 |
| 停牌处理 | VNPY 行情接口自动识别停牌股票，整合层过滤停牌标的的交易信号 |

## 3.4 风险控制模块

### 3.4.1 三级风控体系

```
┌──────────────────────────────────────────────────────┐
│                    三级风控体系                        │
├──────────────┬──────────────┬────────────────────────┤
│  一级：事前   │  二级：事中   │  三级：事后             │
├──────────────┼──────────────┼────────────────────────┤
│ 单股仓位≤30% │ 日亏损≥3%预警│ 策略归因分析            │
│ 日亏损限额≤5%│ 日亏损≥5%熔断│ 模型性能回测            │
│ 行业集中度≤40%│ 波动率突增降仓│ 交易复盘报告            │
│ 模型置信度阈值│ 数据异常暂停  │ 合规审计日志            │
│ 交易时段限制  │ 订单超时撤单  │ 风险指标周报            │
└──────────────┴──────────────┴────────────────────────┘
```

### 3.4.2 风控参数配置

| 参数 | 默认值 | 说明 | 来源 |
|------|--------|------|------|
| 单股持仓上限 | 30% | 单只股票占总资产比例上限 | VNPY 风控模块 |
| 日亏损预警线 | 3% | 触发预警通知 | 整合层 |
| 日亏损熔断线 | 5% | 自动暂停交易 | 整合层 |
| 单笔最大亏损 | 2% | 单笔交易最大允许亏损 | QLib 风险评估 |
| 模型置信度下限 | 0.4 | pred_score < 0.4 不生成信号 | QLib |
| 数据缺失率上限 | 0.1% | 超过则切换备用数据源 | QLib 数据校验 |
| 行业集中度上限 | 40% | 单行业持仓占比上限 | 整合层 |
| 最大持仓股票数 | 20 | 同时持有的股票数量上限 | 整合层 |

## 3.5 舆情分析模块（新增）

### 3.5.1 功能概述

针对投资者受情绪影响的特点，开发舆情分析系统，实现"新闻抓取 → 情感分析 → 股价影响因子评估 → 策略调整建议"的完整闭环，专门针对比亚迪等热门股票进行深度舆情监控。

### 3.5.2 功能清单

| 功能 | 来源 | 具体实现 | 优先级 |
|------|------|---------|--------|
| 多源资讯抓取 | 补充 | 对接东方财富、新浪财经、同花顺、证券时报等多源数据，包括：公司公告、新闻资讯、研报分析、股吧评论、行业动态 | P0 |
| 情感分析引擎 | 补充 | 基于大模型/情感词典的情感极性分析，输出：正面/中性/负面情感评分、情感强度、关键情绪词 | P0 |
| 股价影响因子分析 | 补充 | 建立历史舆情-股价联动数据库，通过统计分析计算：舆情发布后1日/3日/5日/10日的超额收益率、相关性系数、影响时效性、影响衰减曲线 | P0 |
| 舆情预警系统 | 补充 | 设置情感阈值、因子强度阈值，当出现重大利好/利空时自动推送预警，包含：预警级别、影响分析、历史类似案例、操作建议 | P1 |
| 舆情报告生成 | 补充 | 每日生成比亚迪舆情简报，包含：当日新闻概览、情感走势、关键因子、与历史类似舆情对比、策略建议 | P1 |

### 3.5.3 情感分析技术方案

**方法一：大模型情感分析（推荐）**
```python
# 使用大模型进行深度情感分析
prompt = """
请分析以下新闻对{stock_name}的影响：

新闻标题：{title}
新闻内容：{content}

请输出以下格式的JSON：
{
  "sentiment": "positive|neutral|negative",  // 情感极性
  "sentiment_score": -1.0~1.0,            // 情感评分，越正面越高
  "impact_level": 1~5,                    // 影响级别，5最高
  "key_factors": [...],                  // 关键影响因子
  "suggestion": "buy|hold|sell",          // 操作建议
  "reasoning": "分析理由"
}
"""
```

**方法二：情感词典分析（备用）**
- 构建金融领域情感词典（正向词、负向词、程度副词、否定词）
- 基于规则计算情感得分
- 适用于大模型不可用时的降级方案

### 3.5.4 股价影响因子计算方法

**因子1：舆情影响系数**
```
impact_coefficient = corr(historical_sentiment, next_N_day_return)
```
计算历史N天的舆情得分与后N日收益率的相关系数

**因子2：时效性衰减因子**
```
time_decay = exp(-lambda * t)  // 指数衰减，t为舆情发布天数
```

**因子3：舆情影响力评分**
```
influence_score = sentiment_score * impact_coefficient * media_weight
```
- sentiment_score：情感评分
- impact_coefficient：历史影响系数
- media_weight：媒体权重（权威媒体权重更高）

### 3.5.5 舆情-策略联动机制

将舆情分析结果与现有量化策略结合：

| 策略类型 | 舆情联动规则 |
|---------|------------|
| 趋势策略 | 重大利好时加仓，重大利空时减仓 |
| 均值回归 | 舆情反转信号出现时反向操作 |
| 事件驱动 | 基于重大事件触发专项策略 |
| 组合策略 | 舆情因子作为策略权重调整依据 |

**信号融合权重：**
- QLib 技术面信号：60%
- 舆情分析信号：25%
- LLM 分析信号：15%

### 3.5.6 舆情数据处理流程

```
多源新闻抓取
     ↓
数据清洗与去重
     ↓
情感分析引擎
     ↓
股价影响因子评估
     ↓
舆情风险预警
     ↓
策略信号融合
     ↓
生成报告推送
```

## 3.6 可视化操作模块

### 3.6.1 功能概述

以 VNPY 的 PyQt 可视化界面为基础，整合 QLib 的分析功能、大模型分析结果及舆情分析，打造"一站式"可视化操作平台。

### 3.6.2 界面模块设计

| 模块 | 功能 | 来源 |
|------|------|------|
| 首页总览 | 实时行情、账户盈亏、策略运行状态、风险预警 | VNPY MainWindow 扩展 |
| 数据中心 | K 线图、成交量图、因子热力图、因子有效性曲线 | VNPY ChartWidget + QLib 分析图表 |
| 策略工作台 | 策略模板选择、参数配置、回测启动、实盘切换 | VNPY StrategyWidget 扩展 |
| AI 分析面板 | 大模型分析结果、QLib 模型输出、信号融合可视化 | 新增面板 |
| 舆情分析面板 | 实时舆情监控、情感走势图、影响因子展示、历史案例库 | 新增面板 |
| 交易监控 | 订单状态、持仓明细、成交记录、盈亏曲线 | VNPY TradingWidget |
| 风控仪表盘 | 风险指标实时展示、预警记录、熔断状态 | 新增面板 |
| 系统设置 | 数据源配置、交易接口配置、风控参数、LLM API 密钥 | VNPY SettingWidget 扩展 |

---

# 四、产品架构设计

## 4.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        应用层 (Application)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ 首页总览  │ │ 策略工作台│ │ AI分析面板│ │ 交易监控  │          │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘          │
│       │             │             │             │                │
│  VNPY Qt 界面 + 自定义 QWidget 扩展                              │
├─────────────────────────────────────────────────────────────────┤
│                      整合层 (Integration)                        │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│  │ DataBridge   │ │ SignalRouter │ │ RiskManager  │            │
│  │ 数据格式转换  │ │ 信号路由融合  │ │ 风控决策引擎  │            │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘            │
│         │                │                │                      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│  │ NewsFetcher  │ │ LLManalyzer  │ │ Monitor      │            │
│  │ 资讯抓取     │ │ 大模型分析    │ │ 系统监控      │            │
│  └──────────────┘ └──────────────┘ └──────────────┘            │
│  ┌──────────────────────────────────────────────────┐         │
│  │       SentimentAnalyzer（情感分析）              │         │
│  │  · 情感极性分析   · 情感强度计算              │         │
│  │  · 关键因子提取   · 历史相关性分析            │         │
│  │       ImpactAnalyzer（影响因子分析）          │         │
│  │  · 舆情影响系数   · 时效性衰减曲线            │         │
│  │  · 历史案例库   · 策略联动机制               │         │
│  │       SentimentReport（报告生成）          │         │
│  └──────────────────────────────────────────────────┘         │
├─────────────────────────────────────────────────────────────────┤
│                        接口层 (Interface)                        │
│  ┌─────────────────────┐  ┌─────────────────────┐              │
│  │     QLib 接口        │  │     VNPY 接口        │              │
│  │ · DataHandlerLP     │  │ · BaseDataGateway   │              │
│  │ · Alpha158/360      │  │ · CtpGateway        │              │
│  │ · LGBModel/TFT      │  │ · XtpGateway        │              │
│  │ · backtest_executor │  │ · BacktestingEngine │              │
│  │ · R (实验记录)       │  │ · MainEngine        │              │
│  │ · qlib.init()       │  │ · OmsEngine         │              │
│  └─────────────────────┘  └─────────────────────┘              │
│           │                          │                           │
│  ┌─────────────────────┐  ┌─────────────────────┐              │
│  │   第三方接口          │  │   数据存储            │              │
│  │ · 东方财富资讯API    │  │ · QLib: ~/.qlib/    │              │
│  │ · 同花顺资讯API      │  │ · VNPY: SQLite      │              │
│  │ · LLM API           │  │ · 备份: CSV/Parquet  │              │
│  └─────────────────────┘  └─────────────────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

## 4.2 整合层核心模块详细设计

### 4.2.1 DataBridge（数据桥接模块）

**职责：** VNPY 行情数据 → QLib 数据格式的实时转换与同步

```python
class DataBridge:
    """
    VNPY 行情数据到 QLib 数据格式的实时桥接
    """

    CODE_MAP = {
        "SZ": "SZ",   # 深交所
        "SH": "SH",   # 上交所
    }

    def vnpy_to_qlib_symbol(self, vnpy_symbol: str) -> str:
        """VNPY 代码格式 → QLib 代码格式
        例: '000001.SZ' → 'SZ000001'
        """
        code, exchange = vnpy_symbol.split(".")
        return f"{self.CODE_MAP.get(exchange, exchange)}{code}"

    def qlib_to_vnpy_symbol(self, qlib_symbol: str) -> str:
        """QLib 代码格式 → VNPY 代码格式
        例: 'SZ000001' → '000001.SZ'
        """
        exchange = qlib_symbol[:2]
        code = qlib_symbol[2:]
        reverse_map = {v: k for k, v in self.CODE_MAP.items()}
        return f"{code}.{reverse_map.get(exchange, exchange)}"

    def bar_to_qlib_record(self, bar_data) -> dict:
        """VNPY BarData → QLib 数据记录"""
        return {
            "datetime": bar_data.datetime.strftime("%Y-%m-%d"),
            "instrument": self.vnpy_to_qlib_symbol(bar_data.symbol),
            "$open": bar_data.open_price,
            "$high": bar_data.high_price,
            "$low": bar_data.low_price,
            "$close": bar_data.close_price,
            "$volume": bar_data.volume,
            "$factor": self._calc_adjust_factor(bar_data),
        }

    def sync_to_qlib(self, bar_data_list: list):
        """批量将 VNPY 行情数据写入 QLib 数据目录"""
        pass

    def _calc_adjust_factor(self, bar_data) -> float:
        """计算复权因子（基于历史分红派息数据）"""
        pass
```

### 4.2.2 SignalRouter（信号路由模块）

**职责：** QLib 预测信号 + LLM 分析信号 → 融合决策 → VNPY 订单

```python
class SignalRouter:
    """
    交易信号融合与路由
    """

    WEIGHT_QLIB = 0.6
    WEIGHT_LLM = 0.4

    def fuse_signals(self, qlib_pred: float, llm_signal: dict) -> dict:
        """融合 QLib 预测分数与 LLM 分析结果"""
        qlib_score = self._qlib_to_signal(qlib_pred)
        llm_score = self._llm_to_signal(llm_signal)

        final_score = (self.WEIGHT_QLIB * qlib_score
                      + self.WEIGHT_LLM * llm_score)

        return {
            "direction": self._score_to_direction(final_score),
            "confidence": abs(final_score),
            "target_price": llm_signal.get("target_price"),
            "stop_loss": llm_signal.get("stop_loss"),
        }

    def _qlib_to_signal(self, pred_score: float) -> float:
        """QLib pred_score (0~1) → 信号分数 (-1~1)"""
        return (pred_score - 0.5) * 2

    def _llm_to_signal(self, llm_result: dict) -> float:
        """LLM 分析结果 → 信号分数 (-1~1)"""
        signal_map = {"BUY": 1.0, "SELL": -1.0, "HOLD": 0.0}
        return signal_map.get(llm_result.get("signal"), 0.0) * llm_result.get("confidence", 0.5)

    def _score_to_direction(self, score: float) -> str:
        if score > 0.2:
            return "BUY"
        elif score < -0.2:
            return "SELL"
        return "HOLD"

    def signal_to_order_request(self, signal: dict, account: dict) -> dict:
        """交易信号 → VNPY 订单请求"""
        base_volume = self._calc_position_size(signal, account)
        risk_coeff = self._calc_risk_coefficient(account)

        return {
            "vt_symbol": self._qlib_to_vnpy_symbol(signal["symbol"]),
            "direction": signal["direction"],
            "price": signal.get("target_price", 0),
            "volume": int(base_volume * signal["confidence"] * risk_coeff / 100) * 100,
            "stop_price": signal.get("stop_loss"),
        }
```

### 4.2.3 LLManalyzer（大模型分析模块）

**职责：** 将行情数据 + 资讯文本输入 LLM，输出结构化交易建议

```python
class LLManalyzer:
    """
    大模型行情分析模块
    """

    SYSTEM_PROMPT = """你是一位专业的量化分析师..."""  # 见 3.2.4

    def analyze(self, stock_code: str, market_data: dict,
                news_list: list, qlib_pred: float) -> dict:
        """综合分析并输出结构化交易建议"""
        user_prompt = self._build_prompt(stock_code, market_data,
                                          news_list, qlib_pred)
        response = self.llm_client.chat(
            system=self.SYSTEM_PROMPT,
            user=user_prompt,
            response_format="json",
        )
        return self._parse_response(response)

    def _build_prompt(self, stock_code, market_data,
                      news_list, qlib_pred) -> str:
        return f"""
输入数据：
1. 当前行情：{stock_code} 最新价 {market_data['price']}，
   涨跌幅 {market_data['change_pct']}%
   5日均线 {market_data['ma5']}，20日均线 {market_data['ma20']}，
   成交量 {market_data['volume']}
2. QLib 模型预测分数：{qlib_pred}
3. 近期资讯：
{self._format_news(news_list)}
"""

    def _parse_response(self, response: str) -> dict:
        """解析 LLM JSON 输出，校验字段完整性"""
        pass
```

### 4.2.4 NewsFetcher（资讯抓取模块）

**职责：** 对接第三方资讯 API，抓取并结构化股票相关资讯

| 数据源 | 接口 | 数据内容 | 费用 |
|--------|------|---------|------|
| 东方财富 | HTTP REST API | 公告、研报、新闻 | 免费（有频率限制） |
| 同花顺 | iFinD API | 资讯、资金流向、龙虎榜 | 付费 |
| Tushare Pro | Python SDK | 财务数据、分红配股 | 积分制 |
| 新浪财经 | HTTP 爬虫 | 实时新闻 | 免费 |

## 4.3 数据流转全景图

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  VNPY    │    │ 整合层    │    │  QLib    │    │ 整合层    │    │  VNPY    │
│ 行情网关  │───→│DataBridge│───→│ 数据处理  │───→│SignalRouter│──→│ 交易网关  │
│          │    │ 格式转换  │    │ 因子计算  │    │ 信号融合  │    │ 订单执行  │
│ 实时tick │    │ 代码映射  │    │ 模型预测  │    │ 仓位计算  │    │ 成交回报  │
│ 历史K线  │    │ 复权计算  │    │ 策略回测  │    │ 风控校验  │    │ 持仓更新  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
      │                              ↑               ↑                │
      │                              │               │                │
      │         ┌──────────┐    ┌────┴─────┐   ┌────┴─────┐         │
      │         │NewsFetcher│    │  QLib    │   │   LLM    │         │
      │         │ 资讯抓取  │───→│ 数据存储  │   │ 大模型   │         │
      │         │ 东方财富  │    │          │   │ 分析     │         │
      │         │ 同花顺    │    │          │   │          │         │
      │         └──────────┘    └──────────┘   └──────────┘         │
      │                                                             │
      └─────────────── 成交回报 → 更新持仓 → 反馈至风控 ─────────────┘
```

## 4.4 部署架构

### 4.4.1 单机部署（推荐，个人/小团队）

```
┌─────────────────────────────────────────────┐
│              单机部署架构                     │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │         Python 进程                    │  │
│  │  ┌─────────┐  ┌─────────┐            │  │
│  │  │  VNPY   │  │  QLib   │            │  │
│  │  │ MainEng │  │ init()  │            │  │
│  │  └────┬────┘  └────┬────┘            │  │
│  │       │            │                  │  │
│  │  ┌────┴────────────┴────┐            │  │
│  │  │    整合层模块          │            │  │
│  │  │  DataBridge           │            │  │
│  │  │  SignalRouter         │            │  │
│  │  │  LLManalyzer          │            │  │
│  │  │  RiskManager          │            │  │
│  │  └───────────────────────┘            │  │
│  └───────────────────────────────────────┘  │
│                                             │
│  硬件：CPU≥i5, 内存≥16G, SSD≥256G           │
│  系统：macOS / Windows 10+ / Ubuntu 20.04+  │
└─────────────────────────────────────────────┘
```

### 4.4.2 macOS 兼容性说明

VNPY 的 CTP 接口（`vnpy_ctp`）在 macOS 上需要特殊处理：

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| CTP API 结构体差异 | macOS 版 CTP 头文件缺少部分字段（LoginDRIdentityID 等） | 条件编译 `#ifdef __APPLE__` 包裹不兼容代码 |
| CTP API 函数差异 | `CreateFtdcMdApi`/`CreateFtdcTraderApi` 参数数量不同 | macOS 调用少参数版本 |
| CTP Framework 签名 | macOS 代码签名校验 | `codesign --force --deep --sign -` 重签名 |
| 链接 iconv 依赖 | CTP Framework 依赖 iconv 库 | meson.build 添加 `-liconv` |
| 缺失 API 函数 | macOS 版 CTP 不支持 Wechat 相关 API | 条件编译排除 |

**建议：** 如需在 macOS 上进行实盘交易，优先使用 XTP 接口（对 macOS 支持更好），CTP 接口建议在 Linux 环境下运行。

### 4.4.3 环境配置清单

| 组件 | 版本要求 | 安装方式 |
|------|---------|---------|
| Python | 3.10+ | pyenv / conda |
| QLib | 0.9+ | `pip install pyqlib` |
| VNPY | 3.9+ | `pip install vnpy` |
| vnpy_ctp | 6.7+ | 源码编译安装（macOS 需条件编译修复） |
| vnpy_xtp | 最新 | `pip install vnpy_xtp` |
| pybind11 | 2.11+ | `pip install pybind11` |
| meson | 1.7+ | `pip install meson` |
| LightGBM | 4.0+ | `pip install lightgbm` |
| pandas | 2.0+ | `pip install pandas` |

---

# 五、对标行业产品分析

## 5.1 国内产品对标

| 维度 | 本产品 | 聚宽 JoinQuant | 米筐 RiceQuant | 迅投 QMT | 私募排排 |
|------|--------|---------------|---------------|----------|---------|
| AI 分析 | ⭐⭐⭐⭐⭐ QLib+LLM | ⭐⭐ 基础 | ⭐⭐ 基础 | ⭐ 弱 | ⭐⭐ 基础 |
| 实盘交易 | ⭐⭐⭐⭐ VNPY 40+接口 | ⭐⭐⭐ 有限 | ⭐⭐⭐ 有限 | ⭐⭐⭐⭐⭐ 强 | ⭐⭐ 弱 |
| 回测能力 | ⭐⭐⭐⭐⭐ QLib | ⭐⭐⭐⭐ 好 | ⭐⭐⭐⭐ 好 | ⭐⭐⭐ 一般 | ⭐⭐⭐ 一般 |
| 数据覆盖 | ⭐⭐⭐ VNPY+第三方 | ⭐⭐⭐⭐⭐ 全面 | ⭐⭐⭐⭐⭐ 全面 | ⭐⭐⭐ 一般 | ⭐⭐⭐ 一般 |
| 使用成本 | ⭐⭐⭐⭐⭐ 开源免费 | ⭐⭐⭐ 部分收费 | ⭐⭐ 收费高 | ⭐ 收费高 | ⭐⭐⭐ 部分免费 |
| 学习门槛 | ⭐⭐⭐ 中等 | ⭐⭐⭐⭐ 低 | ⭐⭐ 高 | ⭐⭐ 高 | ⭐⭐⭐⭐ 低 |
| 部署方式 | 本地部署 | 云端 | 云端 | 本地 | 云端 |

## 5.2 国际产品对标

| 维度 | 本产品 | QuantConnect | WorldQuant BRAIN | Quantopian(已关) |
|------|--------|-------------|-----------------|------------------|
| AI 分析 | ⭐⭐⭐⭐⭐ QLib+LLM | ⭐⭐⭐ 基础ML | ⭐⭐⭐⭐⭐ Alpha因子 | N/A |
| 实盘交易 | ⭐⭐⭐⭐ 国内40+接口 | ⭐⭐⭐⭐ 国际券商 | ⭐⭐ 模拟为主 | N/A |
| 因子体系 | ⭐⭐⭐⭐⭐ Alpha158/360 | ⭐⭐⭐ 自定义 | ⭐⭐⭐⭐⭐ 全球因子库 | N/A |
| 本土化 | ⭐⭐⭐⭐⭐ 深度适配A股 | ⭐⭐ 美股为主 | ⭐ 全球 | N/A |

## 5.3 差异化优势与优化方向

**核心差异化：**
1. **AI + 实盘双强**：唯一同时具备 QLib 级 AI 分析能力与 VNPY 级实盘对接能力的开源方案
2. **大模型赋能**：集成 LLM 进行资讯分析，这是聚宽、米筐等平台均不具备的能力
3. **零成本起步**：核心功能完全开源免费，适合个人和小团队
4. **本地部署可控**：数据不出本地，隐私安全有保障

**待优化方向：**
1. 数据覆盖不如聚宽/米筐全面（缺乏港股、美股数据）
2. 云端部署选项缺失（需本地配置，门槛偏高）
3. 策略社区生态薄弱（缺乏用户共享策略模板的机制）
4. 高频交易支持不足（VNPY 事件驱动架构延迟较高）

---

# 六、落地方案

## 6.1 分阶段实施路线图

### 阶段 1：基础搭建（第 1-2 周）

| 任务 | 具体内容 | 交付物 | 验收标准 |
|------|---------|--------|---------|
| 环境搭建 | 安装 QLib + VNPY，配置 Python 环境 | 可运行的 Python 环境 | `import qlib; import vnpy` 成功 |
| 接口对接 | 配置 VNPY 行情接口（CTP/XTP），配置 QLib 数据初始化 | 数据连通 | VNPY 可收到行情，QLib 可读取数据 |
| DataBridge | 开发数据格式转换模块 | data_bridge.py | VNPY BarData 可正确转换为 QLib 格式 |
| 第三方配置 | 对接资讯 API、LLM API | API 配置文件 | 可成功调用 API 获取数据 |

### 阶段 2：核心功能开发（第 3-5 周）

| 任务 | 具体内容 | 交付物 | 验收标准 |
|------|---------|--------|---------|
| SignalRouter | 开发信号融合与路由模块 | signal_router.py | QLib 信号 + LLM 信号可正确融合 |
| LLManalyzer | 开发大模型分析模块 | llm_analyzer.py | 输入行情+资讯，输出结构化交易建议 |
| NewsFetcher | 开发资讯抓取模块 | news_fetcher.py | 可抓取指定股票相关资讯 |
| RiskManager | 开发风控决策引擎 | risk_manager.py | 三级风控规则可正确触发 |
| 交易对接 | 信号→VNPY 订单的完整链路 | 完整交易链路 | 模拟环境下可自动下单 |

### 阶段 3：测试与上线（第 6-8 周）

| 任务 | 具体内容 | 交付物 | 验收标准 |
|------|---------|--------|---------|
| 模块测试 | 各模块单元测试 | 测试报告 | 所有测试用例通过 |
| 集成测试 | 全流程端到端测试 | 测试报告 | 数据→分析→信号→交易链路通畅 |
| 异常测试 | 接口失败、数据异常、行情突变 | 异常处理报告 | 异常场景系统不崩溃 |
| 模拟盘运行 | 1-2 只标的，模拟盘运行 2 周 | 运行报告 | 策略执行稳定，无异常 |
| 小规模实盘 | 1 只标的，最小资金实盘 | 实盘报告 | 交易执行正常，风控有效 |

## 6.2 人员配置

| 角色 | 人数 | 技能要求 | 职责 |
|------|------|---------|------|
| 量化工程师 | 1-2 | Python、QLib、VNPY | 环境搭建、整合层开发、接口对接 |
| 策略研究员 | 1 | 量化策略、因子分析 | 策略设计、参数优化、回测验证 |
| 运维 | 0.5（兼职） | Linux、Docker | 系统部署、监控、异常处理 |

## 6.3 成本预算

| 项目 | 月成本 | 说明 |
|------|--------|------|
| 硬件 | ¥0 | 使用现有电脑 |
| QLib | ¥0 | 开源免费 |
| VNPY | ¥0 | 开源免费 |
| 行情数据 | ¥0-500 | 迅投研免费版/付费版 |
| 资讯 API | ¥0-300 | 东方财富免费/同花顺付费 |
| LLM API | ¥100-500 | 按 token 计费 |
| **合计** | **¥100-1300/月** | 基础配置约 ¥100/月 |

---

# 七、风险与应对

## 7.1 技术风险

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|---------|
| QLib/VNPY 版本升级导致接口不兼容 | 中 | 高 | 锁定版本号，建立版本兼容性测试，预留接口适配层 |
| macOS 上 CTP 接口编译/运行异常 | 高 | 中 | 优先使用 XTP 接口，CTP 在 Linux 环境运行，macOS 用于策略研发 |
| LLM API 服务不可用或响应超时 | 中 | 中 | 设置超时降级策略（仅使用 QLib 信号），备用多个 LLM 提供商 |
| 实时数据源中断 | 低 | 高 | 配置主备数据源（迅投研 + RQData），自动切换 |
| 整合层内存泄漏或进程崩溃 | 低 | 高 | 进程守护（supervisor/systemd），自动重启，状态持久化 |

## 7.2 交易风险

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|---------|
| 策略失效导致持续亏损 | 中 | 高 | 三级风控体系，日亏损 5% 自动熔断，模型性能实时监控 |
| 极端行情（闪崩/黑天鹅） | 低 | 极高 | 止损止盈硬编码，手动干预权限，最大回撤预警 |
| 交易接口延迟或故障 | 低 | 高 | 订单超时自动撤单，多交易接口冗余 |
| 模型过拟合 | 中 | 中 | 样本外测试，滚动窗口验证，定期重训练 |

## 7.3 合规风险

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|---------|
| 交易行为触发交易所风控 | 低 | 高 | 遵守交易频率限制，避免异常交易模式 |
| 数据使用合规问题 | 低 | 中 | 仅使用合法数据源，遵守数据使用协议 |
| 交易记录留存不完整 | 低 | 中 | 全量交易记录双写（VNPY SQLite + QLib），保留至少 5 年 |

---

# 八、后期迭代规划

## 8.1 短期（3-6 个月）

- [ ] 补充港股/美股数据接口（通过 Tushare Pro / AKShare）
- [ ] 优化一键部署脚本（Docker Compose 一键启动）
- [ ] 新增新手引导模块与视频教程
- [ ] 丰富策略模板（网格策略、配对交易、多因子选股）
- [ ] LLM Prompt 优化与回测（基于历史信号评估 LLM 分析准确率）

## 8.2 中期（6-12 个月）

- [ ] 搭建策略社区（策略模板分享、回测结果排行）
- [ ] 引入可解释 AI（XAI），提升模型透明度
- [ ] 完善机构级功能（多账户批量管理、合规风控、业绩归因）
- [ ] 云端部署选项（AWS/阿里云一键部署）
- [ ] 支持更多 LLM 提供商（OpenAI、DeepSeek、Qwen）

## 8.3 长期（1 年以上）

- [ ] 国际化适配（美股、港股实盘交易）
- [ ] 引入联邦学习（多用户协同训练，数据不出本地）
- [ ] 高频交易优化（C++ 订单路由、FPGA 加速）
- [ ] 商业化（机构级 SaaS 服务、专属策略定制）
- [ ] 与券商/基金公司合作，接入更多交易接口与数据源

---

# 九、总结

本产品通过"调用 QLib 与 VNPY 原生功能、择优整合、补充完善"的方式，无需重新开发核心模块，实现了"实时数据抓取 → AI 分析 → 策略生成 → 实盘交易 → 风险监控"的全闭环。

**核心创新点：**
1. **双引擎择优架构**：AI 分析用 QLib，实盘交易用 VNPY，各取所长
2. **大模型赋能**：LLM 资讯分析 + QLib 因子预测的信号融合，填补行业空白
3. **轻量化整合层**：DataBridge + SignalRouter + RiskManager 三大核心模块，代码量可控
4. **全流程自动化**：从数据到交易的全链路自动执行，人工仅需监控与干预

**落地保障：**
- 分阶段实施路线图，8 周可完成基础版上线
- 月成本 ¥100-1300，个人投资者可承受
- macOS/Linux/Windows 全平台支持（macOS 需注意 CTP 兼容性）
- 三级风控体系确保交易安全
