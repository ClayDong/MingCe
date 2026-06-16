#!/bin/bash
# 停止实时监控系统

cd /Users/dong/workspace/MakingMoney

echo "=========================================="
echo "🛑 停止实时监控系统"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

PID_FILE="realtime_monitor.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "⚠️ 未找到PID文件，尝试查找进程..."
    PIDS=$(ps aux | grep "realtime_monitor.py" | grep -v grep | awk '{print $2}')
else
    PID=$(cat "$PID_FILE")
    PIDS=$PID
fi

if [ -z "$PIDS" ]; then
    echo "✅ 监控系统未运行"
else
    echo "正在停止进程: $PIDS"
    kill $PIDS 2>/dev/null
    
    sleep 2
    
    # 检查是否还有进程在运行
    REMAINING=$(ps -p $PIDS 2>/dev/null)
    if [ -n "$REMAINING" ]; then
        echo "强制停止..."
        kill -9 $PIDS 2>/dev/null
    fi
    
    rm -f "$PID_FILE"
    echo "✅ 监控系统已停止"
fi

echo ""
echo "当前运行的Python进程:"
ps aux | grep python | grep -v grep
