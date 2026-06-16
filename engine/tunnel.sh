#!/bin/bash
# 内网穿透启动脚本 - 使用 ngrok
# 使用前需要：
# 1. 注册 ngrok: https://ngrok.com
# 2. 下载 ngrok: https://ngrok.com/download
# 3. 配置 authtoken: ./ngrok config add-authtoken <YOUR_TOKEN>
# 4. 或者使用国内替代品: natapp, sunflower 等

cd "$(dirname "$0")"

echo "================================================"
echo "  内网穿透配置指南"
echo "================================================"

echo ""
echo "方案1: ngrok (推荐)"
echo "--------------------"
echo "1. 下载 ngrok:"
echo "   - macOS: brew install ngrok"
echo "   - 或下载: https://ngrok.com/download"
echo ""
echo "2. 注册并获取 authtoken:"
echo "   - 访问 https://ngrok.com"
echo "   - 注册账号"
echo "   - 复制你的 authtoken"
echo ""
echo "3. 配置 token:"
echo "   ./ngrok config add-authtoken <YOUR_TOKEN>"
echo ""
echo "4. 启动穿透:"
echo "   ./ngrok http 5000"
echo ""
echo "免费账号限制:"
echo "  - 同时1个隧道"
echo "  - 每月10GB流量"
echo "  - 4分钟会话(需要重新连接)"
echo ""

echo ""
echo "方案2: natapp (国内,推荐)"  
echo "--------------------"
echo "1. 注册: https://natapp.cn"
echo "2. 下载客户端"
echo "3. 购买隧道(有免费隧道)"
echo "4. 配置:"
echo "   ./natapp -authtoken=<YOUR_TOKEN>"
echo ""

echo ""
echo "方案3: sunflower (向日葵,国内)"
echo "--------------------"
echo "1. 下载向日葵客户端"
echo "2. 登录账号"
echo "3. 使用远程桌面功能"
echo ""

echo ""
echo "方案4: frp (自建服务器)"
echo "--------------------"
echo "适合有自己服务器的用户"
echo "GitHub: https://github.com/fatedier/frp"
echo ""

echo ""
echo "================================================"
echo "启动穿透后，外部访问地址:"
echo "  - ngrok: http://xxxx.ngrok.io"
echo "  - natapp: http://xxxx.natappfree.cc"
echo "================================================"
echo ""

# 如果已安装 ngrok，直接启动
if command -v ngrok &> /dev/null; then
    echo "检测到 ngrok 已安装，正在启动..."
    echo ""
    echo "⚠️  重要提示:"
    echo "1. 请确保已在 https://ngrok.com 注册并获取 authtoken"
    echo "2. 如果还没配置 token，运行: ngrok config add-authtoken <YOUR_TOKEN>"
    echo ""
    read -p "按 Enter 启动 ngrok (Ctrl+C 退出)..."
    ngrok http 5000
else
    echo "ngrok 未安装，请先安装后再运行此脚本"
fi
