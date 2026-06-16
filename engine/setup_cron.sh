#!/bin/bash
# 安装 MakingMoney 定时任务（macOS launchd 方式）
# 替代 crontab（在此系统上不可用）

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_DIR"
mkdir -p "$PROJECT_DIR/logs"

echo "============================================"
echo "📅 安装 MakingMoney 定时任务"
echo "项目目录: $PROJECT_DIR"
echo "============================================"

# ── 任务1：策略交易报告（交易日 16:00）──
PLIST_TRADE="$LAUNCH_DIR/com.makingmoney.daily_trade_report.plist"
cat > "$PLIST_TRADE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.makingmoney.daily_trade_report</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${PROJECT_DIR}/run_daily_trade_report.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Hour</key>
            <integer>16</integer>
            <key>Minute</key>
            <integer>0</integer>
            <key>Weekday</key>
            <integer>1</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>16</integer>
            <key>Minute</key>
            <integer>0</integer>
            <key>Weekday</key>
            <integer>2</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>16</integer>
            <key>Minute</key>
            <integer>0</integer>
            <key>Weekday</key>
            <integer>3</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>16</integer>
            <key>Minute</key>
            <integer>0</integer>
            <key>Weekday</key>
            <integer>4</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>16</integer>
            <key>Minute</key>
            <integer>0</integer>
            <key>Weekday</key>
            <integer>5</integer>
        </dict>
    </array>
    <key>StandardOutPath</key>
    <string>${PROJECT_DIR}/logs/cron_trade.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_DIR}/logs/cron_trade.error.log</string>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
echo "✅ $PLIST_TRADE"

# ── 任务2：策略监控报告（交易日 16:30）──
PLIST_MONITOR="$LAUNCH_DIR/com.makingmoney.daily_monitor.plist"
cat > "$PLIST_MONITOR" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.makingmoney.daily_monitor</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${PROJECT_DIR}/run_daily_report.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer><key>Weekday</key><integer>1</integer></dict>
        <dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer><key>Weekday</key><integer>2</integer></dict>
        <dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer><key>Weekday</key><integer>3</integer></dict>
        <dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer><key>Weekday</key><integer>4</integer></dict>
        <dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer><key>Weekday</key><integer>5</integer></dict>
    </array>
    <key>StandardOutPath</key>
    <string>${PROJECT_DIR}/logs/cron_monitor.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_DIR}/logs/cron_monitor.error.log</string>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
echo "✅ $PLIST_MONITOR"

# ── 任务3：全自动日报（交易日 17:00）──
PLIST_AUTO="$LAUNCH_DIR/com.makingmoney.auto_report.plist"
cat > "$PLIST_AUTO" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.makingmoney.auto_report</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${PROJECT_DIR}/run_auto_report.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer><key>Weekday</key><integer>1</integer></dict>
        <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer><key>Weekday</key><integer>2</integer></dict>
        <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer><key>Weekday</key><integer>3</integer></dict>
        <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer><key>Weekday</key><integer>4</integer></dict>
        <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer><key>Weekday</key><integer>5</integer></dict>
    </array>
    <key>StandardOutPath</key>
    <string>${PROJECT_DIR}/logs/cron_auto.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_DIR}/logs/cron_auto.error.log</string>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
echo "✅ $PLIST_AUTO"

# ── 加载服务 ──
echo ""
echo "📦 加载 launchd 服务..."
for plist in "$PLIST_TRADE" "$PLIST_MONITOR" "$PLIST_AUTO"; do
    launchctl load "$plist" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "  ✅ $(basename $plist) 加载成功"
    else
        echo "  ⚠️  $(basename $plist) 可能已加载或权限不足"
    fi
done

echo ""
echo "============================================"
echo "📋 已安装的定时任务："
echo "  交易日 16:00 → 策略交易报告"
echo "  交易日 16:30 → 策略监控报告"
echo "  交易日 17:00 → 全自动日报（策略+舆情+LLM）"
echo ""
echo "管理命令："
echo "  查看状态：launchctl list | grep makingmoney"
echo "  手动触发：launchctl start com.makingmoney.daily_trade_report"
echo "  停止：launchctl unload ~/Library/LaunchAgents/com.makingmoney.*.plist"
echo "============================================"
