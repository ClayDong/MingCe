# 明策（MingCe）全面修复报告

> 修复时间：2026-06-16  
> 修复范围：10 大专家视角提出的 20+ 风险点

---

## 🔴 严重风险修复（Phase 1）

### 1. ✅ SQLite 并发线程安全问题
- **文件**: `bot/services/portfolio_manager.py`
- **修复**: 从同步 `sqlite3` 全面迁移到 `aiosqlite` + WAL 模式 + `asyncio.Lock`
- **关键变更**:
  - 所有函数改为 `async def`（`add_watchlist`, `get_holdings` 等）
  - 启用 `PRAGMA journal_mode=WAL` 和 `PRAGMA busy_timeout=5000`
  - 添加索引加速查询
  - 添加模糊匹配别名映射（"宁德"→ SZ300750, "BYD"→ SZ002594）

### 2. ✅ RSI signal_strength 计算覆盖 bug
- **文件**: `engine/qlib_vnpy_platform/core/strategies.py`
- **修复**: 每行 `signal_strength` 赋值后立即 `clamp`，不再在循环末尾统一覆盖

### 3. ✅ KDJ 除零风险
- **文件**: `engine/qlib_vnpy_platform/core/strategies.py`
- **修复**: 使用 `.where(denom != 0, np.nan)` 替代 `.replace(0, np.inf)`，避免除零

### 4. ✅ 同步调用阻塞事件循环
- **文件**: `bot/services/report_generator.py`
- **修复**: 12 个同步数据采集调用 → 使用 `asyncio.gather()` + `run_in_executor` 并行执行
- 并行度从串行 12 步 → 2 批并行

### 5. ✅ 进程管理与健康检查
- **文件**: 
  - `bot/mingce.service`（新建）
  - `bot/app/main.py`（增强 /health）
- **新增**: systemd 服务文件（自动重启 + 10s 间隔）
- **增强**: /health 返回数据库/LLM/缓存/调度器/数据源 5 大组件状态

### 6. ✅ 依赖版本锁定
- **文件**: `engine/requirements.txt`
- **修复**: 从 `>=` 改为 `==` 锁定 14 个包版本
- **关键**: `akshare==1.18.62` 固定版本，防止上游破坏性变更

---

## ⚠️ 高风险修复（Phase 2）

### 7. ✅ LLM API Key 前置校验
- **文件**: `bot/services/llm_service.py`
- **新增**: `validate_llm_config()` 函数，检查 URL/Key/Model 全部配置
- **移除**: `DEEPSEEK_API_KEY` 残留引用
- **新增**: `warmup()` 函数，启动时验证

### 8. ✅ 加密货币数据源回退
- **文件**: `bot/services/data_fetcher.py`
- **新增**: CoinGecko API 作为 `akshare.crypto_js_spot()` 的回退源
- 两级降级：akshare → CoinGecko

### 9. ✅ 策略参数外置
- **文件**: `engine/qlib_vnpy_platform/config/strategy_defaults.yaml`（新建）
- **新增**: 18 个核心策略的默认参数 + 中文描述，可通过 YAML 配置化

### 10. ✅ 日志轮转
- **文件**: `bot/run_server.py`, `bot/app/main.py`
- **修复**: 使用 `loguru` 配置日志轮转（10MB/文件，保留 30 天，自动 gz 压缩）
- **新增**: 自动清理超过 30 天的旧 uvicorn 日志

### 11. ✅ 飞书卡片精简
- **文件**: `bot/services/feishu_service.py`
- **优化**: 策略信号最多展示 Top 5（按信号总数排序）
- **优化**: 免责声明显著化（加粗 + 完整版）

---

## 📋 中风险修复（Phase 3-4）

### 12. ✅ 动态权重融合（SignalRouter）
- **文件**: `engine/qlib_vnpy_platform/core/signal_router.py`
- **新增**:
  - 市场波动率自动调节权重（高波动 → QLib 70%，低波动 → LLM 60%）
  - 信号独立性评估（同组策略折价，最多 5 折）
  - Bayesian 方向一致增强（方向一致时 +30% 置信度）
  - 输出 `fusion_info` 透传融合细节

### 13. ✅ T+1/T+0 规则完善
- **文件**: `engine/qlib_vnpy_platform/core/risk_manager.py`
- **新增**:
  - T+0 品种自动识别（可转债 11xxxx, ETF 51xxxx/159xxx 等）
  - 科创板 (688xxx) 交易规则提示
  - 卖出入参检查优化

### 14. ✅ 数据验证类型安全
- **文件**: `bot/services/data_fetcher.py`
- **修复**: `_validate_index_value` 增加 `isinstance` 类型检查
- **修复**: `if price and price > 0.001` → `if price is not None and price > 0.001`（2 处）

### 15. ✅ 健康检查增强
- **文件**: `bot/app/main.py`
- **增强**: /health 返回 6 大组件状态（database/llm/cache/scheduler/sources/version）
- **状态**: ok / degraded / critical 三级

---

## 📊 变更统计

| 类别 | 数量 |
|:-----|:----:|
| 修改文件 | 12 |
| 新建文件 | 3 |
| 修复 Bug | 8 |
| 新增功能 | 7 |
| 代码行变更 | ~1200 行新增 / ~300 行删除 |

## 📈 修复后状态对比

| 维度 | 修复前 | 修复后 |
|:-----|:-------|:-------|
| 并发安全 | ❌ sync sqlite3 线程不安全 | ✅ aiosqlite + WAL + asyncio.Lock |
| 事件循环 | ❌ 同步阻塞 12 步串行 | ✅ asyncio.gather 2 批并行 |
| RSI 信号 | ❌ 强度始终固定 | ✅ 按 RSI 偏离度计算 |
| KDJ 计算 | ❌ 除零风险 | ✅ NaN 保护 |
| LLM 配置 | ❌ 无校验静默失败 | ✅ 启动时主动校验 |
| 加密货币 | ❌ 单源无回退 | ✅ akshare + CoinGecko 双源 |
| 信号融合 | ❌ 固定权重线性相加 | ✅ 动态权重 + 独立性 + 方向增强 |
| T+1 规则 | ❌ 仅检查买入日期 | ✅ T+0 豁免 + 科创板规则 |
| 日志 | ❌ 单文件无限增长 | ✅ 10MB 轮转 + 30 天保留 + gz 压缩 |
| 进程管理 | ❌ 无守护 | ✅ systemd 自动重启 |
| 卡通信噪 | ❌ 所有信号全展示 | ✅ Top 5 排序 + 缩略 |
| 数据验证 | ❌ string/None 可能崩溃 | ✅ 类型安全检查 |
