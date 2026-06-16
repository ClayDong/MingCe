#!/bin/bash
# 飞书机器人消息监听服务
# 使用 lark-cli event consume 监听消息并自动回复

cd /Users/dong/workspace/MakingMoney

LOG_FILE="bot_listener.log"
VENV_PYTHON="/Users/dong/workspace/MakingMoney/venv/bin/python"

# 如果 venv 不存在则用系统 python
if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="python3"
fi

# 查找 lark-cli
LARK_CLI=""
for cli_path in \
    "/Users/dong/.nvm/versions/node/v24.14.0/bin/lark-cli" \
    "/Users/dong/.nvm/versions/node/v22.22.3/bin/lark-cli" \
    "$(which lark-cli 2>/dev/null)"; do
    if [ -f "$cli_path" ] && [ -x "$cli_path" ]; then
        LARK_CLI="$cli_path"
        break
    fi
done

if [ -z "$LARK_CLI" ]; then
    echo "[WARN] lark-cli 未找到，尝试安装..."
    npm install -g lark-cli
fi

# 把 lark-cli 加入 PATH
if [ -n "$LARK_CLI" ]; then
    export PATH="$(dirname "$LARK_CLI"):$PATH"
fi

echo "=========================================="
echo "🤖 启动飞书机器人消息监听"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "lark-cli: ${LARK_CLI:-未找到}"
echo "=========================================="

# 运行Python监听器 - 它会内部调用lark-cli event consume
nohup "$VENV_PYTHON" feishu_bot_listener.py >> "$LOG_FILE" 2>&1 &

LISTENER_PID=$!
echo "[INFO] 监听器进程 PID: $LISTENER_PID"
echo "[INFO] 日志文件: $LOG_FILE"
echo ""
echo "在飞书群中发送以下命令测试:"
echo "  - 报告 → 生成策略报告"
echo "  - 状态 → 查看策略状态"
echo "  - 排名 → 查看收益排名"
echo "  - 持仓 → 查看持仓详情"
echo "  - 帮助 → 显示帮助信息"
echo ""
echo "查看日志: tail -f $LOG_FILE"
echo "停止进程: kill $LISTENER_PID"
echo "=========================================="
