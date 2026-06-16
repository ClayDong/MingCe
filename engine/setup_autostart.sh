#!/bin/bash
# 设置开机自启动
# 使用 launchd (macOS) 自动启动监控进程

cd "$(dirname "$0")"
PROJECT_DIR=$(pwd)

echo "================================================"
echo "  设置开机自启动"
echo "================================================"

# 创建 launchd plist 文件
PLIST_NAME="com.qlibvnpy.monitor.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.qlibvnpy.monitor</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${PROJECT_DIR}/watchdog.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${PROJECT_DIR}/logs/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_DIR}/logs/launchd.error.log</string>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
</dict>
</plist>
EOF

echo "✅ 创建 launchd plist: $PLIST_PATH"
echo ""

# 加载 launchd 服务
echo "加载 launchd 服务..."
launchctl load "$PLIST_PATH" 2>/dev/null

if [ $? -eq 0 ]; then
    echo "✅ 服务已加载到 launchd"
    echo ""
    echo "开机自启动已设置完成!"
    echo ""
    echo "管理命令:"
    echo "  查看状态: launchctl list | grep qlibvnpy"
    echo "  停止服务: launchctl unload $PLIST_PATH"
    echo "  删除自启: launchctl unload $PLIST_PATH && rm $PLIST_PATH"
else
    echo "⚠️  加载失败，请检查权限"
fi

echo ""
echo "================================================"
