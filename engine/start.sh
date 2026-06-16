#!/bin/bash
# QLib+VNPY 量化交易平台启动脚本

cd "$(dirname "$0")"

echo "================================================"
echo "  QLib+VNPY 量化交易平台"
echo "================================================"

# 激活虚拟环境
if [ -d "venv" ]; then
    echo "✅ 激活虚拟环境..."
    source venv/bin/activate
else
    echo "❌ 虚拟环境不存在，请先运行 setup.sh"
    exit 1
fi

# 创建日志目录
mkdir -p logs

echo "✅ 启动服务..."
echo "📊 Web Dashboard: http://127.0.0.1:5000"
echo "📱 H5 Mobile: http://127.0.0.1:5000/mobile"
echo "📡 策略信号服务: http://127.0.0.1:8765/health"
echo "📝 日志文件: logs/app.log, logs/signal_service.log"
echo "================================================"

# 启动主 Web 服务（后台运行）
nohup python web_app.py -H 0.0.0.0 -p 5000 > logs/app.log 2>&1 &
APP_PID=$!
echo $APP_PID > logs/app.pid

# 启动策略信号服务（后台运行）
nohup python -m uvicorn signal_service:app \
    --host 127.0.0.1 \
    --port 8765 \
    --workers 1 \
    --log-level info \
    > logs/signal_service.log 2>&1 &
SIGNAL_PID=$!
echo $SIGNAL_PID > logs/signal_service.pid

echo "✅ 主服务已启动，PID: $APP_PID"
echo "✅ 信号服务已启动，PID: $SIGNAL_PID"
echo ""
echo "查看日志:"
echo "  tail -f logs/app.log"
echo "  tail -f logs/signal_service.log"
echo "停止服务: ./stop.sh"
echo "重启服务: ./restart.sh"
