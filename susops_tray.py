#!/usr/bin/python3
"""SusOps System Tray Application for Linux — feature parity with susops-mac."""

import gi
gi.require_version('Gtk', '3.0')

import os
import re
import shutil
import subprocess
import threading
from enum import Enum
from pathlib import Path
from typing import Optional

from gi.repository import Gtk, GLib, Gdk, GdkPixbuf, Pango

# ── AppIndicator detection ────────────────────────────────────────────────────
_INDICATOR_BACKEND = None
try:
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AyatanaAppIndicator3 as _AI3
    _INDICATOR_BACKEND = 'ayatana'
except (ValueError, ImportError):
    try:
        gi.require_version('AppIndicator3', '0.1')
        from gi.repository import AppIndicator3 as _AI3
        _INDICATOR_BACKEND = 'appindicator'
    except (ValueError, ImportError):
        _AI3 = None

# ── Paths ─────────────────────────────────────────────────────────────────────
import sys
_here        = os.path.dirname(os.path.abspath(__file__))
_bundle      = getattr(sys, '_MEIPASS', None)  # set by PyInstaller at runtime
WORKSPACE    = os.path.expanduser('~/.susops')
CONFIG_PATH  = os.path.join(WORKSPACE, 'config.yaml')
AUTOSTART_DIR  = os.path.expanduser('~/.config/autostart')
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, 'org.susops.App.desktop')

SUSOPS_SH = next(
    (os.path.realpath(p) for p in [
        os.path.join(_bundle, 'susops.sh') if _bundle else None,
        os.path.join(_here, '..', 'susops-cli', 'susops.sh'),
        '/usr/lib/susops/susops.sh',
        '/app/share/susops/susops.sh',
        os.path.expanduser('~/.local/share/susops/susops.sh'),
    ] if p and os.path.exists(p)),
    None,
)

ICON_PATH = next(
    (p for p in [
        os.path.join(_bundle, 'icon.png') if _bundle else None,
        '/app/share/icons/hicolor/128x128/apps/org.susops.App.png',
        os.path.join(_here, '..', 'susops-cli', 'icon.png'),
        os.path.join(_here, 'icon.png'),
    ] if p and os.path.exists(p)),
    '',
)

# Search order for the per-state SVG icon directory
_ICONS_DIR = next(
    (p for p in [
        os.path.join(_bundle, 'icons') if _bundle else None,
        os.path.join(_here, 'icons'),
        os.path.expanduser('~/.local/share/susops/icons'),
    ] if p and os.path.isdir(p)),
    None,
)

def _is_dark_theme() -> bool:
    """Return True when the desktop is using a dark colour scheme."""
    try:
        import subprocess
        out = subprocess.run(
            ['gsettings', 'get', 'org.gnome.desktop.interface', 'color-scheme'],
            capture_output=True, text=True, timeout=2).stdout.strip()
        if 'dark' in out.lower():
            return True
        out = subprocess.run(
            ['gsettings', 'get', 'org.gnome.desktop.interface', 'gtk-theme'],
            capture_output=True, text=True, timeout=2).stdout.strip()
        return 'dark' in out.lower()
    except Exception:
        return False

def _state_icon_path(state_name: str, logo_style=None) -> str:
    """Return absolute path to the PNG (converted from SVG) for the given state name."""
    if not _ICONS_DIR:
        return ICON_PATH
    variant = 'light' if _is_dark_theme() else 'dark'
    # Resolve logo style — fall back to default if not set or icons missing
    style = logo_style if logo_style is not None else DEFAULT_LOGO_STYLE
    style_name = style.dir_name
    svg = os.path.join(_ICONS_DIR, style_name, variant, f'{state_name}.svg')
    if not os.path.exists(svg):
        # Fall back to colored_glasses
        style_name = DEFAULT_LOGO_STYLE.dir_name
        svg = os.path.join(_ICONS_DIR, style_name, variant, f'{state_name}.svg')
        if not os.path.exists(svg):
            return ICON_PATH
    # Convert SVG → PNG into a per-user cache dir (22 px — standard tray size)
    cache_dir = os.path.expanduser('~/.cache/susops/icons')
    os.makedirs(cache_dir, exist_ok=True)
    png = os.path.join(cache_dir, f'{style_name}_{state_name}_{variant}.png')
    if not os.path.exists(png):
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_size(svg, 22, 22)
            pb.savev(png, 'png', [], [])
        except Exception:
            return ICON_PATH
    return png

from version import VERSION
BIND_ADDRESSES = ['localhost', '172.17.0.1', '0.0.0.0']


# ── Enums ─────────────────────────────────────────────────────────────────────
class ProcessState(Enum):
    INITIAL           = ('initial',           '⚫', 'stopped')
    RUNNING           = ('running',           '🟢', 'running')
    STOPPED_PARTIALLY = ('stopped partially', '🟠', 'stopped_partially')
    STOPPED           = ('stopped',           '⚫', 'stopped')
    ERROR             = ('error',             '🔴', 'error')

    @property
    def label(self):    return self.value[0]
    @property
    def dot(self):      return self.value[1]
    @property
    def icon_name(self): return self.value[2]


class LogoStyle(Enum):
    GEAR            = 'GEAR'
    COLORED_GLASSES = 'COLORED_GLASSES'
    COLORED_S       = 'COLORED_S'

    @property
    def dir_name(self) -> str:
        return self.value.lower()

    @property
    def display_name(self) -> str:
        return self.value.replace('_', ' ').title()


DEFAULT_LOGO_STYLE = LogoStyle.COLORED_GLASSES


# ── Config helper (direct yq access, mirrors macOS ConfigHelper) ──────────────
class ConfigHelper:
    @staticmethod
    def read(query: str, default: str = '') -> str:
        if not os.path.exists(CONFIG_PATH):
            return default
        try:
            r = subprocess.run(['yq', 'e', query, CONFIG_PATH],
                               capture_output=True, text=True, timeout=5)
            out = r.stdout.strip()
            return default if (out == 'null' or r.returncode != 0) else out
        except Exception:
            return default

    @staticmethod
    def write(query: str) -> bool:
        os.makedirs(WORKSPACE, exist_ok=True)
        try:
            subprocess.run(['yq', 'e', '-i', query, CONFIG_PATH],
                           check=True, timeout=5)
            return True
        except Exception as exc:
            print(f'Config write error: {exc}')
            return False

    @staticmethod
    def get_connection_tags() -> list[str]:
        out = ConfigHelper.read('.connections[].tag')
        return [t for t in out.splitlines() if t]

    @staticmethod
    def get_domains() -> list[str]:
        out = ConfigHelper.read('.connections[].pac_hosts[]')
        return [d for d in out.splitlines() if d]

    @staticmethod
    def get_local_forwards() -> list[str]:
        q = r'.connections[].forwards.local[] | "\(.tag) (\((.src_port // .src)) → \((.dst_port // .dst)))"'
        out = ConfigHelper.read(q)
        return [f for f in out.splitlines() if f and f != '( → )']

    @staticmethod
    def get_remote_forwards() -> list[str]:
        q = r'.connections[].forwards.remote[] | "\(.tag) (\((.src_port // .src)) → \((.dst_port // .dst)))"'
        out = ConfigHelper.read(q)
        return [f for f in out.splitlines() if f and f != '( → )']

    @staticmethod
    def load_app_config() -> dict:
        logo_style_raw = ConfigHelper.read('.susops_app.logo_style', DEFAULT_LOGO_STYLE.value)
        if logo_style_raw.upper() not in LogoStyle.__members__:
            logo_style_raw = DEFAULT_LOGO_STYLE.value
        return {
            'pac_server_port':  ConfigHelper.read('.pac_server_port', '0'),
            'stop_on_quit':     ConfigHelper.read('.susops_app.stop_on_quit', '1') == '1',
            'ephemeral_ports':  ConfigHelper.read('.susops_app.ephemeral_ports', '1') == '1',
            'logo_style':       logo_style_raw.upper(),
        }


