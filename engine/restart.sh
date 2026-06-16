#!/bin/bash
# QLib+VNPY 量化交易平台重启脚本

cd "$(dirname "$0")"

echo "================================================"
echo "  重启 QLib+VNPY 服务"
echo "================================================"

./stop.sh

echo "⏳ 等待 3 秒..."
sleep 3

./start.sh
