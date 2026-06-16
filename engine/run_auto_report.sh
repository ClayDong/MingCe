#!/bin/bash
# 每日自动化策略 + 舆情分析报告
# 每天 17:00 自动运行（crontab）
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="python3"
fi

echo "=========================================="
echo "🤖 每日自动化分析系统启动"
echo "日期: $(date '+%Y-%m-%d %H:%M:%S')"
echo "工作目录: $PROJECT_DIR"
echo "Python: $VENV_PYTHON"
echo "=========================================="

# 运行 Python 脚本
"$VENV_PYTHON" auto_daily_report.py

echo "=========================================="
echo "✅ 自动化分析完成"
echo "=========================================="
