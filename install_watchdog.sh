#!/bin/bash
# 南山科转通 守护进程安装脚本
# 用法: sudo bash install_watchdog.sh

set -euo pipefail

PLIST_NAME="com.nanshan.watchdog"
PLIST_SRC="/Users/mac/Desktop/南山小程序/${PLIST_NAME}.plist"
PLIST_DST="/Library/LaunchDaemons/${PLIST_NAME}.plist"
LOG_DIR="/Users/mac/Desktop/南山小程序/logs"

echo "🔧 安装南山科转通守护进程..."

# 1. 创建日志目录
mkdir -p "$LOG_DIR"
chmod 755 "$LOG_DIR"

# 2. 停止旧服务（如果存在）
if launchctl list | grep -q "$PLIST_NAME" 2>/dev/null; then
    echo "⏹  停止旧服务..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
fi

# 3. 复制plist
echo "📋 安装配置文件..."
cp "$PLIST_SRC" "$PLIST_DST"
chown root:wheel "$PLIST_DST"
chmod 644 "$PLIST_DST"

# 4. 加载服务
echo "🚀 加载守护进程..."
launchctl load "$PLIST_DST"

# 5. 验证
echo ""
echo "✅ 安装完成！"
echo ""
echo "=== 服务状态 ==="
launchctl list | grep "$PLIST_NAME" || echo "服务未加载"
echo ""
echo "=== 管理命令 ==="
echo "  查看状态:  launchctl list | grep nanshan"
echo "  停止服务:  sudo launchctl unload $PLIST_DST"
echo "  启动服务:  sudo launchctl load $PLIST_DST"
echo "  卸载服务:  sudo launchctl unload $PLIST_DST && sudo rm $PLIST_DST"
echo "  查看日志:  tail -f $LOG_DIR/watchdog-stdout.log"
echo ""
echo "=== 开机自启 ==="
echo "  服务已设置为开机自动启动，无需登录。"
echo "  电脑重启后，守护进程会自动拉起后端和AI Agent。"