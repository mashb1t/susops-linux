#!/usr/bin/env bash
# build.sh – Build and install the SusOps Flatpak app (user install)
#
# Usage:
#   cd flatpak/
#   ./build.sh          # build + install
#   ./build.sh --run    # build + install + launch
#   ./build.sh --uninstall

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="org.susops.App"
BUILD_DIR="$SCRIPT_DIR/.flatpak-build"
MANIFEST="$SCRIPT_DIR/org.susops.App.yml"

cd "$SCRIPT_DIR"

# ── Argument handling ─────────────────────────────────────────────────────────
ACTION="${1:-build}"

if [[ "$ACTION" == "--uninstall" ]]; then
  echo "==> Uninstalling $APP_ID …"
  flatpak uninstall --user -y "$APP_ID" || true
  echo "Done."
  exit 0
fi

# ── Dependency checks ─────────────────────────────────────────────────────────
for cmd in flatpak flatpak-builder git; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: '$cmd' is not installed. Please install it and re-run."
    exit 1
  fi
done

# ── Flatpak remote ────────────────────────────────────────────────────────────
echo "==> Ensuring Flathub remote is configured …"
flatpak remote-add --user --if-not-exists flathub \
  https://flathub.org/repo/flathub.flatpakrepo 2>/dev/null || true

# ── Runtime / SDK ─────────────────────────────────────────────────────────────
echo "==> Installing GNOME Platform 47 runtime and SDK (if needed) …"
flatpak install --user -y --or-update \
  flathub org.gnome.Platform//47 org.gnome.Sdk//47 \
  2>/dev/null || {
    echo "WARNING: Could not install via Flathub. If already installed, continuing …"
  }

# ── Build ─────────────────────────────────────────────────────────────────────
echo "==> Building $APP_ID …"
flatpak-builder \
  --force-clean \
  --user \
  --install \
  --state-dir="$BUILD_DIR/.flatpak-builder-state" \
  "$BUILD_DIR" \
  "$MANIFEST"

echo
echo "==> Build complete. Run with:"
echo "    flatpak run $APP_ID"

# ── Optional autostart ────────────────────────────────────────────────────────
AUTOSTART_DIR="$HOME/.config/autostart"
AUTOSTART_FILE="$AUTOSTART_DIR/$APP_ID.desktop"
if [[ ! -f "$AUTOSTART_FILE" ]]; then
  echo
  read -rp "Add SusOps to autostart? [y/N] " yn
  if [[ "${yn,,}" == "y" ]]; then
    mkdir -p "$AUTOSTART_DIR"
    cat > "$AUTOSTART_FILE" <<EOF
[Desktop Entry]
Name=SusOps
Exec=flatpak run $APP_ID
Icon=$APP_ID
Type=Application
X-GNOME-Autostart-enabled=true
EOF
    echo "Autostart entry created at $AUTOSTART_FILE"
  fi
fi

# ── Optional launch ───────────────────────────────────────────────────────────
if [[ "$ACTION" == "--run" ]]; then
  echo
  echo "==> Launching $APP_ID …"
  flatpak run "$APP_ID"
fi