# ── SSH host discovery (from ~/.ssh/config) ───────────────────────────────────
def get_ssh_hosts() -> list[str]:
    cfg = Path(os.path.expanduser('~/.ssh/config'))
    if not cfg.exists():
        return []
    hosts = []
    pattern = re.compile(r'^\s*Host\s+(.*)$', re.IGNORECASE)
    for line in cfg.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = pattern.match(line)
        if m:
            for h in m.group(1).split():
                if '*' not in h and '?' not in h:   # skip wildcards
                    hosts.append(h)
    return hosts


# ── Browser autodiscovery ─────────────────────────────────────────────────────
_BROWSER_DEFS = [
    # (display_name, executables, chromium_based, has_proxy_settings)
    ('Chrome',   ['google-chrome', 'google-chrome-stable'],           True,  True),
    ('Chromium', ['chromium', 'chromium-browser'],                    True,  True),
    ('Brave',    ['brave-browser', 'brave', 'brave-browser-stable'],  True,  True),
    ('Vivaldi',  ['vivaldi', 'vivaldi-stable'],                       True,  False),
    ('Opera',    ['opera'],                                           True,  False),
    ('Edge',     ['microsoft-edge', 'microsoft-edge-stable'],         True,  False),
    ('Firefox',  ['firefox', 'firefox-bin'],                          False, False),
]


def _find_exe(names: list[str]) -> Optional[str]:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def discover_browsers() -> list[dict]:
    """Return list of installed browser dicts with keys: name, exe, chromium, settings."""
    found = []
    for name, exes, chromium, settings in _BROWSER_DEFS:
        exe = _find_exe(exes)
        if exe:
            found.append({'name': name, 'exe': exe, 'chromium': chromium, 'settings': settings})
    return found


# ── susops command execution ──────────────────────────────────────────────────
def _build_cmd(susops_args: str) -> list[str]:
    if SUSOPS_SH:
        cmd = [SUSOPS_SH] + susops_args.split()
    else:
        cmd = ['susops'] + susops_args.split()

    return cmd


def run_cmd(susops_args: str, timeout: int = 30) -> tuple[str, int]:
    """Run susops command. Returns (combined stdout+stderr, returncode)."""
    try:
        r = subprocess.run(_build_cmd(susops_args),
                           capture_output=True, text=True, timeout=timeout)
        # Prefer stdout; fall back to stderr so errors are never silently swallowed
        out = r.stdout.strip() or r.stderr.strip()
        return out, r.returncode
    except subprocess.TimeoutExpired:
        return 'Command timed out', 1
    except Exception as exc:
        return str(exc), 1


def run_async(susops_args: str, callback, timeout: int = 30):
    """Run susops command in background; call callback(stdout, rc) on GTK main thread."""
    def _worker():
        out, rc = run_cmd(susops_args, timeout)
        GLib.idle_add(callback, out, rc)
    threading.Thread(target=_worker, daemon=True).start()


def open_path(path: str):
    try:
        subprocess.Popen(['xdg-open', path])
    except Exception:
        pass


def launch_browser(exe: str, args: list[str]):
    try:
        subprocess.Popen([exe] + args)
    except FileNotFoundError as exc:
        raise RuntimeError(str(exc))


# ── Validation helpers ────────────────────────────────────────────────────────
def is_valid_port(value: str) -> bool:
    return value.isdigit() and 1 <= int(value) <= 65535


# ── GTK helpers ───────────────────────────────────────────────────────────────
def _alert(parent, title: str, body: str = '', msg_type=Gtk.MessageType.INFO):
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True,
                            message_type=msg_type,
                            buttons=Gtk.ButtonsType.CLOSE, text=title)
    if body:
        dlg.format_secondary_text(body)
    dlg.run(); dlg.destroy()


def _confirm(parent, title: str, body: str = '', ok_label='OK') -> bool:
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True,
                            message_type=Gtk.MessageType.QUESTION,
                            buttons=Gtk.ButtonsType.NONE, text=title)
    if body:
        dlg.format_secondary_text(body)
    dlg.add_buttons('_Cancel', Gtk.ResponseType.CANCEL,
                    ok_label, Gtk.ResponseType.OK)
    dlg.set_default_response(Gtk.ResponseType.OK)
    resp = dlg.run(); dlg.destroy()
    return resp == Gtk.ResponseType.OK


def _combobox_text(options: list[str], selected: int = 0) -> Gtk.ComboBoxText:
    cb = Gtk.ComboBoxText()
    for opt in options:
        cb.append_text(opt)
    if options:
        cb.set_active(selected)
    return cb


def _entry_with_completion(options: list[str]) -> Gtk.Entry:
    entry = Gtk.Entry()
    if options:
        store = Gtk.ListStore(str)
        for o in options:
            store.append([o])
        comp = Gtk.EntryCompletion(model=store)
        comp.set_text_column(0)
        comp.set_inline_completion(True)
        entry.set_completion(comp)
    return entry


def _labeled_grid(fields: list) -> tuple[Gtk.Grid, dict]:
    """
    fields: list of (key, label, widget)
    Returns (grid, {key: widget}).
    """
    grid = Gtk.Grid(column_spacing=12, row_spacing=8,
                    margin_start=16, margin_end=16,
                    margin_top=16, margin_bottom=8)
    widgets = {}
    for row, (key, label, widget) in enumerate(fields):
        lbl = Gtk.Label(label=label, xalign=1.0)
        lbl.set_width_chars(22)
        grid.attach(lbl, 0, row, 1, 1)
        widget.set_hexpand(True)
        grid.attach(widget, 1, row, 1, 1)
        widgets[key] = widget
    return grid, widgets


# ── Connection selector row (used in Add dialogs) ─────────────────────────────
def _make_connection_row() -> Gtk.ComboBoxText:
    cb = Gtk.ComboBoxText()
    for t in ConfigHelper.get_connection_tags():
        cb.append_text(t)
    if cb.get_model() and cb.get_model().iter_n_children() > 0:
        cb.set_active(0)
    return cb


