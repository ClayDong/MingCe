#!/bin/bash
# 启动项目 + 内网穿透
# 使用前需要先配置 ngrok (参考 tunnel.sh 的说明)

cd "$(dirname "$0")"

echo "================================================"
echo "  启动量化交易平台 + 内网穿透"
echo "================================================"

# 检查 ngrok
if ! command -v ngrok &> /dev/null; then
    echo "❌ ngrok 未安装"
    echo "请先运行 ./tunnel.sh 查看配置指南"
    exit 1
fi

# 检查 ngrok 是否配置
if ! ngrok config check &> /dev/null; then
    echo "⚠️  ngrok 未配置 authtoken"
    echo "请先运行: ngrok config add-authtoken <YOUR_TOKEN>"
    echo "获取 Token: https://dashboard.ngrok.com/get-started/your-authtoken"
    exit 1
fi

# 启动主程序
echo "✅ 启动主程序..."
./start.sh

# 等待启动
sleep 3

# 启动 ngrok
echo ""
echo "✅ 启动内网穿透..."
echo ""
echo "⚠️  穿透地址将在下方显示，请等待几秒..."
echo ""

ngrok http 5000 --log=stdout | grep -E "(started|http|https)" | head -5 &

NGROK_PID=$!
echo "ngrok PID: $NGROK_PID"

sleep 5

# 显示访问地址
echo ""
echo "================================================"
echo "  ✅ 服务已启动!"
echo "================================================"
echo ""
echo "📱 本地访问:"
echo "   Web Dashboard: http://127.0.0.1:5000"
echo "   H5 Mobile:     http://127.0.0.1:5000/mobile"
echo ""
echo "🌐 外网访问:"
echo "   请查看 ngrok 提供的 http/https 地址"
echo ""
echo "================================================"
echo ""
echo "按 Ctrl+C 停止所有服务"
echo ""

# 捕获退出信号
trap "kill $NGROK_PID 2>/dev/null; ./stop.sh; exit" SIGINT SIGTERM

# 保持运行
wait $NGROK_PID
