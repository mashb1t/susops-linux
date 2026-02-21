<p align="center">
    <img src="icon.png" alt="SusOps" height="200" />
</p>

# SusOps for Linux - SSH Utilities & SOCKS5 Operations

A native-feeling **system tray app** for the [**SusOps CLI**](https://github.com/mashb1t/susops-cli) SSH–proxy and forwarding toolkit.
**SusOps CLI** is already bundled as a submodule, no need to manually install it.

Built with GTK3 and AyatanaAppIndicator3, the app lets you start/stop the SusOps SOCKS proxy, add
local / remote port-forwards, and tweak settings without touching a terminal.

<img src="screenshots/menu.png" alt="Menu" height="400"/>

## Features

| Menu action                      | CLI equivalent                                              | What it does                                             |
|----------------------------------|-------------------------------------------------------------|----------------------------------------------------------|
| **Status**                       | `so ps`                                                     | Show running state and active forwards.                  |
| **Settings…**                    | edit dot‑files                                              | GUI for SSH host & port defaults; autostart; icon style. |
| **Add Domain / IP / CIDR**       | `so add <domain>`                                           | Add a domain, IP, or CIDR block to the PAC file.         |
| **Add Local Forward**            | `so add -l REMOTE LOCAL`                                    | Expose a remote service on `localhost:<LOCAL>`.          |
| **Add Remote Forward**           | `so add -r LOCAL REMOTE`                                    | Publish a local port on `ssh_host:<REMOTE>`.             |
| **Remove Domain / Forward**      | `so rm …`                                                   | Remove a domain or port-forward rule.                    |
| **List All**                     | `so ls`                                                     | Show all configured domains and forwards.                |
| **Open Config File**             | —                                                           | Open `~/.susops/config.yaml` in your default editor.     |
| **Start / Stop / Restart Proxy** | `so start`<br/>`so stop`<br/>`so restart`                   | Launch or tear down the SSH SOCKS5 proxy and PAC server. |
| **Test Any / Test All**          | `so test …`                                                 | Quick connectivity test dialogs.                         |
| **Launch Browser**               | `so firefox`<br/>`so chrome`<br/>`so chrome-proxy-settings` | Open a detected browser preconfigured with the PAC file. |
| **Reset All**                    | `so reset`                                                  | Remove all domains and port-forwards.                    |

## Requirements

* Linux with a system tray (GNOME + AppIndicator extension, KDE, XFCE, etc.)
* Python 3
* System packages:
  * `go-yq` (Mike Farah's yq v4) — **not** the Python-based `yq`
  * `autossh`
  * `netcat` / `openbsd-netcat`
  * `gtk3`
  * `python-gobject` (PyGObject)
  * `libayatana-appindicator`
* A remote host you have SSH access to

## Setup

### 1. Clone with submodule

```bash
git clone --recursive https://github.com/mashb1t/susops-linux.git
cd susops-linux
```

Or if you already cloned without `--recursive`:

```bash
git submodule update --init
```

### 2. Install dependencies and the app

```bash
./build.sh
```

`./build.sh` automatically detects your package manager (`pacman`, `apt`, `dnf`, `zypper`, `apk`) and installs system dependencies before installing the app.

- **Arch Linux** — installs as a proper pacman package via `makepkg`.
- **All other distros** — installs to `~/.local` (no root required for app files).

To uninstall:

```bash
./build.sh --uninstall
```

### 4. Configure

1. Launch the application (`susops-tray`)
2. Set up your SSH host and ports in the **Settings** menu
3. Start the proxy (tray icon turns green)
4. Add domains or port-forwards as needed

> [!TIP]
> You can configure the SSH host using `~/.ssh/config` to set up proxy jumps and multi-hop SSH connections.

> [!IMPORTANT]
> `go-yq` (Mike Farah's yq v4) is required. The Python-based `yq` package is **incompatible**.
> On Arch Linux: install `go-yq`, not `yq`.

## Development

```bash
# Clone with submodule
git clone --recursive https://github.com/mashb1t/susops-linux.git
cd susops-linux

# Run directly (uses system python-gobject, no venv needed)
python3 susops.py

# Test the installed version
./build.sh --run
```

> [!IMPORTANT]
> The [**SusOps CLI**](https://github.com/mashb1t/susops-cli) lives in its own repository and is included here as a **git submodule**.
> Make sure you clone with `--recursive` or run `git submodule update --init` after checkout.

## Runtime files

### Arch Linux (installed via pacman)

| Location                                          | Purpose                              |
|---------------------------------------------------|--------------------------------------|
| `~/.susops/`                                      | Config files shared with the CLI.    |
| `/usr/bin/susops-tray`                            | Launcher script.                     |
| `/usr/lib/susops/`                                | App files (script, icons, CLI).      |
| `/usr/share/applications/susops-tray.desktop`     | Desktop entry.                       |

### Other distros (installed to `~/.local`)

| Location                                               | Purpose                              |
|--------------------------------------------------------|--------------------------------------|
| `~/.susops/`                                           | Config files shared with the CLI.    |
| `~/.local/bin/susops-tray`                             | Launcher script.                     |
| `~/.local/lib/susops/`                                 | App files (script, icons, CLI).      |
| `~/.local/share/applications/susops-tray.desktop`      | Desktop entry.                       |

## How To Use SusOps As Docker Proxy

See [SusOps CLI Readme](https://github.com/mashb1t/susops-cli?tab=readme-ov-file#how-to-use-susops-as-docker-proxy)

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **Tray icon doesn't appear** | Install an AppIndicator extension. On GNOME: [AppIndicator and KStatusNotifierItem Support](https://extensions.gnome.org/extension/615/appindicator-support/). |
| **`susops-tray` not found after install** | Arch: ensure `/usr/bin` is in your `$PATH`. Other distros: add `export PATH="$HOME/.local/bin:$PATH"` to your shell profile. |
| **SusOps in state "error"** | Ensure you have configured a connection and `~/.susops/` exists. Run `so add-connection <tag> <ssh_host> <socks_port>` first. |
| **Proxy doesn't start** | Verify you can SSH to the host manually. Check that `go-yq` (v4) is installed, not the Python-based `yq`. |
| **`yq` errors in logs** | You have the wrong `yq`. Install `go-yq` (Arch: `sudo pacman -S go-yq`). |
| **Proxy shows as stopped even when running** | Known Linux behaviour — `autossh` process names aren't visible to `pgrep -x`. The app works around this automatically. |
| **Chrome doesn't pick up added domains** | Close Chrome fully and reopen it via **Launch Browser**. Then open Chrome Proxy Settings and click **Re-apply settings**. |
| **Firefox doesn't pick up added domains** | Close Firefox fully and reopen it via **Launch Browser**. |
| **Everything else** | See [Troubleshooting — SusOps CLI](https://github.com/mashb1t/susops-cli?tab=readme-ov-file#troubleshooting) or [report a bug](https://github.com/mashb1t/susops-linux/issues/new). |

## Contributing

1. Set up the project as described above in "Development".
2. Create a feature branch.
3. `python3 susops.py` while hacking the UI.
4. `./build.sh --run` to test the installed version.
5. Open a [PR](https://github.com/mashb1t/susops-linux/pulls).

## License

MIT © 2025 Manuel Schmid — see [LICENSE](LICENSE.txt).
[**SusOps CLI**](https://github.com/mashb1t/susops-cli) (submodule) retains its own [license](https://github.com/mashb1t/susops-cli/blob/main/LICENSE.txt).
