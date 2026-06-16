# 📊 数据质量监控系统 - 完整使用指南

## 概述

数据质量监控系统提供完整的实时数据质量检查、告警、历史记录和可视化功能，确保您的量化交易系统使用的数据始终可靠。

---

## 🚀 快速开始

### 1. 单次检查模式

运行一次检查并退出：

```bash
python start_data_quality_monitor.py --check
```

检查指定股票：

```bash
python start_data_quality_monitor.py --check --symbol SZ002594
```

### 2. 交互模式启动

启动交互式监控界面：

```bash
python start_data_quality_monitor.py
```

### 3. 守护进程模式

在后台持续运行：

```bash
python start_data_quality_monitor.py --daemon
```

---

## 📋 功能特性

### ✅ 核心功能

1. **6维度数据质量检查**
   - 完整性检查：缺失列、缺失率
   - 准确性检查：价格、成交量验证
   - 一致性检查：OHLC关系、价格范围
   - 时效性检查：数据过期、日期连续性
   - 重复检查：日期去重
   - 波动率异常：检测异常波动

2. **智能告警系统**
   - 4个默认告警规则
   - 冷却时间机制，避免刷屏
   - 多级别告警：info, warning, error, critical
   - 自定义告警规则支持

3. **数据质量评分**
   - 0-100分的量化评分
   - 详细的检查结果
   - 问题列表展示

4. **历史记录**
   - 实时检查记录
   - 按日期归档
   - 质量趋势分析

5. **控制台界面**
   - 实时状态展示
   - 交互式操作
   - 告警推送显示

---

## ⚙️ 配置说明

在 [settings.yaml](qlib_vnpy_platform/config/settings.yaml) 中配置：

```yaml
data_quality:
  enabled: true
  check_interval: 60              # 检查间隔（分钟）
  alert_threshold: 70             # 告警阈值（低于此分数告警）
  stale_data_days: 5              # 数据过期天数
  auto_fix_enabled: true          # 自动修复启用
  max_missing_rate: 0.001         # 最大缺失率 0.1%
  max_price_change: 0.20          # 最大价格变化率 20%
  max_volume_change: 10.0         # 最大成交量变化率 10倍
  monitor_symbols:                 # 监控股票列表
    - SZ002594
    - SZ000001
    - SH600519
    - SZ300750
    - SH600036
```

---

## 📖 API 指南

### 基本使用

```python
from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.data_quality_monitor import (
    DataQualityMonitor,
    get_monitor_instance
)

# 1. 加载配置
load_config()

# 2. 创建监控器
monitor = DataQualityMonitor()

# 3. 检查单个股票
record = monitor.check_symbol_quality("SZ002594")
print(f"质量评分: {record.quality_score:.1f}/100")
print(f"是否通过: {record.passed}")

# 4. 批量检查
results = monitor.check_multiple_symbols([
    "SZ002594", 
    "SZ000001", 
    "SH600519"
])

# 5. 获取摘要
summary = monitor.get_quality_summary()
print(f"平均评分: {summary['average_score']:.1f}")
```

### 自定义告警规则

```python
from qlib_vnpy_platform.core.data_quality_monitor import AlertRule

# 创建自定义规则
rule = AlertRule(
    name="low_volume",
    condition=lambda r: any("volume" in issue.lower() for issue in r.issues_summary),
    alert_level="warning",
    message_template="⚠️ 成交量异常: {symbol}",
    cooldown_minutes=30
)

# 添加到监控器
monitor.add_alert_rule(rule)
```

---

## 🎯 使用场景

### 场景1：启动前数据检查

```python
# 在策略启动前检查数据质量
monitor = get_monitor_instance()
record = monitor.check_symbol_quality("SZ002594")

if record.quality_score < 80:
    print("数据质量不足，暂不启动策略")
    print(f"问题: {record.issues_summary}")
else:
    print("数据质量良好，可以启动策略")
    # 启动策略逻辑
```

### 场景2：数据质量自动告警

```python
# 在后台运行监控，发现问题立即告警
monitor.start_monitoring(
    symbols=["SZ002594", "SZ000001"],
    interval_minutes=30
)

# 定期检查告警
while True:
    alerts = monitor.get_pending_alerts()
    for alert in alerts:
        # 发送飞书/邮件/短信告警
        send_alert(alert)
    time.sleep(60)
```

### 场景3：质量报告生成

```python
# 生成质量报告
summary = monitor.get_quality_summary()

print("=" * 50)
print("数据质量周报")
print("=" * 50)
print(f"平均评分: {summary['average_score']:.1f}/100")
print(f"通过率: {summary['pass_rate']*100:.1f}%")
print(f"总检查次数: {summary['total_checks']}")

for symbol, stats in summary['symbol_stats'].items():
    print(f"{symbol}: {stats['avg_score']:.1f}分")
```

---

## 🔧 故障排查

### 常见问题

**Q: 数据质量检查失败怎么办？**

A: 根据告警信息处理：
- 数据过期：检查网络连接，更新数据源
- 数据缺失：检查数据获取逻辑
- 数据异常：查看原始数据，手动验证

**Q: 如何修改告警阈值？**

A: 在配置文件中修改 `alert_threshold`，或添加自定义告警规则。

**Q: 如何查看历史记录？**

A: 历史记录保存在 `data/quality_monitor/` 目录下，按日期归档为 JSON 文件。

---

## 📊 质量评分说明

| 分数区间 | 等级 | 说明 | 建议操作 |
|---------|------|------|---------|
| 90-100 | ✅ 优秀 | 数据质量完美 | 继续保持 |
| 70-89 | ⚠️ 良好 | 小问题，不影响使用 | 关注问题 |
| 50-69 | 🚨 中等 | 需要检查 | 调查原因 |
| 0-49 | ❌ 较差 | 数据不可靠 | 暂停使用，修复数据 |

---

## 🎯 最佳实践

1. **启动时检查**：在策略启动前进行一次完整的数据质量检查
2. **定期监控**：建议每小时检查一次核心股票的数据质量
3. **告警响应**：收到critical级别告警时，应立即停止策略
4. **历史分析**：定期查看质量趋势，发现潜在问题
5. **配置优化**：根据实际使用情况调整阈值

---

## 📞 联系与支持

如遇到问题，请查看：
- [数据质量监控服务](qlib_vnpy_platform/core/data_quality_monitor.py)
- [数据质量检查器](qlib_vnpy_platform/core/data_quality.py)
- [启动脚本](start_data_quality_monitor.py)

---

**祝您的数据质量监控顺利！** 🚀
