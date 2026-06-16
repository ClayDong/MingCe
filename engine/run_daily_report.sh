#!/bin/bash
# 每日策略监控报告 - 自动执行脚本
# 每天 16:30 自动运行（crontab）

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="python3"
fi

echo "=========================================="
echo "📊 开始生成每日策略监控报告"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

"$VENV_PYTHON" daily_strategy_monitor_feishu.py

echo ""
echo "=========================================="
echo "✅ 报告生成完成"
echo "=========================================="
