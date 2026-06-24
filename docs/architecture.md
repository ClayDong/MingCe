# 明策（MingCe）系统架构文档

> **版本**：v3.0 · 2026-06-16  
> **文档定位**：描述系统整体架构、模块职责、数据流与依赖关系

---

## 目录

1. [双系统架构总览](#1-双系统架构总览)
2. [五维框架说明](#2-五维框架说明)
3. [三层传导框架](#3-三层传导框架)
4. [数据采集层](#4-数据采集层)
5. [策略引擎](#5-策略引擎)
6. [推送层](#6-推送层)
7. [告警链路](#7-告警链路)
8. [服务依赖关系图](#8-服务依赖关系图)
9. [炒股的智慧深度分析](#9-炒股的智慧深度分析)

---

## 1. 双系统架构总览

明策由 **bot（日报主系统）** 和 **engine（策略引擎）** 两个子系统构成，通过 HTTP 微服务 / subprocess 两种方式通信。

### 1.1 ASCII 架构图

```
                           ┌──────────────────────┐
                           │      飞书群            │
                           │  每日推送 · @机器人    │
                           └──────────┬───────────┘
                                      │ 飞书 Open API
                                      │ (tenant_access_token)
                           ┌──────────▼───────────┐
                           │       bot/            │ ← 日报主系统
                           │  FastAPI + APScheduler │
                           │  Port 8000             │
                           └──────┬──────────┬─────┘
                                  │          │
                    ┌─────────────┘          └─────────────┐
                    ▼                                      ▼
        ┌─────────────────────┐              ┌───────────────────────┐
        │   数据采集层          │  HTTP/       │   engine/             │
        │   data_fetcher.py    │  subprocess  │   策略引擎             │
        │                     │◄───────────►│                       │
        │   ┌───────────────┐ │    JSON      │   ┌─────────────────┐ │
        │   │ 新浪财经 API   │ │              │   │ QLibPredictor   │ │
        │   │ akshare       │ │              │   │ Alpha158因子     │ │
        │   │ 腾讯API(回退)  │ │              │   │ LGBModel/GBR    │ │
        │   │ yfinance(回退) │ │              │   │ 三级回退机制     │ │
        │   └───────────────┘ │              │   └─────────────────┘ │
        │                     │              │                       │
        │   文件缓存 (JSON)    │              │   ┌─────────────────┐ │
        │   数据质量验证器     │              │   │ 18核心策略       │ │
        │   数据源熔断器       │              │   │ 6大类别          │ │
        └─────────────────────┘              │   │ 信号融合路由     │ │
                    │                        │   └─────────────────┘ │
                    ▼                        │                       │
        ┌─────────────────────┐              │   ┌─────────────────┐ │
        │   报告生成层          │              │   │ 三级风控         │ │
        │   report_generator  │              │   │ 事前/事中/事后   │ │
        │   五维日报组装       │              │   └─────────────────┘ │
        └─────────────────────┘              └───────────────────────┘
                    │
        ┌───────────▼───────────┐
        │      LLM 分析层        │
        │   llm_service.py      │
        │   Qwen3-8B API 调用   │
        │   大师兄分析框架       │
        │   三层传导解读         │
        └───────────────────────┘
                    │
        ┌───────────▼───────────┐
        │      推送层            │
        │   feishu_service.py   │
        │   飞书卡片渲染 + 发送  │
        └───────────────────────┘
```

### 1.2 双系统职责对比

| 维度 | bot/（日报主系统） | engine/（策略引擎） |
|:-----|:-------------------|:--------------------|
| **技术栈** | FastAPI + APScheduler + httpx | FastAPI 微服务 + sklearn/pandas |
| **端口** | 8000 | 8765（信号微服务） |
| **核心职责** | 数据采集、日报生成、LLM 分析、飞书推送 | 量化策略计算、QLib 预测、信号融合、风控 |
| **依赖环境** | 独立 venv | 独立 venv（可能含 QLib/lightgbm） |
| **通信方式** | HTTP POST /analyze（主），subprocess（回退） | 暴露 RESTful API |
| **数据存储** | SQLite (portfolio.db)、文件缓存 | 模型缓存 (joblib)、SQLite |
| **调度方式** | APScheduler AsyncIOScheduler | signal_service 请求驱动 |

### 1.3 通信协议

```
bot  ──── HTTP POST /analyze ──────►  engine (signal_service:8765)
      ◄──── JSON response ───────────

回退路径（当 HTTP 失败或 FALLBACK_MODE=1）:
bot  ──── subprocess ──────────────►  python get_strategy_signals.py
      ◄──── stdout JSON ────────────
```

---

## 2. 五维框架说明

五维框架是明策宏观分析的核心方法论，将全球宏观数据按 **金 → 油 → 汇 → 债 → G** 五个维度组织，覆盖影响 A 股定价的核心外部变量。

### 2.1 五维总览

| 维度 | 符号 | 覆盖资产 | 数据来源 | 数据源回退 | 缓存 TTL | 分析作用 |
|:-----|:-----|:---------|:---------|:-----------|:---------|:---------|
| **金** | 🥇 | 黄金（美元/盎司）、白银、金银比 | akshare 期货历史 | 新浪财经 | 1800s (30min) | 避险情绪、通胀预期、美元信用锚 |
| **油** | 🛢️ | 布伦特原油、WTI 原油、国内商品期货（螺纹钢/铜/铁矿石） | akshare 期货 | 新浪财经 | 1800s (30min) | 通胀传导、生产成本、PPI 先行指标 |
| **汇** | 💱 | 美元指数、USD/CNY、EUR/USD、USD/JPY、GBP/USD | akshare（汇率） | 新浪财经 | 1800s (30min) | 人民币定价、资本流动、出口竞争力 |
| **债** | 📜 | 美债 10Y/2Y 收益率、中债收益率、Shibor、LPR、中美利差 | akshare | — | 3600s (1h) | 全球流动性定价、无风险利率基准、期限利差信号 |
| **G** | 🌐 | VIX、BDI 波罗的海干散货指数、加密货币（BTC/ETH）、北向资金、跨市场比价 | akshare + CoinGecko API + 新浪 | — | 900s (15min) | 市场恐慌/风险偏好、全球贸易景气、聪明钱流向 |

### 2.2 各维度详解

#### 金（Gold）

- **数据采集**：`get_global_macro()` → `gold` / `silver` 字段
- **核心指标**：伦敦金现价（美元/盎司）、伦敦银现价、金银比（Gold/Silver Ratio）
- **分析作用**：
  - 黄金是避险资产标杆，金价上涨 → 市场避险情绪升温 → 利空风险资产
  - 金价与美元指数通常负相关，反映美元信用体系信心
  - 金银比突破 80 通常预示经济衰退风险
- **数据来源**：`ak.futures_foreign_hist()` 获取伦敦金/银期货数据

#### 油（Oil）

- **数据采集**：`get_global_macro()` → `brent_oil` / `wti_oil` + `get_futures_data()`
- **核心指标**：布伦特原油、WTI 原油、国内螺纹钢/铜/铁矿石期货涨跌幅
- **分析作用**：
  - 原油是"工业血液"，油价上涨 → 生产成本上升 → 通胀压力 → 货币政策收紧预期
  - 布伦特-WTI 价差反映区域供需差异
  - 国内商品期货反映"中国需求"强度
- **数据来源**：`ak.futures_foreign_hist()` + `ak.futures_hist_daily()`（国内）

#### 汇（FX）

- **数据采集**：`get_global_macro()` → `usd_index` / 汇率篮子
- **核心指标**：美元指数、USDCNY（在岸/离岸）、欧元/日元/英镑
- **分析作用**：
  - 美元指数走强 → 新兴市场资金外流压力 → 利空 A 股
  - USDCNY 是 A 股核心变量：人民币升值 → 外资流入 → 利好 A 股（尤其消费/金融）
  - 汇率篮子综合判断美元强弱周期
- **数据来源**：`ak.spot_quote()` 获取实时汇率

#### 债（Bond）

- **数据采集**：`get_global_macro()` → `us_bond_yield` / `shibor` / `lpr`
- **核心指标**：美债 10Y 收益率、中美 10Y 利差、Shibor 1W、LPR 1Y/5Y
- **分析作用**：
  - 美债收益率是全球资产定价的"锚"：收益率上升 → 成长股估值承压
  - 中美利差（中国-美国）收窄或倒挂 → 资本外流压力
  - Shibor/LPR 反映国内流动性松紧
- **数据来源**：`ak.bond_zh_us_rate()` + `ak.shibor_report()` + `ak.lpr_1y()` / `ak.lpr_5y()`

#### G（Global & Derivatives）

- **数据采集**：`get_global_macro()` → `vix` / `bdi` + `get_crypto_data()` + `get_north_flow()`
- **核心指标**：VIX 恐慌指数、BDI 航运指数、BTC/ETH 价格、北向资金净流入
- **分析作用**：
  - VIX > 30 → 市场恐慌 → 系统性风险预警
  - BDI 上涨 → 全球贸易活跃 → 利好航运/出口板块
  - 加密货币反映全球流动性溢出和风险偏好
  - 北向资金是 A 股"聪明钱"风向标
- **数据来源**：`ak.index_us_hist()`（VIX）+ `ak.scrub_index()`（BDI）+ CoinGecko API + `ak.stock_hsgt_north_net_flow_in_hist()`

### 2.3 五维联动分析

```
金 ↑ + 油 ↑ = 滞胀风险（黄金抗通胀 + 油价推升成本）
汇 ↑（美元强）+ 债 ↑（美债收益率升）= 全球流动性紧缩 → 利空新兴市场
金 ↑ + 汇 ↓（美元弱）= 避险但不紧缩 → 黄金股利好
油 ↓ + BDI ↓ = 全球需求走弱 → 周期股承压
债 ↓（美债收益率降）+ 汇 ↓（美元弱）= 全球宽松 → 利好成长股
```

---

## 3. 三层传导框架

LLM 大师兄分析采用 **宏观 → 行业 → 个股** 三层传导框架，确保投资建议从宏观到微观逻辑通顺。

### 3.1 框架结构

```
┌─────────────────────────────────────────────────┐
│                  第一层：宏观                      │
│  输入：五维数据（金/油/汇/债/G）                 │
│  输出：宏观环境判断 + 风险偏好评级               │
│  例如："美债收益率上行+美元走强→流动性收紧"      │
└──────────────────────┬──────────────────────────┘
                       │ 传导
┌──────────────────────▼──────────────────────────┐
│                  第二层：行业                      │
│  输入：第一层宏观判断 + 板块轮动数据             │
│  输出：受影响行业 + 传导路径                     │
│  例如："流动性收紧→成长板块承压，价值防御占优"   │
└──────────────────────┬──────────────────────────┘
                       │ 映射
┌──────────────────────▼──────────────────────────┐
│                  第三层：个股                      │
│  输入：第二层行业判断 + 自选股基本面 + 策略信号  │
│  输出：具体操作建议（加仓/减仓/持有）            │
│  例如："茅台(600519)：消费复苏+外资回流→推荐持有"│
└─────────────────────────────────────────────────┘
```

### 3.2 传导流程详解

```
数据采集（五维）
    │
    ▼
LLM 宏观分析 ──────────────────────────► 宏观判断输出
    │                                         │
    │ 宏观→行业映射                            │
    ▼                                         ▼
LLM 行业分析（板块轮动+行业影响） ──────────► 行业判断输出
    │                                         │
    │ 行业→个股映射                           │
    ▼                                         ▼
LLM 个股分析（+策略信号融合） ──────────────► 操作建议输出
    │
    ▼
卡片渲染 + 飞书推送
```

### 3.3 代码实现

- **位置**：`bot/services/llm_service.py`
- **函数**：`generate_commentary()`、`generate_five_dimension_analysis()`
- **Prompt 框架**：基于"大师兄经济分析"知识框架（SKILL.md），包含：
  - 五维矩阵联动分析 prompt
  - 三层传导推理 prompt
  - 操作建议结构化输出 prompt
- **降级策略**：LLM 不可用时自动走结构化数据模板，使用规则逻辑生成简化版建议

### 3.4 策略信号融合（与三层传导并行）

```
18个量化策略信号
    │
    ▼
信号融合路由（SignalRouter）
    │ 权重：QLib 0.6 + LLM 0.4
    ▼
综合信号（BUY/SELL/HOLD + 置信度）
    │
    ▼
注入日报 + 飞书卡片策略信号区
```

---

## 4. 数据采集层

### 4.1 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                数据采集层 (data_fetcher.py)               │
│                                                         │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│   │ 新浪财经  │  │ akshare  │  │ 腾讯API  │  │yfinance│ │
│   │ (个股K线) │  │(宏观/指数│  │ (个股回退)│  │(美股回 │ │
│   │          │  │ /板块)   │  │          │  │ 退)    │ │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘  └───┬────┘ │
│        │              │              │             │      │
│        ▼              ▼              ▼             ▼      │
│   ┌──────────────────────────────────────────────────┐  │
│   │             4级数据回退（_try_sources）            │  │
│   │  Level 1: 首选源 → Level 2: 回退源 → ...        │  │
│   └──────────────────────┬──────────────────────────┘  │
│                          │                               │
│   ┌──────────────────────▼──────────────────────────┐  │
│   │         文件缓存系统（FileCache）                  │  │
│   │  key_{date}.json | 按模块TTL | 按天分文件         │  │
│   └──────────────────────┬──────────────────────────┘  │
│                          │                               │
│   ┌──────────────────────▼──────────────────────────┐  │
│   │      数据质量验证器（DataQualityValidator）        │  │
│   │  完整性/准确性/一致性/时效性/有效性 五维评估       │  │
│   └──────────────────────┬──────────────────────────┘  │
│                          │                               │
│   ┌──────────────────────▼──────────────────────────┐  │
│   │      数据源监控器（DataSourceMonitor）            │  │
│   │  熔断器模式：连续失败≥3次 → 自动跳过             │  │
│   └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 4.2 多源回退架构

数据采集采用多源回退策略，每个数据项支持主源 + 多级回退，确保单数据源故障时系统持续可用。

#### 回退链路

```
主源(akshare) → 回退1(新浪财经) → 回退2(东方财富) → 回退3(海外交易所API)
```

核心设计原则：
- **逐级回退**：主源失败自动切换下一级，直到获取到有效数据
- **价格合理性校验**：每个数据项都有区间范围检查，异常值自动丢弃并触发回退
- **缓存机制**：文件缓存系统避免频繁请求，按模块设置不同 TTL
- **熔断器保护**：连续失败≥3次的数据源自动跳过，防止无效重试

#### 各数据项回退详情

| 数据项 | 主源 | 回退1 | 回退2 | 回退3 |
|:-------|:-----|:------|:------|:------|
| 全球宏观数据（金/油/汇/债/G） | akshare | 新浪期货 | 新浪外汇 | 东方财富 |
| 美债收益率 | akshare `bond_zh_us_rate`（按列名直接取值） | — | — | — |
| VIX恐慌指数 | akshare | 新浪期货 `hf_VX` | — | — |
| USD/CNY汇率 | akshare | 新浪外汇 `fx_susdcny` | — | — |
| 北向资金 | akshare | 东方财富 `kamt` 接口 | — | — |
| ETH价格 | CoinGecko API | Gate.io API | — | — |
| 个股K线 | 新浪财经 HTTP API | 腾讯财经 API | yfinance | 缓存历史 |
| A股指数 | akshare `ak.stock_zh_index_daily()` | 新浪逐只获取 | — | — |
| 美股指数 | 新浪逐只获取 | — | — | — |
| 宏观(金/油) | akshare 期货历史 | 新浪财经 | — | — |
| 汇率 | akshare `ak.spot_quote()` | 新浪财经 | — | — |
| 板块轮动 | akshare `ak.stock_board_industry_hist()` | — | — | — |

#### 数据完整率

当前数据完整率达 **90%**，仅美元指数因网络限制无法获取。各数据项获取情况：

| 数据项 | 状态 | 说明 |
|:-------|:-----|:-----|
| 黄金/白银 | ✅ 可获取 | akshare 期货历史 + 新浪回退 |
| 布伦特/WTI原油 | ✅ 可获取 | akshare 期货历史 + 新浪回退 |
| 美债收益率 | ✅ 可获取 | akshare `bond_zh_us_rate` 按列名直接取值 |
| VIX恐慌指数 | ✅ 可获取 | akshare + 新浪期货 `hf_VX` 回退 |
| USD/CNY汇率 | ✅ 可获取 | akshare + 新浪外汇 `fx_susdcny` 回退 |
| 北向资金 | ✅ 可获取 | akshare + 东方财富 `kamt` 接口回退 |
| ETH价格 | ✅ 可获取 | CoinGecko + Gate.io API 回退 |
| 美元指数 | ❌ 无法获取 | 网络限制，暂无可用数据源 |

**实现机制**：`data_fetcher.py` 中的 `_try_sources(*source_funcs)` 函数：

```python
def _try_sources(*source_funcs):
    """尝试多个数据源，返回第一个成功且非空的结果。"""
    for idx, func in enumerate(source_funcs):
        source_name = func.__name__
        # 检查熔断器：如果该源连续失败≥3次，跳过
        if monitor.should_skip(source_name):
            continue
        try:
            result = func()
            if result is not None and not result.empty:
                monitor.record_success(source_name)
                return result
        except Exception:
            monitor.record_failure(source_name, str(e))
    return None  # 全部失败
```

### 4.3 缓存系统

**位置**：`bot/core/cache.py` — `FileCache` 类

| 特性 | 说明 |
|:-----|:------|
| **存储格式** | JSON 文件，按 `{safe_key}_{date}.json` 命名 |
| **TTL 机制** | 每个 key 独立 TTL，写入时记录 `_cached_at` 时间戳 |
| **过期清理** | `get()` 时惰性检查 + `clean_expired()` 定时清理（48h+） |
| **模块化 TTL** | 不同数据模块使用不同的 TTL 配置 |

**各模块 TTL 配置**：

| 模块 | TTL | 说明 |
|:-----|:----|:-----|
| `market` | 300s (5min) | A股行情（盘中高频） |
| `macro` | 1800s (30min) | 宏观数据（金油汇债G） |
| `north_flow` | 900s (15min) | 北向资金 |
| `etf` | 3600s (1h) | ETF 数据 |
| `global_macro` | 1800s (30min) | 全球宏观 |
| `leading` | 3600s (1h) | 龙头股数据 |

### 4.4 数据质量验证

**位置**：`bot/core/data_quality.py`

**五维数据质量指标**：

| 维度 | 说明 | 权重 |
|:-----|:------|:-----|
| 完整性 (Completeness) | 必填字段是否齐全 | 25% |
| 准确性 (Accuracy) | 数据值是否在合理范围 | 25% |
| 一致性 (Consistency) | 多源数据是否一致（如北向净流=沪+深） | 20% |
| 时效性 (Timeliness) | 数据是否为最新交易日 | 15% |
| 有效性 (Validity) | 非空、非 NaN、非 Inf | 15% |

**验证规则示例**：

| 检查项 | 规则 | 处理方式 |
|:-------|:-----|:---------|
| 指数值范围 | 上证[2500, 5000]、深证[8000, 18000] | 超出→警告，数据仍可用 |
| 涨跌幅范围 | ±20% | 超出→警告 |
| 成交额 | ≥ 0 | 负值→不可用 |
| 北向资金一致性 | 净流 ≈ 沪股通 + 深股通（误差<0.1亿） | 不一致→警告 |
| 历史一致性 | Z-score > 3 视为异常偏离 | 警告 |
| 空值/NaN | 关键字段为空→不可用 | 不可用 |

**质量等级**：

| 综合评分 | 等级 | 响应 |
|:---------|:-----|:-----|
| ≥ 0.95 | EXCELLENT | 正常使用 |
| ≥ 0.85 | GOOD | 正常使用 |
| ≥ 0.70 | ACCEPTABLE | 正常使用 |
| ≥ 0.50 | WARNING | 记录告警 |
| > 0 | CRITICAL | 切换备用数据源 |

### 4.5 熔断器（Circuit Breaker）

**位置**：`bot/core/data_quality.py` — `DataSourceMonitor` 类

**熔断机制**：

```
正常状态 ── 连续失败 ≥3 次 ──► 开启（跳过该数据源）
    ▲                              │
    │                              │ 成功调用其他源
    │                              │ 或手动 reset()
    └──────── 恢复正常 ────────────┘
```

- **连续失败阈值**：3 次（可配置）
- **降级阈值**：失败率 > 30%（失败数 > 成功数 × 0.3）→ 状态降为 `DEGRADED`
- **恢复方式**：`reset(source_name)` 手动重置，或下次调度自动跳过

---

## 5. 策略引擎

### 5.1 引擎架构

```
┌────────────────── 策略引擎 (engine/) ─────────────────┐
│                                                        │
│   ┌────────────────── 外部接口 ───────────────────┐    │
│   │                                               │    │
│   │  signal_service.py (HTTP微服务 :8765)          │    │
│   │  POST /analyze → 策略分析                     │    │
│   │  POST /health  → 健康检查                     │    │
│   │                                               │    │
│   │  get_strategy_signals.py (CLI入口)             │    │
│   │  python get_strategy_signals.py --symbol XXX   │    │
│   └───────────────────────────────────────────────┘    │
│                                                        │
│   ┌──────────────── 核心模块 ────────────────────┐    │
│   │                                               │    │
│   │  ┌─────────────────────────────────────────┐  │    │
│   │  │  QLibPredictor（三级回退）                │  │    │
│   │  │  Level 1: QLib Alpha158 + LGBModel      │  │    │
│   │  │  Level 2: sklearn (Alpha158模拟+GBR)    │  │    │
│   │  │  Level 3: Rule-based (MA/布林/RSI)      │  │    │
│   │  └──────────────────┬──────────────────────┘  │    │
│   │                     │                          │    │
│   │  ┌──────────────────▼──────────────────────┐  │    │
│   │  │  18个核心策略（6大类）                    │  │    │
│   │  │  strategies_optimized.py / strategies.py │  │    │
│   │  └──────────────────┬──────────────────────┘  │    │
│   │                     │                          │    │
│   │  ┌──────────────────▼──────────────────────┐  │    │
│   │  │  信号融合路由 (SignalRouter)              │  │    │
│   │  │  QLib权重0.6 + LLM权重0.4                │  │    │
│   │  │  输出：BUY/SELL/HOLD + 置信度             │  │    │
│   │  └─────────────────────────────────────────┘  │    │
│   │                                               │    │
│   │  ┌─────────────────────────────────────────┐  │    │
│   │  │  三级风控 (RiskManager)                  │  │    │
│   │  │  事前：单股≤30%、集中度≤40%              │  │    │
│   │  │  事中：日亏3%预警、5%熔断                │  │    │
│   │  │  事后：最大回测、T+1限制                 │  │    │
│   │  └─────────────────────────────────────────┘  │    │
│   └───────────────────────────────────────────────┘    │
│                                                        │
└────────────────────────────────────────────────────────┘
```

### 5.2 18策略 × 6大类

| 类别 | 策略数 | 策略列表 | 适用市场状态 |
|:-----|:-------|:---------|:------------|
| **趋势跟踪** | 4 | MA 交叉、MACD、布林带突破、SAR 抛物线 | 单边趋势市 |
| **均值回归** | 4 | RSI 超买超卖、KDJ、均值回归、MFI 资金流 | 震荡市 |
| **动量策略** | 3 | 动量策略、VWAP、OBV 能量潮 | 趋势初期/中期 |
| **突破策略** | 3 | 双轨突破 (Dual Thrust)、海龟交易、支撑阻力 | 突破确认行情 |
| **轮动/情绪** | 2 | 行业轮动、情绪周期、龙头战法 | 板块轮动/游资行情 |
| **主动交易** | 2 | 波段操作、价值投资 | 中长期配置 |

**代码位置**：

- `engine/qlib_vnpy_platform/core/strategies.py` — 原始 18 策略实现（~1647 行）
- `engine/qlib_vnpy_platform/core/strategies_optimized.py` — 优化版 18 核心策略

### 5.3 QLib 三级回退

**位置**：`engine/qlib_vnpy_platform/core/qlib_predictor.py`

```
Level 1: QLib (full)
────────────────────────────────────────────────────────────
  依赖: pyqlib + lightgbm + Alpha158 数据
  流程: Alpha158 因子计算 → LGBModel 训练/预测
  状态: ⚠️ 可选安装（编译耗时）
  数据: ~/.qlib/qlib_data/cn_data/

Level 2: sklearn（当前默认）
────────────────────────────────────────────────────────────
  依赖: scikit-learn
  流程: 手动计算 Alpha158 因子（36个特征）→ GradientBoostingRegressor
  状态: ✅ 默认使用
  精度: 略低于完整 QLib，但无需额外安装

Level 3: Rule-based（最终兜底）
────────────────────────────────────────────────────────────
  依赖: 无
  流程: MA交叉 + 布林带 + RSI 等简单技术规则
  状态: ✅ 始终可用
  精度: 较低，确保系统永不空转
```

**三级回退自动降级代码逻辑**：

```python
class QLibPredictor:
    def _detect_capabilities(self):
        # 1. 检测 QLib
        try:
            import qlib
            self._qlib_available = True
            self._mode = MODE_QLIB
        except ImportError:
            pass

        # 2. 回退到 sklearn
        if not self._qlib_available:
            try:
                from sklearn.ensemble import GradientBoostingRegressor
                self._sklearn_available = True
                self._mode = MODE_SKLEARN
            except ImportError:
                pass

        # 3. 最终回退到规则
        if self._mode == MODE_RULE:
            logger.info("📋 切换到规则模式（简单技术指标）")
```

### 5.4 信号融合

**位置**：`engine/qlib_vnpy_platform/core/signal_router.py`

**SignalRouter 信号融合公式**：

```
QLib_score = (QLib_pred - 0.5) × 2          # [-1, 1]
LLM_score  = signal_map[LLM_direction] × confidence  # [-1, 1]
  signal_map = {"BUY": 1.0, "SELL": -1.0, "HOLD": 0.0}

final_score = w_qlib × QLib_score + w_llm × LLM_score
  w_qlib = 0.6, w_llm = 0.4

direction:
  final_score > 0.2  → BUY
  final_score < -0.2 → SELL
  其余                → HOLD

confidence = abs(final_score)
```

**信号输出结构**：

```json
{
  "symbol": "SZ002594",
  "direction": "BUY",
  "score": 0.45,
  "confidence": 0.45,
  "current_price": 285.5,
  "qlib_score": 0.6,
  "llm_score": 0.2,
  "target_price": 310.0,
  "stop_loss": 260.0,
  "risk_level": "MEDIUM",
  "reason": "...",
  "key_factors": ["..."]
}
```

---

## 6. 推送层

### 6.1 飞书卡片结构

**位置**：`bot/services/feishu_service.py`（822 行，26 个卡片构建函数）

**卡片类型**：

| 卡片类型 | 构建函数 | 适用时段 | 内容 |
|:---------|:---------|:---------|:-----|
| 指数卡 | `build_index_card()` | 全时段 | A 股四大指数行情 |
| 五维卡 | `build_five_dim_card()` | early/close | 金/油/汇/债/G 数据 |
| 策略信号卡 | `build_strategy_signals_card()` | morning/noon/close | 自选股买卖信号 |
| ETF 卡 | `build_etf_card()` | close | ETF 涨跌排行 |
| 基金卡 | `build_fund_monitor_card()` | 15:35 | 基金净值变化 |
| 异动提醒卡 | `build_alert_card()` | 盘中 | 价格/成交量异动 |

**卡片结构模板**（飞书消息卡片 JSON）：

```json
{
  "msg_type": "interactive",
  "card": {
    "header": {
      "title": {"tag": "plain_text", "content": "📰 明策早报 2026-06-16"},
      "template": "blue"
    },
    "elements": [
      {"tag": "markdown", "content": "## 📊 A 股核心行情\n..."},
      {"tag": "markdown", "content": "## 🥇 五维矩阵\n..."},
      {"tag": "markdown", "content": "## 🧠 大师兄解读\n..."},
      {"tag": "note", "elements": [
        {"tag": "plain_text", "content": "明策系统 · 2026-06-16 09:10:00"}
      ]}
    ]
  }
}
```

**飞书鉴权流程**：

```
bot 启动
    │
    ▼
get_tenant_token()
    │ POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
    │ {app_id, app_secret}
    ▼
缓存 tenant_access_token（有效期 7200s，提前 600s 刷新）
    │
    ▼
send_card_message(chat_id, card)
    │ POST https://open.feishu.cn/open-apis/im/v1/messages
    │ Authorization: Bearer {token}
    ▼
飞书群收到推送
```

### 6.2 APScheduler 5时段调度

**位置**：`bot/app/main.py` — `AsyncIOScheduler`

| 时段 | 时间 | 任务函数 | 版本标识 | 推送内容 | 策略信号 |
|:-----|:-----|:---------|:---------|:---------|:---------|
| 🏙️ 早间 | 08:00 | `scheduled_report("early")` | `early` | 隔夜全球简报：美股/黄金/原油/汇率/美债/BDI | ❌ |
| ☀️ 早盘 | 09:10 | `scheduled_report("morning")` | `morning` | 早盘准备：A 股盘前+板块热点+昨日回顾 | ✅ 预览 |
| 🌤️ 午间 | 11:35 | `scheduled_report("noon")` | `noon` | 午间复盘：上午盘面+板块轮动+异动提醒 | ✅ 预览 |
| 🏁 收盘 | 15:10 | `scheduled_report("close")` | `close` | 收盘总结：全天数据+五维分析+策略信号+AI 解读 | ✅ 完整 |
| 📊 基金 | 15:35 | `scheduled_fund_monitor()` | `fund` | 基金净值变化跟踪 | ❌ |

**交易日检测**：

```python
def _is_trading_day() -> bool:
    today = date.today()
    # 周末检查
    if today.weekday() not in (0, 1, 2, 3, 4):
        return False
    # 中国法定节假日（chinesecalendar 库）
    if is_holiday(today):
        return False
    return True
```

**APScheduler 注册代码**：

```python
scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

scheduler.add_job(scheduled_report, "cron", args=["early"],  hour=8,  minute=0)
scheduler.add_job(scheduled_report, "cron", args=["morning"], hour=9,  minute=10)
scheduler.add_job(scheduled_report, "cron", args=["noon"],    hour=11, minute=35)
scheduler.add_job(scheduled_report, "cron", args=["close"],   hour=15, minute=10)
scheduler.add_job(scheduled_fund_monitor, "cron", hour=15, minute=35)
```

### 6.3 推送失败处理

```
推送失败
    │
    ├── 飞书 API 错误（token 过期、权限不足）
    │     └── 自动刷新 token 重试（最多 3 次）
    │
    ├── 网络超时
    │     └── 重试 2 次，间隔 5s
    │
    └── 数据生成失败
          └── 通过 alert_service 发送告警到飞书
```

---

## 7. 告警链路

### 7.1 alert_service.py 完整流程

**位置**：`bot/services/alert_service.py`（45 行）

```
系统关键链路失败
    │
    ▼
send_alert(message, level)
    │
    ├── level="warning"    → 蓝色卡片，可恢复问题
    ├── level="error"      → 黄色卡片，需要关注
    └── level="critical"   → 红色卡片，需要立即处理
    │
    ▼
检查 settings.ALERT_WEBHOOK_URL
    │
    ├── 未配置 → 仅日志输出（logger.warning）
    │
    └── 已配置 → POST 到飞书 Webhook
                   │
                   ▼
            飞书群收到告警卡片
```

**告警触发场景**：

| 场景 | 级别 | 告警内容 | 触发位置 |
|:-----|:-----|:---------|:---------|
| 日报生成失败 | error | `📰 日报 [version] 生成失败` | `app/main.py` → `scheduled_report()` |
| LLM 分析超时 | warning | `LLM 分析超时，使用结构化模板` | `services/llm_service.py` |
| 数据采集失败 | warning | `数据源 [name] 连续失败 [n] 次` | `services/data_fetcher.py` |
| 策略引擎不可用 | error | `策略引擎调用失败，使用缓存数据` | `services/strategy_adapter.py` |
| 飞书推送失败 | error | `飞书消息推送失败：{error}` | `services/feishu_service.py` |
| 熔断器触发 | warning | `数据源 [name] 已熔断，自动跳过` | `core/data_quality.py` |

### 7.2 告警卡片示例

```
┌──────────────────────────────────┐
│  ⚠️ 明策告警 [error]              │  ← 红色/黄色/蓝色 header
│                                  │
│  📰 日报 [close] 生成失败         │
│  ┌────────────────────────┐      │
│  │ ValueError: 上证指数    │      │
│  │ 数据为空                │      │
│  └────────────────────────┘      │
│                                  │
│  明策系统 · 2026-06-16 15:10:30 │
└──────────────────────────────────┘
```

---

## 8. 服务依赖关系图

### 8.1 模块依赖图

```
                     ┌───────────────┐
                     │  config/      │
                     │  settings.py  │  ← pydantic-settings (.env)
                     └───────┬───────┘
                             │ 被所有模块依赖
                             ▼
┌────────────┐    ┌─────────────────────┐    ┌──────────────┐
│ core/      │◄───│    services/        │───►│  models/    │
│ database   │    │                     │    │  schemas    │
│ cache      │    │  data_fetcher       │    └──────────────┘
│ data_      │    │  report_generator   │
│ quality    │    │  llm_service        │
│ utils      │    │  feishu_service     │
└────────────┘    │  strategy_adapter   │
                  │  alert_service      │
                  │  decision_engine    │
                  │  portfolio_manager  │
                  │  feishu_bot_handler │
                  │  fund_monitor       │
                  │  wisdom_analyzer    │
                  └─────────┬───────────┘
                            │
                    ┌───────▼───────┐
                    │   app/main    │
                    │   FastAPI +   │
                    │  APScheduler  │
                    └───────────────┘
```

### 8.2 外部依赖

```
┌──────────────────────────────────────────────────────┐
│                   外部服务依赖                          │
├──────────────────────────────────────────────────────┤
│  ┌───────────────────┐                               │
│  │  新浪财经 API      │  ── 个股K线、指数、期货数据    │
│  │  http://hq.sinajs │                               │
│  └───────────────────┘                               │
│                                                       │
│  ┌───────────────────┐                               │
│  │  akshare          │  ── 宏观/板块/北向/美股/美债   │
│  │  (开源 Python 库) │     统一接口，多数据源聚合      │
│  └───────────────────┘                               │
│                                                       │
│  ┌───────────────────┐                               │
│  │  飞书 Open API     │  ── 消息推送、机器人指令       │
│  │  open.feishu.cn   │     需 tenant_access_token     │
│  └───────────────────┘                               │
│                                                       │
│  ┌───────────────────┐                               │
│  │  LLM API         │  ── 大师兄分析                  │
│  │  SiliconFlow      │     模型: Qwen3-8B             │
│  └───────────────────┘                               │
│                                                       │
│  ┌───────────────────┐                               │
│  │  QLib (可选)      │  ── Level 1 预测器             │
│  │  Microsoft/QLib   │     Alpha158 + LGBModel        │
│  └───────────────────┘                               │
│                                                       │
│  ┌───────────────────┐                               │
│  │  CoinGecko API    │  ── 加密货币价格               │
│  │  api.coingecko.com│     BTC/ETH 行情               │
│  └───────────────────┘                               │
└──────────────────────────────────────────────────────┘
```

### 8.3 内部调用关系

```
FastAPI app (main.py)
    │
    ├── generate_daily_report(version)
    │     ├── data_fetcher.get_market_overview()        ← 指数行情
    │     ├── data_fetcher.get_macro_data()              ← 宏观五维
    │     ├── data_fetcher.get_north_flow()              ← 北向资金
    │     ├── data_fetcher.get_global_macro()            ← 全球宏观
    │     ├── data_fetcher.get_us_market()               ← 美股
    │     ├── data_fetcher.get_crypto_data()             ← 加密货币
    │     ├── data_fetcher.get_futures_data()            ← 国内期货
    │     ├── data_fetcher.get_etf_data()               ← ETF
    │     ├── data_fetcher.get_leading_stocks()         ← 龙头股
    │     ├── data_fetcher.get_bse_data()               ← 北交所
    │     ├── data_fetcher.detect_alerts()              ← 异动检测
    │     ├── strategy_adapter.get_all_signals()        ← 策略信号
    │     │     ├── HTTP → signal_service:8765/analyze
    │     │     └── subprocess → get_strategy_signals.py
    │     └── llm_service.generate_commentary()         ← LLM 解读
    │           └── HTTP → SiliconFlow API (Qwen3-8B)
    │
    ├── wisdom_analyzer.run_wisdom_analysis(data)       ← 深度分析（触发式）
    │     ├── _detect_wisdom_triggers(data)             ← 触发条件检测
    │     │     └── ≥2个不同类别触发条件满足 → 继续
    │     ├── _build_wisdom_data_summary(data)          ← 精简市场数据摘要
    │     ├── _build_wisdom_prompt(triggers)            ← 动态构建 system prompt
    │     │     └── _load_wisdom_skills() + _extract_decision_rules()  ← 从 bot/skills/wisdom/ 加载7个SKILL.md
    │     ├── _call_llm(system_prompt, user_prompt)     ← DeepSeek LLM 分析
    │     └── _build_wisdom_card(analysis, triggers)    ← 飞书卡片构建
    │           └── feishu_service.send_card_message()  ← 推送飞书群
    │
    └── push_daily_report(data)
          └── feishu_service.send_card_message()
                └── HTTP POST → 飞书 Open API

scheduled_fund_monitor()
    └── FundMonitor.run_monitor()
          └── feishu_service.send_card_message()

飞书 @机器人指令
    └── feishu_bot_handler.handle_message()
          ├── portfolio_manager → SQLite 读写
          ├── strategy_adapter.get_signals()
          └── "深度分析" → wisdom_analyzer.run_wisdom_analysis()
```

### 8.4 数据流全景

```
                          ┌───────────┐
                          │ 定时触发   │
                          │ 08/09/11/ │
                          │ 15/15:35  │
                          └─────┬─────┘
                                │
                    ┌───────────▼───────────┐
                    │   数据采集 (fetcher)    │
                    │   多源 → 4级回退        │
                    │   缓存 → 质量验证      │
                    │   熔断器保护           │
                    └───────────┬───────────┘
                                │ 结构化数据
                    ┌───────────▼───────────┐
                    │   报告生成 (generator) │
                    │   五维组装 → 策略注入   │
                    │   LLM 分析            │
                    └───────────┬───────────┘
                                │ 报告数据
                    ┌───────────▼───────────┐
                    │   卡片渲染 (feishu)   │
                    │   按维度 → 按类型      │
                    │   卡片 JSON 构建       │
                    └───────────┬───────────┘
                                │ 飞书卡片 JSON
                    ┌───────────▼───────────┐
                    │  飞书 Open API 发送    │
                    │  鉴权 → POST → 推送   │
                    └───────────┬───────────┘
                                │
                          ┌─────▼─────┐
                          │  飞书群    │
                          │ 每日推送   │
                          └───────────┘

                    ┌───────────────────────────────────────┐
                    │         深度分析分支（触发式）           │
                    │                                       │
                    │  日报数据（existing_data）              │
                    │       │                               │
                    │       ▼                               │
                    │  _detect_wisdom_triggers(data)         │
                    │       │                               │
                    │       ├── 触发条件不足 → 返回 skipped   │
                    │       │                               │
                    │       │ 触发条件满足（≥2个不同类别）     │
                    │       ▼                               │
                    │  _build_wisdom_data_summary(data)      │
                    │       │                               │
                    │       ▼                               │
                    │  _build_wisdom_prompt(triggers)        │
                    │    + _load_wisdom_skills() + _extract_decision_rules()      │
                    │       │                               │
                    │       ▼                               │
                    │  _call_llm(system_prompt, user_prompt) │
                    │    DeepSeek LLM 分析                   │
                    │       │                               │
                    │       ▼                               │
                    │  _build_wisdom_card(analysis, triggers) │
                    │       │                               │
                    │       ▼                               │
                    │  feishu_service.send_card_message()    │
                    │       │                               │
                    │       ▼                               │
                    │  飞书群（深度分析卡片）                  │
                    └───────────────────────────────────────┘
```

---

## 9. 炒股的智慧深度分析

### 9.1 模块概述

- **位置**：`bot/services/wisdom_analyzer.py`
- **功能**：市场异动时自动触发深度分析
- **特点**：触发式（非定时），需要至少 2 个不同类别触发条件同时满足
- **名称说明**："炒股的智慧"是陈江挺著的投资经典书籍名称，模块基于该书的蒸馏知识库（books2skill），包含7个决策SKILL
- **知识库路径**：`bot/skills/wisdom/`
### 9.2 触发条件检测

5 类触发条件：

| 类别 | 触发条件 | 阈值/规则 |
|:-----|:---------|:----------|
| **1. 市场周期触发** | 金银比 > 85 | 大市判断：宏观失衡信号（书中第二章） |
| | 北向流出 > 80 亿 | 外资大幅撤离，大市转弱信号 |
| | 美债 10Y-2Y 倒挂 | 收益率曲线倒挂，经济衰退预警 |
| | 金油背离 | 黄金与原油走势背离，周期错位 |
| **2. 入场信号触发** | 大市值个股涨跌幅 ≥ 5% | 临界点突破：权重股剧烈波动（书中第四章） |
| **3. 风险预警触发** | VIX > 25 | 止损铁律：市场恐慌加剧（书中第五章） |
| | BDI < 500 | 全球贸易萎缩，基本面恶化 |
| | M2 增速 < 6% | 流动性收紧，资金面风险 |
| **4. 心理触发** | A 股指数涨跌幅 ≥ 2% | 六大心理陷阱：市场极端情绪（书中第六章） |
| | BTC 涨跌幅 ≥ 8% | 加密市场剧烈波动，贪婪与恐惧 |
| **5. 泡沫触发** | 政策关键词匹配 | 抓住大机会：政策催化信号（书中第七章） |

**激活规则**：至少 2 个不同类别的触发条件同时满足

### 9.3 分析框架

基于陈江挺《炒股的智慧》蒸馏的7个决策SKILL：

| SKILL 名称 | 对应分析维度 | 书中来源 |
|:-----------|:-------------|:---------|
| `stock-entry-decision` | 三层过滤入场 | 第二三四章·三层过滤 |
| `stock-stop-loss-decision` | 止损铁律 | 第五章·止损铁律 |
| `stock-position-sizing` | 分层下注 | 第三章·分层下注 |
| `stock-profit-taking-decision` | 让利润奔跑 | 第四章·让利润奔跑 |
| `stock-trailing-stop` | 移动止损/跟踪止损 | 第四章·让利润奔跑 |
| `stock-psychology-check` | 六大心理陷阱 | 第三章+第六章·心理建设 |
| `stock-bubble-participation` | 抓住大机会 | 第七章·抓住大机会 |

**分析框架**：

| 框架维度 | 说明 |
|:---------|:-----|
| **大市判断** | 先判大市方向，再决定操作策略（书中第二章） |
| **临界点四阶段** | 蓄势→突破→加速→衰竭，识别临界点（书中第四章） |
| **三层过滤入场** | 大市→板块→个股，逐层过滤确认（书中第二三四章） |
| **止损铁律** | 入场即设止损，亏损不超过本金的一定比例（书中第五章） |
| **让利润奔跑** | 盈利时耐心持有，用移动止损保护利润（书中第四章） |
| **分层下注** | 分批建仓，不一把梭哈（书中第三章） |
| **六大心理陷阱** | 贪婪、恐惧、希望、后悔、从众、锚定（书中第六章） |

**知识库加载**：从 `bot/skills/wisdom/` 加载7个SKILL.md，提取I段（指令）+ E段（示例）+ B段（背景知识）

### 9.4 出处标注系统

| 标注类型 | 格式 | 示例 |
|:---------|:-----|:-----|
| **数据出处** | `[数据: 来源]` | `[数据: akshare实时行情]` / `[数据: akshare全球宏观]` / `[数据: 央行官方]` |
| **框架出处** | `[框架: 《炒股的智慧》章节]` | `[框架: 《炒股的智慧》第二章·大市判断]` / `[框架: 《炒股的智慧》第四章·临界点四阶段]` / `[框架: 《炒股的智慧》第二三四章·三层过滤]` / `[框架: 《炒股的智慧》第五章·止损铁律]` / `[框架: 《炒股的智慧》第四章·让利润奔跑]` / `[框架: 《炒股的智慧》第三章·分层下注]` / `[框架: 《炒股的智慧》第三章+第六章·心理建设]` / `[框架: 《炒股的智慧》第七章·抓住大机会]` |
| **卡片底部** | 出处说明 + 免责声明 | 每张深度分析卡片均附带 |

### 9.5 数据流

```
日报数据（existing_data）
    │
    ▼
_detect_wisdom_triggers(data) ── 触发条件不足 ──► 返回 skipped
    │ 触发条件满足（≥2个不同类别）
    ▼
_build_wisdom_data_summary(data) ── 精简市场数据摘要
    │
_build_wisdom_prompt(triggers) ── 动态构建 system prompt
    │ + _load_wisdom_skills() 加载7个SKILL.md
    │ + _extract_decision_rules() 提取I段+E段+B段
    ▼
_call_llm(system_prompt, user_prompt) ── DeepSeek LLM 分析
    │
_build_wisdom_card(analysis, triggers) ── 飞书卡片构建
    │
    ▼
feishu_service.send_card_message() ── 推送飞书群
```

### 9.6 严谨性红线

| 红线 | 说明 |
|:-----|:-----|
| **BTC 不是避险资产** | 严禁将 BTC 与黄金并列避险 |
| **板块轮动归因** | 不得无依据归因政策 |
| **数据引用** | 所有分析必须引用具体数据 |
| **禁止倒推** | 严禁"先有结论再找理由" |

### 9.7 API 与交互

| 交互方式 | 说明 |
|:---------|:-----|
| **API** | `POST /api/wisdom/analyze`（需 API Key 认证） |
| **飞书指令** | `@机器人 深度分析` |
| **平静模式** | 市场平静时推送通知 |

---

> **文档维护**：此文档应与代码同步更新。每次架构变更（新增模块、修改数据流、增减外部依赖）后应同步更新对应章节。
