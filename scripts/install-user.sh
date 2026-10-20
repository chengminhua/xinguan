#!/usr/bin/env bash
# Install 芯观 for the current user only: desktop entry, icon and command.
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ID="local.ahua.HardwarePanel"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
BIN_DIR="$HOME/.local/bin"

mkdir -p "$APPS_DIR" "$ICON_DIR" "$BIN_DIR"
install -m 644 "$ROOT/assets/icon.svg" "$ICON_DIR/$APP_ID.svg"
ln -sfn "$ROOT/scripts/run.sh" "$BIN_DIR/xinguan"

cat > "$APPS_DIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=芯观
GenericName=硬件监测
Comment=实时查看 AIBOOK 的占用率、部件功率、温度、风扇与电池
Exec="$ROOT/scripts/run.sh"
Icon=$APP_ID
Terminal=false
Categories=System;Monitor;
StartupNotify=true
StartupWMClass=xinguan
Keywords=芯观;Xinguan;硬件;监控;功耗;功率;温度;风扇;CPU;GPU;
EOF
chmod 755 "$APPS_DIR/$APP_ID.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

echo "已安装：应用列表中的“芯观”，以及命令 $BIN_DIR/xinguan"
echo "如果应用列表没有立即刷新，注销后重新登录即可。"
