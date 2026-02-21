#!/usr/bin/env bash
# build.sh – Build and install susops-tray
#
# Usage:
#   ./build.sh              # build + install (pacman on Arch, direct otherwise)
#   ./build.sh --uninstall  # remove installed files
#   ./build.sh --run        # install + launch

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTION="${1:-install}"

# ── Arch Linux: use PKGBUILD / makepkg ────────────────────────────────────────
if command -v pacman &>/dev/null; then
    case "$ACTION" in
        --uninstall)
            echo "==> Removing susops-tray …"
            sudo pacman -R susops-tray
            exit 0
            ;;
        --run)
            cd "$SCRIPT_DIR"
            makepkg -si --noconfirm
            exec susops-tray
            ;;
        *)
            cd "$SCRIPT_DIR"
            makepkg -si --noconfirm
            echo "==> Done. Run with: susops-tray"
            exit 0
            ;;
    esac
fi