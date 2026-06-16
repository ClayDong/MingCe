#!/bin/bash
# QLib+VNPY 量化交易平台进程监控脚本

cd "$(dirname "$0")"

APP_SCRIPT="web_app.py"
PID_FILE="logs/app.pid"
LOG_FILE="logs/app.log"
WATCHDOG_LOG="logs/watchdog.log"

# 创建日志目录
mkdir -p logs

log_message() {
    local timestamp=$(date "+%Y-%m-%d %H:%M:%S" 2>/dev/null || date)
    echo "[$timestamp] $1" >> "$WATCHDOG_LOG"
    echo "[$timestamp] $1"
}

check_process() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

start_app() {
    log_message "检测到进程未运行，正在启动..."
    
    if [ -d "venv" ]; then
        source venv/bin/activate
    fi
    
    nohup python web_app.py -H 0.0.0.0 -p 5000 > "$LOG_FILE" 2>&1 &
    APP_PID=$!
    echo $APP_PID > "$PID_FILE"
    
    log_message "服务已启动，PID: $APP_PID"
}

log_message "Watchdog 启动监控..."

while true; do
    if ! check_process; then
        start_app
    fi
    sleep 60
done
