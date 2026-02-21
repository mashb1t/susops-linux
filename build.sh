#!/usr/bin/env bash
# build.sh – Build and install susops
#
# Usage:
#   ./build.sh              # install system dependencies + install app
#   ./build.sh --uninstall  # remove installed files
#   ./build.sh --run        # install + launch
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTION="${1:-install}"

# ── Detect package manager ────────────────────────────────────────────────────
detect_pm() {
    if   command -v pacman &>/dev/null; then echo "pacman"
    elif command -v apt    &>/dev/null; then echo "apt"
    elif command -v dnf    &>/dev/null; then echo "dnf"
    elif command -v zypper &>/dev/null; then echo "zypper"
    elif command -v apk    &>/dev/null; then echo "apk"
    else echo "unknown"
    fi
}

install_deps() {
    local pm
    pm="$(detect_pm)"
    echo "==> Installing system dependencies via ${pm} …"
    case "$pm" in
        pacman)
            sudo pacman -S --needed --noconfirm \
                go-yq autossh openbsd-netcat gtk3 python-gobject libayatana-appindicator
            ;;
        apt)
            sudo apt install -y \
                golang-github-mikefarah-yq autossh netcat-openbsd \
                python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
                libayatana-appindicator3-1 gir1.2-ayatanaappindicator3-0.1
            ;;
        dnf)
            sudo dnf install -y \
                yq autossh nmap-ncat gtk3 python3-gobject libayatana-appindicator
            ;;
        zypper)
            sudo zypper install -y \
                yq autossh netcat-openbsd python3-gobject typelib-1_0-Gtk-3_0 \
                libayatana-appindicator3-1
            ;;
        apk)
            sudo apk add \
                yq autossh netcat-openbsd gtk+3.0 py3-gobject3 libayatana-appindicator
            ;;
        *)
            echo "    WARNING: Unknown package manager. Install dependencies manually (see README)."
            ;;
    esac
}

# ── Arch Linux: use PKGBUILD / makepkg ────────────────────────────────────────
if command -v pacman &>/dev/null; then
    case "$ACTION" in
        --uninstall)
            echo "==> Removing susops …"
            sudo pacman -R susops
            exit 0
            ;;
        --run)
            cd "$SCRIPT_DIR"
            makepkg -si --noconfirm
            exec susops
            ;;
        *)
            cd "$SCRIPT_DIR"
            makepkg -si --noconfirm
            echo "==> Done. Run with: susops"
            exit 0
            ;;
    esac
fi

# ── Generic install (non-Arch): install deps then install to ~/.local ─────────
PREFIX="${HOME}/.local"
LIB_DIR="${PREFIX}/lib/susops"
BIN_DIR="${PREFIX}/bin"
APP_DIR="${PREFIX}/share/applications"
ICON_DIR="${PREFIX}/share/icons/hicolor/128x128/apps"

case "$ACTION" in
    --uninstall)
        echo "==> Removing susops from ${PREFIX} …"
        rm -rf "${LIB_DIR}"
        rm -f  "${BIN_DIR}/susops"
        rm -f  "${APP_DIR}/susops.desktop"
        rm -f  "${ICON_DIR}/org.susops.App.png"
        echo "==> Done."
        exit 0
        ;;
    --run | install)
        install_deps
        cd "$SCRIPT_DIR"

        echo "==> Installing susops to ${PREFIX} …"

        # App files
        install -Dm644 susops.py            "${LIB_DIR}/susops.py"
        install -Dm644 version.py           "${LIB_DIR}/version.py"
        install -Dm755 susops-cli/susops.sh "${LIB_DIR}/susops.sh"
        install -Dm644 icon.png             "${LIB_DIR}/icon.png"
        cp -r icons "${LIB_DIR}/icons"

        # App icon
        install -Dm644 icon.png "${ICON_DIR}/org.susops.App.png"

        # Desktop entry
        install -Dm644 susops.desktop "${APP_DIR}/susops.desktop"

        # Launcher
        install -dm755 "${BIN_DIR}"
        cat > "${BIN_DIR}/susops" << EOF
#!/bin/bash
export PYTHONPATH="${LIB_DIR}\${PYTHONPATH:+:\$PYTHONPATH}"
exec /usr/bin/python3 "${LIB_DIR}/susops.py" "\$@"
EOF
        chmod 755 "${BIN_DIR}/susops"

        echo "==> Done. Run with: susops"
        echo "    (ensure ${BIN_DIR} is in your \$PATH)"

        if [[ "$ACTION" == "--run" ]]; then
            exec "${BIN_DIR}/susops"
        fi
        ;;
esac