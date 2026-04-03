# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run directly during development (no build needed)
python3 susops.py

# Build and install (Arch: via makepkg; others: to ~/.local)
./build.sh

# Install + launch immediately
./build.sh --run

# Uninstall
./build.sh --uninstall
```

No test suite or linter is configured. There are no venvs — `python-gobject` must be a system package.

## Architecture

The app is a single Python file (`susops.py`) plus a version module (`version.py`). The CLI lives in a **git submodule** (`susops-cli/susops.sh`).

The CLI documentation can be found in @susops-cli/README.md

### Key files

| File | Purpose |
|------|---------|
| `susops.py` | Entire tray application (~700 lines, GTK3 + AyatanaAppIndicator3) |
| `version.py` | Single `VERSION` string, also read by `PKGBUILD` via `pkgver()` |
| `susops-cli/susops.sh` | CLI submodule — **DO NOT MODIFY** |
| `PKGBUILD` | Arch Linux package recipe (reads version from `version.py`) |
| `build.sh` | Cross-distro install script; uses `makepkg` on Arch, installs to `~/.local` elsewhere |
| `icons/` | SVG tray icons in three styles (`colored_glasses/`, `colored_s/`, `gear/`), each with `light/` and `dark/` variants |

### susops-cli is a bash **function**, not a binary

`susops.sh` defines `susops()` — it must be sourced. `susops.py` calls it via `subprocess.run([SUSOPS_SH] + args, ...)` where `SUSOPS_SH` is resolved to the script path at startup (checked in several locations: bundle, submodule, system paths).

### susops CLI commands and async execution

- `run_cmd(args)` — synchronous; returns `(stdout+stderr, returncode)`
- `run_async(args, callback)` — runs in a daemon thread; delivers result back to GTK main loop via `GLib.idle_add(callback, out, rc)`

All state-changing operations (start, stop, restart, add, remove) use `run_async`.

### Process state and the Linux pgrep bug

`ProcessState` enum has five states: `INITIAL`, `RUNNING`, `STOPPED_PARTIALLY`, `STOPPED`, `ERROR`.

`susops ps` returns rc=2 (`STOPPED_PARTIALLY`) even when the proxy is running, because `autossh` sets `argv[0]` to `susops-ssh-<tag>` but the kernel `comm` stays `autossh`, so `pgrep -x` never matches. The tray app works around this: on rc=2, it runs a supplementary `pgrep -f "susops-ssh"` check and upgrades state to `RUNNING` if processes are found.

### Config

`ConfigHelper` reads/writes `~/.susops/config.yaml` using `yq e` (go-yq v4). The Python-based `yq` (kislyuk) is **incompatible**. On Arch: `go-yq` package.

### Icon system

SVG icons in `icons/<style>/<light|dark>/<state>.svg` are rasterised to 22×22 PNG on first use and cached in `~/.cache/susops/icons/`. Theme variant (`light`/`dark`) is detected via `gsettings`.

### AppIndicator detection

`susops.py` tries `AyatanaAppIndicator3` first, then falls back to `AppIndicator3`, then `None` (no tray icon). The deprecation warning from `libayatana-appindicator` is suppressed via `GLib.log_set_handler`.