# ── Settings dialog ───────────────────────────────────────────────────────────
class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, app):
        super().__init__(title='Settings', transient_for=parent, modal=True)
        self._app = app
        self.set_default_size(360, -1)
        self.set_border_width(0)

        self.add_buttons('_Cancel', Gtk.ResponseType.CANCEL,
                         '_Save',   Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        box = self.get_content_area()

        grid = Gtk.Grid(column_spacing=12, row_spacing=10,
                        margin_start=16, margin_end=16,
                        margin_top=16, margin_bottom=8)
        box.add(grid)

        row = 0

        # Launch at Login
        lbl = Gtk.Label(label='Launch at Login:', xalign=1.0)
        lbl.set_width_chars(24)
        grid.attach(lbl, 0, row, 1, 1)
        self._launch_at_login = Gtk.Switch(halign=Gtk.Align.START)
        self._launch_at_login.set_active(os.path.exists(AUTOSTART_FILE))
        grid.attach(self._launch_at_login, 1, row, 1, 1)
        row += 1

        # Stop Proxy On Quit
        lbl = Gtk.Label(label='Stop Proxy On Quit:', xalign=1.0)
        lbl.set_width_chars(24)
        grid.attach(lbl, 0, row, 1, 1)
        self._stop_on_quit = Gtk.Switch(halign=Gtk.Align.START)
        self._stop_on_quit.set_active(app.config.get('stop_on_quit', True))
        grid.attach(self._stop_on_quit, 1, row, 1, 1)
        row += 1

        # Random SSH Ports On Start
        lbl = Gtk.Label(label='Random SSH Ports On Start:', xalign=1.0)
        lbl.set_width_chars(24)
        grid.attach(lbl, 0, row, 1, 1)
        self._ephemeral = Gtk.Switch(halign=Gtk.Align.START)
        self._ephemeral.set_active(app.config.get('ephemeral_ports', True))
        grid.attach(self._ephemeral, 1, row, 1, 1)
        row += 1

        # Logo Style
        lbl = Gtk.Label(label='Logo Style:', xalign=1.0)
        lbl.set_width_chars(24)
        grid.attach(lbl, 0, row, 1, 1)
        self._logo_style = Gtk.ComboBoxText(halign=Gtk.Align.START)
        for style in LogoStyle:
            self._logo_style.append(style.value, style.display_name)
        self._logo_style.set_active_id(app.config.get('logo_style', DEFAULT_LOGO_STYLE.value))
        self._logo_style.connect('changed', self._on_logo_style_changed)
        grid.attach(self._logo_style, 1, row, 1, 1)
        row += 1

        # PAC Server Port
        lbl = Gtk.Label(label='PAC Server Port:', xalign=1.0)
        lbl.set_width_chars(24)
        grid.attach(lbl, 0, row, 1, 1)
        self._pac_port = Gtk.Entry(activates_default=True)
        pac_val = app.config.get('pac_server_port', '0')
        self._pac_port.set_text(pac_val if pac_val != '0' else '')
        self._pac_port.set_placeholder_text('auto (0)')
        grid.attach(self._pac_port, 1, row, 1, 1)

        self.show_all()

    def _on_logo_style_changed(self, combo):
        """Live-preview the selected icon style in the tray."""
        style_id = combo.get_active_id()
        if style_id and style_id in LogoStyle.__members__:
            self._app.config['logo_style'] = style_id
            self._app._update_tray_icon(self._app._state)

    def run(self) -> bool:
        """Show dialog, save on OK. Returns True if saved."""
        while True:
            resp = super().run()
            if resp != Gtk.ResponseType.OK:
                # Revert any live-preview changes
                self._app.config = ConfigHelper.load_app_config()
                self._app._update_tray_icon(self._app._state)
                self.hide()
                return False

            pac = self._pac_port.get_text().strip() or '0'
            if pac != '0' and not is_valid_port(pac):
                _alert(self, 'Invalid Port',
                       'PAC Server Port must be between 1 and 65535.')
                continue

            # Save to config
            ConfigHelper.write(f'.pac_server_port = {pac}')
            stop = '1' if self._stop_on_quit.get_active() else '0'
            ConfigHelper.write(f'.susops_app.stop_on_quit = "{stop}"')
            eph = '1' if self._ephemeral.get_active() else '0'
            ConfigHelper.write(f'.susops_app.ephemeral_ports = "{eph}"')
            logo = self._logo_style.get_active_id() or DEFAULT_LOGO_STYLE.value
            ConfigHelper.write(f'.susops_app.logo_style = "{logo}"')

            # Autostart
            self._apply_autostart(self._launch_at_login.get_active())

            self.hide()
            return True

    def _apply_autostart(self, enable: bool):
        if enable:
            os.makedirs(AUTOSTART_DIR, exist_ok=True)
            exec_line = f'Exec=python3 {os.path.abspath(__file__)}'
            content = (
                '[Desktop Entry]\n'
                'Name=SusOps\n'
                f'{exec_line}\n'
                'Icon=org.susops.App\n'
                'Type=Application\n'
                'X-GNOME-Autostart-enabled=true\n'
            )
            with open(AUTOSTART_FILE, 'w') as f:
                f.write(content)
        else:
            try:
                os.remove(AUTOSTART_FILE)
            except FileNotFoundError:
                pass


# ── Add Connection dialog ─────────────────────────────────────────────────────
class AddConnectionDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, app):
        super().__init__(title='Add Connection', transient_for=parent, modal=True)
        self._app = app
        self.set_default_size(440, -1)
        self.add_buttons('_Cancel', Gtk.ResponseType.CANCEL,
                         '_Add',   Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        self._tag  = Gtk.Entry(activates_default=True)
        self._host = _entry_with_completion(get_ssh_hosts())
        self._host.set_activates_default(True)
        self._port = Gtk.Entry(placeholder_text='auto if blank', activates_default=True)

        grid, _ = _labeled_grid([
            ('tag',  'Connection Tag *:',          self._tag),
            ('host', 'SSH Host *:',                self._host),
            ('port', 'SOCKS Proxy Port (optional):', self._port),
        ])
        self.get_content_area().add(grid)
        self.show_all()

    def run(self):
        while True:
            resp = super().run()
            if resp != Gtk.ResponseType.OK:
                self.hide(); return

            tag  = self._tag.get_text().strip()
            host = self._host.get_text().strip()
            port = self._port.get_text().strip()

            if not tag:
                _alert(self, 'Missing Field', 'Connection Tag must not be empty.',
                       Gtk.MessageType.ERROR); continue
            if not tag.replace('-', '').replace('_', '').isalnum():
                _alert(self, 'Invalid Tag',
                       'Connection Tag must contain only letters, digits, hyphens and underscores.',
                       Gtk.MessageType.ERROR); continue
            if not host:
                _alert(self, 'Missing Field', 'SSH Host must not be empty.',
                       Gtk.MessageType.ERROR); continue
            if port and not is_valid_port(port):
                _alert(self, 'Invalid Port',
                       'SOCKS Proxy Port must be between 1 and 65535.',
                       Gtk.MessageType.ERROR); continue

            cmd = f'add-connection "{tag}" {host} {port}'
            self.hide()
            run_async(cmd, lambda out, rc: self._on_done(out, rc))
            return

    def _on_done(self, out: str, rc: int):
        if rc == 0:
            _alert(self._app._root, 'Connection Added', out)
        else:
            _alert(self._app._root, 'Error', out, Gtk.MessageType.ERROR)
        self._tag.set_text(''); self._host.set_text(''); self._port.set_text('')


# ── Add Domain / IP / CIDR dialog ─────────────────────────────────────────────
class AddHostDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, app):
        super().__init__(title='Add Domain / IP / CIDR', transient_for=parent, modal=True)
        self._app = app
        self.set_default_size(380, -1)
        self.add_buttons('_Cancel', Gtk.ResponseType.CANCEL,
                         '_Add',   Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        box = self.get_content_area()

        self._conn = _make_connection_row()
        self._host = Gtk.Entry(activates_default=True)

        grid, _ = _labeled_grid([
            ('conn', 'Connection *:',      self._conn),
            ('host', 'Host / IP / CIDR *:', self._host),
        ])
        box.add(grid)

        info = Gtk.Label(
            label='Host can be:\n'
                  '  • Domain  (subdomains & wildcards supported)\n'
                  '  • IP address  (CIDR notation supported)',
            xalign=0, margin_start=16, margin_bottom=12)
        info.get_style_context().add_class('dim-label')
        box.add(info)
        self.show_all()

    def run(self):
        # refresh connections each time
        tags = ConfigHelper.get_connection_tags()
        model = self._conn.get_model()
        model.clear()
        for t in tags:
            self._conn.append_text(t)
        if tags:
            self._conn.set_active(0)

        while True:
            resp = super().run()
            if resp != Gtk.ResponseType.OK:
                self.hide(); return

            tag  = self._conn.get_active_text() or ''
            host = self._host.get_text().strip()
            if not tag:
                _alert(self, 'No Connection', 'Add a connection first.', Gtk.MessageType.ERROR); continue
            if not host:
                _alert(self, 'Missing Field', 'Host must not be empty.', Gtk.MessageType.ERROR); continue

            cmd = f'-c "{tag}" add {host}'
            self.hide()
            run_async(cmd, lambda out, rc: self._on_done(out, rc))
            return

    def _on_done(self, out: str, rc: int):
        if rc == 0:
            _alert(self._app._root, 'Host Added', out)
        else:
            _alert(self._app._root, 'Error', out, Gtk.MessageType.ERROR)
        self._host.set_text('')


# ── Add Local Forward dialog ──────────────────────────────────────────────────
class AddLocalForwardDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, app):
        super().__init__(title='Add Local Forward', transient_for=parent, modal=True)
        self._app = app
        self.set_default_size(400, -1)
        self.add_buttons('_Cancel', Gtk.ResponseType.CANCEL,
                         '_Add',   Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        self._conn        = _make_connection_row()
        self._tag         = Gtk.Entry(placeholder_text='optional', activates_default=True)
        self._local_port  = Gtk.Entry(placeholder_text='e.g. 8080', activates_default=True)
        self._remote_port = Gtk.Entry(placeholder_text='e.g. 80',   activates_default=True)
        self._local_addr  = _combobox_text(BIND_ADDRESSES)
        self._remote_addr = _combobox_text(BIND_ADDRESSES)

        grid, _ = _labeled_grid([
            ('conn',   'Connection *:',           self._conn),
            ('tag',    'Tag (optional):',          self._tag),
            ('lport',  'Forward Local Port *:',    self._local_port),
            ('rport',  'To Remote Port *:',        self._remote_port),
            ('laddr',  'Local Bind (optional):',   self._local_addr),
            ('raddr',  'Remote Bind (optional):',  self._remote_addr),
        ])
        self.get_content_area().add(grid)
        self.show_all()

    def run(self):
        tags = ConfigHelper.get_connection_tags()
        model = self._conn.get_model(); model.clear()
        for t in tags: self._conn.append_text(t)
        if tags: self._conn.set_active(0)

        while True:
            resp = super().run()
            if resp != Gtk.ResponseType.OK:
                self.hide(); return

            conn  = self._conn.get_active_text() or ''
            tag   = self._tag.get_text().strip()
            lport = self._local_port.get_text().strip()
            rport = self._remote_port.get_text().strip()
            laddr = self._local_addr.get_active_text() or ''
            raddr = self._remote_addr.get_active_text() or ''

            if not conn:
                _alert(self, 'No Connection', 'Add a connection first.', Gtk.MessageType.ERROR); continue
            if not is_valid_port(lport):
                _alert(self, 'Invalid Port', 'Local Port must be 1–65535.', Gtk.MessageType.ERROR); continue
            if not is_valid_port(rport):
                _alert(self, 'Invalid Port', 'Remote Port must be 1–65535.', Gtk.MessageType.ERROR); continue

            cmd = f'-c "{conn}" add -l {lport} {rport} "{tag}" "{laddr}" "{raddr}"'
            self.hide()
            run_async(cmd, lambda out, rc: self._on_done(out, rc))
            return

    def _on_done(self, out: str, rc: int):
        if rc == 0:
            self._app._show_restart_if_running('Local Forward Added', out)
            self._tag.set_text(''); self._local_port.set_text(''); self._remote_port.set_text('')
        else:
            _alert(self._app._root, 'Error', out, Gtk.MessageType.ERROR)


# ── Add Remote Forward dialog ─────────────────────────────────────────────────
class AddRemoteForwardDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, app):
        super().__init__(title='Add Remote Forward', transient_for=parent, modal=True)
        self._app = app
        self.set_default_size(400, -1)
        self.add_buttons('_Cancel', Gtk.ResponseType.CANCEL,
                         '_Add',   Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        self._conn        = _make_connection_row()
        self._tag         = Gtk.Entry(placeholder_text='optional', activates_default=True)
        self._remote_port = Gtk.Entry(placeholder_text='e.g. 8080', activates_default=True)
        self._local_port  = Gtk.Entry(placeholder_text='e.g. 3000', activates_default=True)
        self._remote_addr = _combobox_text(BIND_ADDRESSES)
        self._local_addr  = _combobox_text(BIND_ADDRESSES)

        grid, _ = _labeled_grid([
            ('conn',   'Connection *:',           self._conn),
            ('tag',    'Tag (optional):',          self._tag),
            ('rport',  'Forward Remote Port *:',   self._remote_port),
            ('lport',  'To Local Port *:',         self._local_port),
            ('raddr',  'Remote Bind (optional):',  self._remote_addr),
            ('laddr',  'Local Bind (optional):',   self._local_addr),
        ])
        self.get_content_area().add(grid)
        self.show_all()

    def run(self):
        tags = ConfigHelper.get_connection_tags()
        model = self._conn.get_model(); model.clear()
        for t in tags: self._conn.append_text(t)
        if tags: self._conn.set_active(0)

        while True:
            resp = super().run()
            if resp != Gtk.ResponseType.OK:
                self.hide(); return

            conn  = self._conn.get_active_text() or ''
            tag   = self._tag.get_text().strip()
            rport = self._remote_port.get_text().strip()
            lport = self._local_port.get_text().strip()
            raddr = self._remote_addr.get_active_text() or ''
            laddr = self._local_addr.get_active_text() or ''

            if not conn:
                _alert(self, 'No Connection', 'Add a connection first.', Gtk.MessageType.ERROR); continue
            if not is_valid_port(rport):
                _alert(self, 'Invalid Port', 'Remote Port must be 1–65535.', Gtk.MessageType.ERROR); continue
            if not is_valid_port(lport):
                _alert(self, 'Invalid Port', 'Local Port must be 1–65535.', Gtk.MessageType.ERROR); continue

            cmd = f'-c "{conn}" add -r {rport} {lport} "{tag}" "{raddr}" "{laddr}"'
            self.hide()
            run_async(cmd, lambda out, rc: self._on_done(out, rc))
            return

    def _on_done(self, out: str, rc: int):
        if rc == 0:
            self._app._show_restart_if_running('Remote Forward Added', out)
            self._tag.set_text(''); self._remote_port.set_text(''); self._local_port.set_text('')
        else:
            _alert(self._app._root, 'Error', out, Gtk.MessageType.ERROR)


# ── Generic remove dialog (dropdown + Remove button) ──────────────────────────
class _RemoveDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, app, title: str, label: str):
        super().__init__(title=title, transient_for=parent, modal=True)
        self._app = app
        self.set_default_size(340, -1)
        self.add_buttons('_Cancel', Gtk.ResponseType.CANCEL,
                         '_Remove', Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        self._combo = Gtk.ComboBoxText(hexpand=True)
        grid, _ = _labeled_grid([(label, label + ':', self._combo)])
        self.get_content_area().add(grid)
        self.show_all()

    def _refresh(self, items: list[str]):
        self._combo.remove_all()
        for item in items:
            self._combo.append_text(item)
        if items:
            self._combo.set_active(0)

    def _get_command(self, value: str) -> str:
        raise NotImplementedError

    def run(self):
        self._refresh(self._get_items())
        while True:
            resp = super().run()
            if resp != Gtk.ResponseType.OK:
                self.hide(); return
            value = self._combo.get_active_text()
            if not value:
                _alert(self, 'Nothing Selected', 'Select an item to remove.', Gtk.MessageType.ERROR); continue
            cmd = self._get_command(value)
            self.hide()
            run_async(cmd, lambda out, rc: self._on_done(out, rc))
            return

    def _on_done(self, out: str, rc: int):
        if rc == 0:
            _alert(self._app._root, 'Removed', out)
        else:
            _alert(self._app._root, 'Error', out, Gtk.MessageType.ERROR)

    def _get_items(self) -> list[str]:
        raise NotImplementedError


class RemoveConnectionDialog(_RemoveDialog):
    def __init__(self, p, a): super().__init__(p, a, 'Remove Connection', 'Connection Tag')
    def _get_items(self): return ConfigHelper.get_connection_tags()
    def _get_command(self, v): return f'rm-connection {v}'


class RemoveHostDialog(_RemoveDialog):
    def __init__(self, p, a): super().__init__(p, a, 'Remove Domain / IP / CIDR', 'Host')
    def _get_items(self): return ConfigHelper.get_domains()
    def _get_command(self, v): return f'rm {v}'


class RemoveLocalForwardDialog(_RemoveDialog):
    def __init__(self, p, a): super().__init__(p, a, 'Remove Local Forward', 'Local Forward')
    def _get_items(self): return ConfigHelper.get_local_forwards()
    def _get_command(self, v):
        m = re.search(r'\((\d+)', v)
        return f'rm -l {m.group(1)}' if m else ''


class RemoveRemoteForwardDialog(_RemoveDialog):
    def __init__(self, p, a): super().__init__(p, a, 'Remove Remote Forward', 'Remote Forward')
    def _get_items(self): return ConfigHelper.get_remote_forwards()
    def _get_command(self, v):
        m = re.search(r'\((\d+)', v)
        return f'rm -r {m.group(1)}' if m else ''


# ── About dialog ──────────────────────────────────────────────────────────────
class AboutDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window):
        super().__init__(title='About SusOps', transient_for=parent, modal=True)
        self.set_default_size(300, -1)
        self.add_button('_Close', Gtk.ResponseType.CLOSE)

        box = self.get_content_area()
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                       margin_start=20, margin_end=20, margin_top=16, margin_bottom=12,
                       halign=Gtk.Align.CENTER)
        box.add(vbox)

        if os.path.exists(ICON_PATH):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_size(ICON_PATH, 64, 64)
                vbox.pack_start(Gtk.Image.new_from_pixbuf(pb), False, False, 0)
            except Exception:
                pass

        name_lbl = Gtk.Label()
        name_lbl.set_markup('<b><big>SusOps</big></b>')
        vbox.pack_start(name_lbl, False, False, 2)

        ver_lbl = Gtk.Label(label=f'Version {VERSION}')
        ver_lbl.get_style_context().add_class('dim-label')
        vbox.pack_start(ver_lbl, False, False, 0)

        for text, url in [
            ('GitHub (Linux)', 'https://github.com/mashb1t/susops-linux'),
            ('GitHub (CLI)',   'https://github.com/mashb1t/susops-cli'),
            ('Sponsor',        'https://github.com/sponsors/mashb1t'),
            ('Report a Bug',   'https://github.com/mashb1t/susops-linux/issues/new'),
        ]:
            btn = Gtk.LinkButton(uri=url, label=text)
            vbox.pack_start(btn, False, False, 0)

        copy_lbl = Gtk.Label(label='Copyright © Manuel Schmid')
        copy_lbl.get_style_context().add_class('dim-label')
        vbox.pack_start(copy_lbl, False, False, 4)

        self.show_all()

    def run(self):
        super().run(); self.hide()


