#!/usr/bin/env bash
# build.sh – Build susops-tray as a standalone binary using PyInstaller
#
# Usage:
#   ./build.sh              # build → dist/susops-tray
#   ./build.sh --install    # build + install to ~/.local/bin + autostart
#   ./build.sh --uninstall  # remove installed files

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARY="$SCRIPT_DIR/dist/susops-tray"
INSTALL_BIN="$HOME/.local/bin/susops-tray"
DESKTOP_SRC="$SCRIPT_DIR/susops-tray.desktop"
DESKTOP_DST="$HOME/.local/share/applications/susops-tray.desktop"
ICON_SRC="$SCRIPT_DIR/susops-cli/icon.png"
ICON_DST="$HOME/.local/share/icons/hicolor/128x128/apps/org.susops.App.png"

PYTHON="${PYTHON:-/usr/bin/python3}"
ACTION="${1-build}"

# ── Uninstall ─────────────────────────────────────────────────────────────────
if [[ "$ACTION" == "--uninstall" ]]; then
  echo "==> Uninstalling susops-tray …"
  rm -f "$INSTALL_BIN" "$DESKTOP_DST" "$ICON_DST" \
        "$HOME/.config/autostart/susops-tray.desktop"
  echo "Done."
  exit 0
fi

# ── Dependency checks ─────────────────────────────────────────────────────────
if ! command -v "$PYTHON" &>/dev/null; then
  echo "ERROR: python3 is required."
  exit 1
fi

if ! "$PYTHON" -c "import gi" &>/dev/null; then
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

if ! "$PYTHON" -c "import PyInstaller" &>/dev/null 2>&1; then
  echo "==> Creating build venv with system packages …"
  "$PYTHON" -m venv --system-site-packages "$SCRIPT_DIR/.build-venv"
  "$SCRIPT_DIR/.build-venv/bin/pip" install --quiet pyinstaller pyinstaller-hooks-contrib
fi

PYINSTALLER="$SCRIPT_DIR/.build-venv/bin/pyinstaller"
if [[ ! -f "$PYINSTALLER" ]]; then
  PYINSTALLER="$SCRIPT_DIR/.build-venv/bin/pyinstaller"
fi

# ── Build ─────────────────────────────────────────────────────────────────────
echo "==> Building susops-tray binary …"
cd "$SCRIPT_DIR"
"$SCRIPT_DIR/.build-venv/bin/python" -m PyInstaller --clean --noconfirm susops-tray.spec

echo
echo "==> Build complete: $BINARY"

# ── Install ───────────────────────────────────────────────────────────────────
if [[ "$ACTION" == "--install" ]]; then
  echo "==> Installing …"

  install -Dm755 "$BINARY" "$INSTALL_BIN"
  echo "    binary  → $INSTALL_BIN"

  if [[ -f "$ICON_SRC" ]]; then
    install -Dm644 "$ICON_SRC" "$ICON_DST"
    gtk-update-icon-cache -f -t "$(dirname "$(dirname "$(dirname "$ICON_DST")")")" 2>/dev/null || true
    echo "    icon    → $ICON_DST"
  fi

  # Update desktop file Exec path and install
  mkdir -p "$(dirname "$DESKTOP_DST")"
  sed "s|^Exec=.*|Exec=$INSTALL_BIN|" "$DESKTOP_SRC" > "$DESKTOP_DST"
  echo "    desktop → $DESKTOP_DST"

  echo
  read -rp "Add SusOps to autostart? [y/N] " yn
  if [[ "${yn,,}" == "y" ]]; then
    mkdir -p "$HOME/.config/autostart"
    cp "$DESKTOP_DST" "$HOME/.config/autostart/susops-tray.desktop"
    echo "    autostart entry created."
  fi

  echo
  echo "==> Run with:  susops-tray"
fi
