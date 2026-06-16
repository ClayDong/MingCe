#!/bin/bash
# MakingMoney 策略信号 HTTP 服务启动脚本
#
# 启动 FastAPI 信号服务（供 market-daily-bot HTTP 调用）
# 替代原有的 subprocess 调用方式，减少 ~10s 启动延迟
#
# 用法:
#   ./run_signal_service.sh              # 前台运行
#   ./run_signal_service.sh --daemon     # 后台运行（nohup）
#   ./run_signal_service.sh --stop       # 停止服务
#

set -euo pipefail

cd "$(dirname "$0")"

PID_FILE="logs/signal_service.pid"
LOG_FILE="logs/signal_service.log"
HOST="${SIGNAL_SERVICE_HOST:-127.0.0.1}"
PORT="${SIGNAL_SERVICE_PORT:-8765}"

stop_service() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "🛑 停止信号服务 (PID: $pid)..."
            kill "$pid" 2>/dev/null || true
            rm -f "$PID_FILE"
            echo "✅ 已停止"
        else
            echo "⚠️  进程 $pid 不存在，清理 PID 文件"
            rm -f "$PID_FILE"
        fi
    else
        echo "ℹ️  信号服务未运行"
    fi
}

case "${1:-}" in
    --stop)
        stop_service
        exit 0
        ;;
    --daemon)
        echo "🚀 启动策略信号服务 (后台模式)..."
        mkdir -p logs
        # 先停止已有实例
        stop_service
        # 激活虚拟环境并启动
        source venv/bin/activate
        nohup python -m uvicorn signal_service:app \
            --host "$HOST" \
            --port "$PORT" \
            --workers 1 \
            --log-level info \
            >> "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        echo "✅ 信号服务已启动 (PID: $(cat "$PID_FILE"))"
        echo "📡 http://${HOST}:${PORT}/health"
        echo "📝 日志: ${LOG_FILE}"
        ;;
    *)
        echo "🚀 启动策略信号服务 (前台模式)..."
        echo "📡 http://${HOST}:${PORT}/health"
        exec python -m uvicorn signal_service:app \
            --host "$HOST" \
            --port "$PORT" \
            --workers 1 \
            --log-level info
        ;;
esac
