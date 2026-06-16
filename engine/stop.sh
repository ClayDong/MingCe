#!/bin/bash
# QLib+VNPY 量化交易平台停止脚本

cd "$(dirname "$0")"

echo "================================================"
echo "  停止 QLib+VNPY 服务"
echo "================================================"

PID_FILE="logs/app.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$PID" ]; then
        if kill -0 "$PID" 2>/dev/null; then
            echo "✅ 停止服务，PID: $PID"
            kill "$PID"
            rm -f "$PID_FILE"
            echo "✅ 服务已停止"
        else
            echo "⚠️ 进程 $PID 不存在，清理 PID 文件"
            rm -f "$PID_FILE"
        fi
    fi
else
    echo "ℹ️ PID 文件不存在，尝试查找相关进程..."
    PIDS=$(pgrep -f "python web_app.py" 2>/dev/null)
    if [ -n "$PIDS" ]; then
        for PID in $PIDS; do
            echo "✅ 停止进程 $PID"
            kill "$PID"
        done
    else
        echo "⚠️ 没有找到运行中的服务"
    fi
fi

echo ""
echo "查看日志: tail -f logs/app.log"
echo "启动服务: ./start.sh"
