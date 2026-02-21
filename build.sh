#!/usr/bin/env bash
# build.sh – Install susops-tray (Python GTK app) as a runnable binary
#
# Usage:
#   ./build.sh              # install to ~/.local
#   ./build.sh --uninstall  # remove installed files
#   ./build.sh --run        # install + launch

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-/usr/bin/python3}"
ACTION="${1-install}"

APP_DATA="$HOME/.local/share/susops"
INSTALL_BIN="$HOME/.local/bin/susops-tray"
DESKTOP_DST="$HOME/.local/share/applications/susops-tray.desktop"
ICON_DST="$HOME/.local/share/icons/hicolor/128x128/apps/org.susops.App.png"

# ── Uninstall ─────────────────────────────────────────────────────────────────
if [[ "$ACTION" == "--uninstall" ]]; then
  echo "==> Uninstalling susops-tray …"
  rm -f "$INSTALL_BIN" "$DESKTOP_DST" "$ICON_DST" \
        "$HOME/.config/autostart/susops-tray.desktop"
  rm -rf "$APP_DATA"
  echo "Done."
  exit 0
fi

# ── Dependency checks ─────────────────────────────────────────────────────────
if ! "$PYTHON" -c "import gi" &>/dev/null 2>&1; then
  echo "==> Installing python3-gi (PyGObject) …"
  if command -v pacman &>/dev/null; then
    sudo pacman -S --noconfirm python-gobject gtk3 libayatana-appindicator
  elif command -v apt-get &>/dev/null; then
    sudo apt-get install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
      gir1.2-ayatanaappindicator3-0.1 libayatana-appindicator3-1
  elif command -v dnf &>/dev/null; then
    sudo dnf install -y python3-gobject gtk3 libayatana-appindicator
  else
    echo "ERROR: python3-gi (PyGObject) is required. Install it with your package manager."
    exit 1
  fi
fi

# ── Install app files ─────────────────────────────────────────────────────────
echo "==> Installing susops-tray …"

install -Dm755 "$SCRIPT_DIR/susops_tray.py"      "$APP_DATA/susops_tray.py"
install -Dm755 "$SCRIPT_DIR/susops-cli/susops.sh" "$APP_DATA/susops.sh"
cp -r "$SCRIPT_DIR/icons" "$APP_DATA/icons"
echo "    script  → $APP_DATA/susops_tray.py"

if [[ -f "$SCRIPT_DIR/susops-cli/icon.png" ]]; then
  install -Dm644 "$SCRIPT_DIR/susops-cli/icon.png" "$ICON_DST"
  gtk-update-icon-cache -f -t "$(dirname "$(dirname "$(dirname "$ICON_DST")")")" 2>/dev/null || true
  echo "    icon    → $ICON_DST"
fi

# ── Create launcher script ────────────────────────────────────────────────────
mkdir -p "$(dirname "$INSTALL_BIN")"
cat > "$INSTALL_BIN" << EOF
#!/usr/bin/env bash
exec $PYTHON $APP_DATA/susops_tray.py "\$@"
EOF
chmod +x "$INSTALL_BIN"
echo "    binary  → $INSTALL_BIN"

# ── Desktop entry ─────────────────────────────────────────────────────────────
mkdir -p "$(dirname "$DESKTOP_DST")"
sed "s|^Exec=.*|Exec=$INSTALL_BIN|" "$SCRIPT_DIR/susops-tray.desktop" > "$DESKTOP_DST"
echo "    desktop → $DESKTOP_DST"

# ── Autostart ─────────────────────────────────────────────────────────────────
AUTOSTART_FILE="$HOME/.config/autostart/susops-tray.desktop"
if [[ ! -f "$AUTOSTART_FILE" ]]; then
  echo
  read -rp "Add SusOps to autostart? [y/N] " yn
  if [[ "${yn,,}" == "y" ]]; then
    mkdir -p "$HOME/.config/autostart"
    cp "$DESKTOP_DST" "$AUTOSTART_FILE"
    echo "    autostart entry created."
  fi
fi

echo
echo "==> Done. Run with:  susops-tray"

if [[ "$ACTION" == "--run" ]]; then
  exec "$INSTALL_BIN"
fi
