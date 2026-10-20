#!/usr/bin/env bash
# Remove the per-user installation created by install-user.sh.
set -euo pipefail

APP_ID="local.ahua.HardwarePanel"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

rm -f "$APPS_DIR/$APP_ID.desktop" "$ICON_DIR/$APP_ID.svg" "$HOME/.local/bin/xinguan"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

echo "已移除当前用户的芯观桌面入口、图标和命令。源码目录未改动。"