# ── Main application ──────────────────────────────────────────────────────────
class SusOpsApp:
    def __init__(self):
        self._state  = ProcessState.INITIAL
        self._root   = Gtk.Window()
        self._root.set_title('SusOps')
        self.config  = ConfigHelper.load_app_config()

        # Persistent dialog instances (created once, reused)
        self._dlg_settings     = None
        self._dlg_add_conn     = None
        self._dlg_add_host     = None
        self._dlg_add_local    = None
        self._dlg_add_remote   = None
        self._dlg_rm_conn      = None
        self._dlg_rm_host      = None
        self._dlg_rm_local     = None
        self._dlg_rm_remote    = None
        self._dlg_about        = None

        self._menu = self._build_menu()
        self._setup_indicator()

        # Startup: check state once, then poll every 5 s
        GLib.idle_add(self._startup_check)
        GLib.timeout_add_seconds(5, self._poll)

    # ── Indicator setup ───────────────────────────────────────────────────────

    def _current_logo_style(self) -> LogoStyle:
        return LogoStyle[self.config.get('logo_style', DEFAULT_LOGO_STYLE.value)]

    def _setup_indicator(self):
        icon = _state_icon_path(ProcessState.STOPPED.icon_name, self._current_logo_style()) or ICON_PATH or 'network-vpn'
        if _INDICATOR_BACKEND:
            self._indicator = _AI3.Indicator.new(
                'org.susops.App', icon,
                _AI3.IndicatorCategory.APPLICATION_STATUS)
            # Tell AppIndicator where to find our per-state PNG files
            cache_dir = os.path.expanduser('~/.cache/susops/icons')
            if os.path.isdir(cache_dir):
                self._indicator.set_icon_theme_path(cache_dir)
            self._indicator.set_status(_AI3.IndicatorStatus.ACTIVE)
            self._indicator.set_menu(self._menu)
        else:
            self._si = Gtk.StatusIcon()
            self._update_status_icon(ProcessState.STOPPED)
            self._si.set_tooltip_text('SusOps'); self._si.set_visible(True)
            self._si.connect('activate',   lambda i: self._menu.popup(None, None, None, None, 0, Gtk.get_current_event_time()))
            self._si.connect('popup-menu', lambda i, b, t: self._menu.popup(None, None, None, None, b, t))

    def _update_tray_icon(self, state: 'ProcessState'):
        try:
            icon_path = _state_icon_path(state.icon_name, self._current_logo_style())
            if _INDICATOR_BACKEND:
                if icon_path and os.path.exists(icon_path):
                    # AppIndicator needs icon name (no path, no extension) + theme path set
                    icon_name = os.path.splitext(os.path.basename(icon_path))[0]
                    self._indicator.set_icon_theme_path(os.path.dirname(icon_path))
                    self._indicator.set_icon_full(icon_name, state.label)
                else:
                    self._indicator.set_icon_full(ICON_PATH or 'network-vpn', state.label)
            elif hasattr(self, '_si'):
                self._update_status_icon(state)
        except Exception:
            pass

    def _update_status_icon(self, state: 'ProcessState'):
        icon = _state_icon_path(state.icon_name, self._current_logo_style())
        if icon and os.path.exists(icon):
            self._si.set_from_file(icon)
        elif os.path.exists(ICON_PATH):
            self._si.set_from_file(ICON_PATH)
        else:
            self._si.set_from_icon_name('network-vpn')

    # ── Menu construction ─────────────────────────────────────────────────────

    def _build_menu(self) -> Gtk.Menu:
        m = Gtk.Menu()

        # ── Status row ────────────────────────────────────────────────────────
        self._status_item = Gtk.MenuItem()
        self._status_label = Gtk.Label()
        self._status_label.set_halign(Gtk.Align.START)
        self._status_label.set_use_markup(True)
        self._status_label.set_markup(f'{ProcessState.INITIAL.dot} <b>Status:</b> checking…')
        self._status_item.add(self._status_label)
        self._status_item.connect('activate', self._on_check_status)
        m.append(self._status_item)
        m.append(Gtk.SeparatorMenuItem())

        # ── Settings ──────────────────────────────────────────────────────────
        i = Gtk.MenuItem(label='Settings…')
        i.connect('activate', self._on_settings)
        m.append(i)
        m.append(Gtk.SeparatorMenuItem())

        # ── Add submenu ───────────────────────────────────────────────────────
        add_item = Gtk.MenuItem(label='Add')
        add_sub  = Gtk.Menu()
        for label, cb in [
            ('Add Connection',         self._on_add_connection),
            ('Add Domain / IP / CIDR', self._on_add_host),
            ('Add Local Forward',      self._on_add_local),
            ('Add Remote Forward',     self._on_add_remote),
        ]:
            si = Gtk.MenuItem(label=label); si.connect('activate', cb); add_sub.append(si)
        add_item.set_submenu(add_sub); m.append(add_item)

        # ── Remove submenu ────────────────────────────────────────────────────
        rm_item = Gtk.MenuItem(label='Remove')
        rm_sub  = Gtk.Menu()
        for label, cb in [
            ('Remove Connection',         self._on_rm_connection),
            ('Remove Domain / IP / CIDR', self._on_rm_host),
            ('Remove Local Forward',      self._on_rm_local),
            ('Remove Remote Forward',     self._on_rm_remote),
        ]:
            si = Gtk.MenuItem(label=label); si.connect('activate', cb); rm_sub.append(si)
        rm_item.set_submenu(rm_sub); m.append(rm_item)

        # ── List All / Open Config ────────────────────────────────────────────
        i = Gtk.MenuItem(label='List All')
        i.connect('activate', self._on_list_all); m.append(i)
        i = Gtk.MenuItem(label='Open Config File')
        i.connect('activate', lambda _: open_path(CONFIG_PATH)); m.append(i)
        m.append(Gtk.SeparatorMenuItem())

        # ── Proxy controls ────────────────────────────────────────────────────
        self._start_item = Gtk.MenuItem(label='Start Proxy')
        self._start_item.connect('activate', self._on_start); m.append(self._start_item)

        self._stop_item = Gtk.MenuItem(label='Stop Proxy')
        self._stop_item.connect('activate', self._on_stop); m.append(self._stop_item)

        self._restart_item = Gtk.MenuItem(label='Restart Proxy')
        self._restart_item.connect('activate', self._on_restart); m.append(self._restart_item)
        m.append(Gtk.SeparatorMenuItem())

        # ── Test submenu ──────────────────────────────────────────────────────
        test_item = Gtk.MenuItem(label='Test')
        test_sub  = Gtk.Menu()
        self._test_any_item = Gtk.MenuItem(label='Test Any')
        self._test_any_item.connect('activate', self._on_test_any)
        test_sub.append(self._test_any_item)
        self._test_all_item = Gtk.MenuItem(label='Test All')
        self._test_all_item.connect('activate', self._on_test_all)
        test_sub.append(self._test_all_item)
        test_item.set_submenu(test_sub); m.append(test_item)

        # ── Launch Browser (built dynamically) ────────────────────────────────
        self._browser_item = Gtk.MenuItem(label='Launch Browser')
        m.append(self._browser_item)
        self._rebuild_browser_submenu()
        m.append(Gtk.SeparatorMenuItem())

        # ── Reset All ─────────────────────────────────────────────────────────
        i = Gtk.MenuItem(label='Reset All')
        i.connect('activate', self._on_reset); m.append(i)
        m.append(Gtk.SeparatorMenuItem())

        # ── About / Quit ──────────────────────────────────────────────────────
        i = Gtk.MenuItem(label='About SusOps')
        i.connect('activate', self._on_about); m.append(i)
        i = Gtk.MenuItem(label='Quit')
        i.connect('activate', self._on_quit); m.append(i)

        m.show_all()
        return m

    def _rebuild_browser_submenu(self):
        browsers = discover_browsers()
        browser_sub = Gtk.Menu()

        if not browsers:
            i = Gtk.MenuItem(label='No browsers found')
            i.set_sensitive(False)
            browser_sub.append(i)
        else:
            for b in browsers:
                if b['chromium']:
                    # Chrome-like: submenu with Launch + Proxy Settings
                    parent = Gtk.MenuItem(label=b['name'])
                    sub = Gtk.Menu()
                    li = Gtk.MenuItem(label=f"Launch {b['name']}")
                    li.connect('activate', self._make_chromium_launch(b))
                    sub.append(li)
                    if b.get('settings'):
                        si = Gtk.MenuItem(label=f"Open {b['name']} Proxy Settings")
                        si.connect('activate', self._make_chromium_settings(b))
                        sub.append(si)
                    parent.set_submenu(sub)
                    browser_sub.append(parent)
                else:
                    # Firefox-like: single Launch item
                    parent = Gtk.MenuItem(label=b['name'])
                    sub = Gtk.Menu()
                    li = Gtk.MenuItem(label=f"Launch {b['name']}")
                    li.connect('activate', self._make_firefox_launch(b))
                    sub.append(li)
                    parent.set_submenu(sub)
                    browser_sub.append(parent)

        browser_sub.show_all()
        self._browser_item.set_submenu(browser_sub)

    # ── Browser launch factories ──────────────────────────────────────────────

    def _get_pac_port(self) -> str:
        return ConfigHelper.read('.pac_server_port', '0')

    def _make_chromium_launch(self, b: dict):
        def handler(_item):
            port = self._get_pac_port()
            if port == '0':
                _alert(self._root, 'Proxy Not Running',
                       'Start the proxy first so the PAC port is known.')
                return
            try:
                launch_browser(b['exe'],
                               [f'--proxy-pac-url=http://localhost:{port}/susops.pac'])
            except RuntimeError as exc:
                _alert(self._root, 'Launch Failed', str(exc), Gtk.MessageType.ERROR)
        return handler

    def _make_chromium_settings(self, b: dict):
        def handler(_item):
            url = 'chrome://net-internals/#proxy'
            try:
                launch_browser(b['exe'], [])
            except RuntimeError:
                pass
            # Show URL in a selectable entry — user presses Ctrl+C to copy
            dlg = Gtk.Dialog(title='Open Proxy Settings',
                             transient_for=self._root, modal=True)
            dlg.add_button('_OK', Gtk.ResponseType.OK)
            dlg.set_default_response(Gtk.ResponseType.OK)
            box = dlg.get_content_area()
            box.set_spacing(8)
            box.set_margin_start(16); box.set_margin_end(16)
            box.set_margin_top(12);  box.set_margin_bottom(8)
            box.add(Gtk.Label(
                label='Paste this URL into the browser address bar:',
                xalign=0.0))
            tv = Gtk.TextView()
            tv.get_buffer().set_text(url)
            tv.set_wrap_mode(Gtk.WrapMode.NONE)
            tv.set_monospace(True)
            tv.set_hexpand(True)
            box.add(tv)
            dlg.show_all()
            # Select all so Ctrl+C copies immediately
            buf = tv.get_buffer()
            buf.select_range(buf.get_start_iter(), buf.get_end_iter())
            tv.grab_focus()
            dlg.run()
            dlg.destroy()
        return handler

    def _make_firefox_launch(self, b: dict):
        def handler(_item):
            port = self._get_pac_port()
            if port == '0':
                _alert(self._root, 'Proxy Not Running',
                       'Start the proxy first so the PAC port is known.')
                return
            profile = os.path.join(WORKSPACE, 'firefox_profile')
            os.makedirs(profile, exist_ok=True)
            with open(os.path.join(profile, 'user.js'), 'w') as f:
                f.write(
                    'user_pref("network.proxy.type", 2);\n'
                    f'user_pref("network.proxy.autoconfig_url",'
                    f' "http://localhost:{port}/susops.pac");\n'
                )
            try:
                launch_browser(b['exe'], ['-profile', profile, '-no-remote'])
            except RuntimeError as exc:
                _alert(self._root, 'Launch Failed', str(exc), Gtk.MessageType.ERROR)
        return handler

    # ── State management ──────────────────────────────────────────────────────

    def _startup_check(self) -> bool:
        out, rc = run_cmd('ps', timeout=10)
        new_state = self._rc_to_state(rc)
        self._apply_state(new_state)

        # Welcome dialog if no connection configured
        if new_state == ProcessState.ERROR and 'no default connection found' in out:
            self._show_welcome()

        return False  # run once

    def _poll(self) -> bool:
        run_async('ps', self._on_poll_result, timeout=10)
        return True

    def _on_poll_result(self, out: str, rc: int):
        state = self._rc_to_state(rc)
        self._apply_state(state)

    @staticmethod
    def _rc_to_state(rc: int) -> ProcessState:
        return {
            0: ProcessState.RUNNING,
            2: ProcessState.STOPPED_PARTIALLY,
            3: ProcessState.STOPPED,
        }.get(rc, ProcessState.ERROR)

    def _apply_state(self, new_state: ProcessState):
        if new_state == self._state:
            return

        # Update status dot (emoji, immune to theme override) + label text
        self._status_label.set_markup(
            f'{new_state.dot} <b>Status:</b> {new_state.label}')
        self._status_item.show_all()

        # Update tray icon (wrapped in try/except inside _update_tray_icon)
        self._update_tray_icon(new_state)

        # Update menu item sensitivity (mirrors macOS behavior exactly)
        running = new_state == ProcessState.RUNNING
        partial = new_state == ProcessState.STOPPED_PARTIALLY
        error   = new_state == ProcessState.ERROR

        self._start_item.set_sensitive(not running and not error)
        self._stop_item.set_sensitive(running or partial)
        self._restart_item.set_sensitive(running or partial)
        self._test_any_item.set_sensitive(running or partial)
        self._test_all_item.set_sensitive(running or partial)

        # Only commit the new state once all UI updates have succeeded
        self._state = new_state

    # ── Welcome / init dialog ─────────────────────────────────────────────────

    def _show_welcome(self):
        dlg = Gtk.MessageDialog(
            transient_for=self._root, modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text='🎉 Welcome to SusOps 🎉')
        dlg.format_secondary_text(
            'To get started, please follow these steps:\n\n'
            '1. Add a connection  (Add → Add Connection)\n'
            '2. Start the proxy  (Start Proxy)\n\n'
            'If you need help, check About → GitHub.')
        dlg.run(); dlg.destroy()

    # ── Restart-if-running helper ─────────────────────────────────────────────

    def _show_restart_if_running(self, title: str, message: str):
        if self._state not in (ProcessState.RUNNING, ProcessState.STOPPED_PARTIALLY):
            _alert(self._root, title, message)
            return
        if _confirm(self._root, title,
                    message + '\n\nRestart proxy to apply?',
                    ok_label='Restart Proxy'):
            self._on_restart(None)
        else:
            _alert(self._root, title, message)

    # ── Settings ──────────────────────────────────────────────────────────────

    def _on_settings(self, _):
        self.config = ConfigHelper.load_app_config()
        if self._dlg_settings is None:
            self._dlg_settings = SettingsDialog(self._root, self)
        else:
            # Refresh values
            self._dlg_settings._stop_on_quit.set_active(self.config.get('stop_on_quit', True))
            self._dlg_settings._ephemeral.set_active(self.config.get('ephemeral_ports', True))
            pac = self.config.get('pac_server_port', '0')
            self._dlg_settings._pac_port.set_text(pac if pac != '0' else '')
            self._dlg_settings._launch_at_login.set_active(os.path.exists(AUTOSTART_FILE))
            self._dlg_settings._logo_style.set_active_id(
                self.config.get('logo_style', DEFAULT_LOGO_STYLE.value))

        if self._dlg_settings.run():
            self.config = ConfigHelper.load_app_config()
            self._show_restart_if_running('Settings Saved',
                                          'Settings will be applied on next proxy start.')

    # ── Add handlers ──────────────────────────────────────────────────────────

    def _on_add_connection(self, _):
        if self._dlg_add_conn is None:
            self._dlg_add_conn = AddConnectionDialog(self._root, self)
        self._dlg_add_conn.run()

    def _on_add_host(self, _):
        if self._dlg_add_host is None:
            self._dlg_add_host = AddHostDialog(self._root, self)
        self._dlg_add_host.run()

    def _on_add_local(self, _):
        if self._dlg_add_local is None:
            self._dlg_add_local = AddLocalForwardDialog(self._root, self)
        self._dlg_add_local.run()

    def _on_add_remote(self, _):
        if self._dlg_add_remote is None:
            self._dlg_add_remote = AddRemoteForwardDialog(self._root, self)
        self._dlg_add_remote.run()

    # ── Remove handlers ───────────────────────────────────────────────────────

    def _on_rm_connection(self, _):
        if self._dlg_rm_conn is None:
            self._dlg_rm_conn = RemoveConnectionDialog(self._root, self)
        self._dlg_rm_conn.run()

    def _on_rm_host(self, _):
        if self._dlg_rm_host is None:
            self._dlg_rm_host = RemoveHostDialog(self._root, self)
        self._dlg_rm_host.run()

    def _on_rm_local(self, _):
        if self._dlg_rm_local is None:
            self._dlg_rm_local = RemoveLocalForwardDialog(self._root, self)
        self._dlg_rm_local.run()

    def _on_rm_remote(self, _):
        if self._dlg_rm_remote is None:
            self._dlg_rm_remote = RemoveRemoteForwardDialog(self._root, self)
        self._dlg_rm_remote.run()

    # ── List All / Status ─────────────────────────────────────────────────────

    def _on_list_all(self, _):
        out, _ = run_cmd('ls')
        self._show_output('Domains & Forwards', out)

    def _on_check_status(self, _):
        out, _ = run_cmd('ps', timeout=10)
        self._show_output('SusOps Status', out or '(no output)')

    def _show_output(self, title: str, content: str):
        dlg = Gtk.Dialog(title=title, transient_for=self._root, modal=False)
        dlg.add_button('Close', Gtk.ResponseType.CLOSE)
        dlg.set_default_size(600, 380)
        dlg.connect('response', lambda d, _r: d.destroy())
        sw = Gtk.ScrolledWindow(vexpand=True, margin_start=12, margin_end=12,
                                margin_top=12, margin_bottom=6)
        tv = Gtk.TextView(editable=False, monospace=True,
                          wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=4)
        tv.get_buffer().set_text(content)
        sw.add(tv)
        dlg.get_content_area().add(sw)
        dlg.show_all()

    # ── Proxy controls ────────────────────────────────────────────────────────

    def _on_start(self, _):
        self._start_item.set_sensitive(False)
        self._status_label.set_markup(f'{ProcessState.INITIAL.dot} <b>Status:</b> starting…')
        run_async('start', self._after_proxy_cmd, timeout=60)

    def _on_stop(self, _):
        self._stop_item.set_sensitive(False)
        self._status_label.set_markup(f'{ProcessState.INITIAL.dot} <b>Status:</b> stopping…')
        keep = '--keep-ports' if not self.config.get('ephemeral_ports', True) else ''
        run_async(f'stop {keep}'.strip(), self._after_proxy_cmd, timeout=30)

    def _on_restart(self, _):
        self.config = ConfigHelper.load_app_config()
        self._restart_item.set_sensitive(False)
        self._status_label.set_markup(f'{ProcessState.INITIAL.dot} <b>Status:</b> restarting…')
        run_async('restart', self._after_proxy_cmd, timeout=60)

    def _after_proxy_cmd(self, out: str, rc: int):
        # Reset state so _apply_state always re-runs (buttons may have been
        # disabled by _on_start/_on_stop and must be re-enabled regardless
        # of whether the state actually changed)
        self._state = ProcessState.INITIAL
        self._poll()
        if rc != 0 and out:
            _alert(self._root, 'Error', out, Gtk.MessageType.ERROR)

    # ── Test ──────────────────────────────────────────────────────────────────

    def _on_test_any(self, _):
        dlg = Gtk.Dialog(title='Test Any', transient_for=self._root, modal=True)
        dlg.set_default_size(360, -1)
        dlg.add_buttons('_Cancel', Gtk.ResponseType.CANCEL,
                        '_Test',   Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        entry = Gtk.Entry(placeholder_text='domain or port number',
                          activates_default=True,
                          margin_start=16, margin_end=16,
                          margin_top=12, margin_bottom=8)
        dlg.get_content_area().add(entry)
        dlg.show_all()
        resp = dlg.run()
        target = entry.get_text().strip()
        dlg.destroy()
        if resp == Gtk.ResponseType.OK and target:
            out, _ = run_cmd(f'test {target}', timeout=30)
            self._show_output(f'Test: {target}', out)

    def _on_test_all(self, _):
        out, _ = run_cmd('test --all', timeout=60)
        self._show_output('SusOps Test All', out)

    # ── Reset ─────────────────────────────────────────────────────────────────

    def _on_reset(self, _):
        if not _confirm(
            self._root,
            'Reset Everything?',
            'This will stop SusOps and remove all of its configs.\n'
            'You will have to reconfigure the SSH host as well as ports.\n\n'
            'Are you sure?',
            ok_label='Reset Everything'
        ):
            return
        run_async('reset --force', lambda out, rc: (
            self.config.update(ConfigHelper.load_app_config()),
            self._poll()
        ))

    # ── About ─────────────────────────────────────────────────────────────────

    def _on_about(self, _):
        if self._dlg_about is None:
            self._dlg_about = AboutDialog(self._root)
        self._dlg_about.run()

    # ── Quit ──────────────────────────────────────────────────────────────────

    def _on_quit(self, _):
        if self.config.get('stop_on_quit', True):
            run_cmd('stop --keep-ports', timeout=15)
        Gtk.main_quit()


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    SusOpsApp()
    Gtk.main()


if __name__ == '__main__':
    main()
