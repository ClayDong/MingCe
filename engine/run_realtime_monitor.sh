#!/bin/bash
# 启动实时监控系统

cd /Users/dong/workspace/MakingMoney

echo "=========================================="
echo "🤖 启动实时监控系统"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

# 检查是否已经在运行
if pgrep -f "realtime_monitor.py" > /dev/null; then
    echo "⚠️ 实时监控已经在运行中"
    echo ""
    echo "查看进程:"
    ps aux | grep "realtime_monitor.py" | grep -v grep
    exit 1
fi

# 清理旧的PID和日志
rm -f realtime_monitor.pid

# 使用 nohup 后台运行
nohup venv/bin/python realtime_monitor.py > realtime_monitor.log 2>&1 &

MONITOR_PID=$!
echo $MONITOR_PID > realtime_monitor.pid

echo "✅ 实时监控已启动 (PID: $MONITOR_PID)"
echo "📝 日志文件: realtime_monitor.log"
echo ""
echo "常用命令:"
echo "  查看日志: tail -f realtime_monitor.log"
echo "  查看进程: ps aux | grep realtime_monitor.py"
echo "  停止监控: ./stop_realtime_monitor.sh"

# 等待一下看是否启动成功
sleep 2
if ps -p $MONITOR_PID > /dev/null; then
    echo ""
    echo "✅ 系统运行正常！"
    echo ""
    echo "监控功能:"
    echo "  - 交易时间每5分钟检查一次策略信号"
    echo "  - 发现信号立即发送飞书预警"
    echo "  - 全天每30分钟检查一次舆情"
    echo "  - 重大舆情立即发送飞书预警"
else
    echo ""
    echo "❌ 启动失败，请检查日志!"
    tail -20 realtime_monitor.log
fi
