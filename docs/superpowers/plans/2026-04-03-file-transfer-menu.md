# File Transfer Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Share File and Fetch File menu items to the SusOps GTK tray app, backed by `susops share` and `susops fetch` CLI commands, with multiple simultaneous shares tracked as dynamic menu items.

**Architecture:** All changes live in `susops.py`. Three new dialog classes are added (`ShareFileDialog`, `ShareInfoDialog`, `FetchFileDialog`). `SusOpsApp` gains an `_active_shares` list and supporting methods. `FetchFileDialog` uses a signal-based (non-blocking) response pattern rather than the modal `super().run()` loop so the dialog can remain open and show "Downloading…" state while the async command runs.

**Tech Stack:** Python 3, GTK 3 (PyGObject), `subprocess.Popen` with `start_new_session=True` for share process isolation, `os.killpg` + `signal.SIGINT` for clean stop, `secrets.token_hex` for auto-passwords.

---

## File map

| File | Change |
|---|---|
| `susops.py` | All changes — imports, `_free_port()`, three new dialog classes, `SusOpsApp` additions |

No new files needed.

---

### Task 1: Add imports and `_free_port()` utility

**Files:**
- Modify: `susops.py:5-15` (imports block)
- Modify: `susops.py:318-320` (after `is_valid_port`)

- [ ] **Step 1: Add three missing imports**

Find the existing import block near the top of `susops.py` (lines 5-15):
```python
import os
import re
import shlex
import shutil
import subprocess
import threading
from enum import Enum
from pathlib import Path
from typing import Optional
```

Replace with:
```python
import os
import re
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import threading
from enum import Enum
from pathlib import Path
from typing import Optional
```

- [ ] **Step 2: Add `_free_port()` after `is_valid_port()`**

Find:
```python
def is_valid_port(value: str) -> bool:
    return value.isdigit() and 1 <= int(value) <= 65535
```

Replace with:
```python
def is_valid_port(value: str) -> bool:
    return value.isdigit() and 1 <= int(value) <= 65535


def _free_port() -> int:
    """Return a random free local port."""
    with socket.socket() as s:
        s.bind(('', 0))
        return s.getsockname()[1]
```

- [ ] **Step 3: Verify syntax**

```bash
cd /home/mashb1t/development/susops/susops-linux
python3 -c "import ast, sys; ast.parse(open('susops.py').read()); print('syntax ok')"
```

Expected output: `syntax ok`

- [ ] **Step 4: Commit**

```bash
git add susops.py
git commit -m "feat: add imports and _free_port() for file transfer"
```

---

### Task 2: Add `ShareFileDialog`

**Files:**
- Modify: `susops.py` — insert class after `RemoveRemoteForwardDialog` (~line 885)

- [ ] **Step 1: Insert `ShareFileDialog` class**

Find the line:
```python
# ── About dialog ──────────────────────────────────────────────────────────────
class AboutDialog(Gtk.Dialog):
```

Insert the following block immediately before it:
```python
# ── Share File dialog ─────────────────────────────────────────────────────────
class ShareFileDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, app):
        super().__init__(title='Share File', transient_for=parent, modal=True)
        self._app = app
        self.set_default_size(440, -1)
        self.add_buttons('_Cancel', Gtk.ResponseType.CANCEL,
                         '_Share',  Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        self._conn     = _make_connection_row()
        self._file_btn = Gtk.FileChooserButton(
            title='Select file to share',
            action=Gtk.FileChooserAction.OPEN)
        self._password = Gtk.Entry(placeholder_text='auto-generated',
                                   activates_default=True)
        self._port     = Gtk.Entry(placeholder_text='auto',
                                   activates_default=True)

        grid, _ = _labeled_grid([
            ('conn', 'Connection *:',         self._conn),
            ('file', 'File *:',               self._file_btn),
            ('pass', 'Password (optional):',  self._password),
            ('port', 'Port (optional):',      self._port),
        ])
        self.get_content_area().add(grid)
        _polish_dialog(self)
        self.show_all()

    def run(self):
        tags = ConfigHelper.get_connection_tags()
        model = self._conn.get_model(); model.clear()
        for t in tags: self._conn.append_text(t)
        if tags:
            self._conn.set_active(0)
        if not tags:
            self.hide()
            _alert(self._app._root, 'No Connection',
                   'Add a connection first.', Gtk.MessageType.ERROR)
            return

        while True:
            resp = super().run()
            if resp != Gtk.ResponseType.OK:
                self.hide(); return

            conn      = self._conn.get_active_text() or ''
            file_path = self._file_btn.get_filename() or ''
            password  = self._password.get_text().strip()
            port_str  = self._port.get_text().strip()

            if not file_path:
                _alert(self, 'No File Selected',
                       'Please select a file to share.',
                       Gtk.MessageType.ERROR); continue
            if not os.path.isfile(file_path):
                _alert(self, 'File Not Found',
                       f'File not found:\n{file_path}',
                       Gtk.MessageType.ERROR); continue
            if port_str and not is_valid_port(port_str):
                _alert(self, 'Invalid Port',
                       'Port must be between 1 and 65535.',
                       Gtk.MessageType.ERROR); continue

            password = password or secrets.token_hex(16)
            port     = int(port_str) if port_str else _free_port()

            self.hide()
            self._app._start_share(conn, file_path, password, str(port))
            return
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('susops.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
git add susops.py
git commit -m "feat: add ShareFileDialog"
```

---

### Task 3: Add `ShareInfoDialog`

**Files:**
- Modify: `susops.py` — insert class after `ShareFileDialog`

- [ ] **Step 1: Insert `ShareInfoDialog` class**

Find the line:
```python
# ── About dialog ──────────────────────────────────────────────────────────────
class AboutDialog(Gtk.Dialog):
```

Insert immediately before it (after `ShareFileDialog`):
```python
# ── Share Info dialog (non-modal, one per active share) ───────────────────────
class ShareInfoDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, app, entry: dict):
        self._entry = entry
        name = os.path.basename(entry['file_path'])
        super().__init__(title=f'Share Info — {name}',
                         transient_for=parent, modal=False)
        self._app = app
        self.set_default_size(420, -1)

        # ── Content grid ──────────────────────────────────────────────────────
        grid = Gtk.Grid(column_spacing=12, row_spacing=8,
                        margin_start=16, margin_end=16,
                        margin_top=16, margin_bottom=8)
        self.get_content_area().add(grid)

        def _lbl(text):
            l = Gtk.Label(label=text, xalign=1.0)
            l.set_width_chars(12)
            return l

        # File row
        grid.attach(_lbl('File:'), 0, 0, 1, 1)
        file_val = Gtk.Label(label=entry['file_path'], xalign=0.0, hexpand=True)
        file_val.set_ellipsize(Pango.EllipsizeMode.START)
        grid.attach(file_val, 1, 0, 1, 1)

        # Port row
        grid.attach(_lbl('Port:'), 0, 1, 1, 1)
        port_val = Gtk.Label(label=entry['port'], xalign=0.0, hexpand=True)
        grid.attach(port_val, 1, 1, 1, 1)

        # Password row: entry + eye toggle + copy button
        grid.attach(_lbl('Password:'), 0, 2, 1, 1)
        pass_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
                           hexpand=True)
        self._pass_entry = Gtk.Entry(text=entry['password'],
                                     editable=False, visibility=False,
                                     hexpand=True)
        pass_box.pack_start(self._pass_entry, True, True, 0)

        eye_btn = Gtk.ToggleButton()
        eye_btn.add(Gtk.Image.new_from_icon_name('view-reveal-symbolic',
                                                  Gtk.IconSize.BUTTON))
        eye_btn.connect('toggled',
                        lambda b: self._pass_entry.set_visibility(b.get_active()))
        pass_box.pack_start(eye_btn, False, False, 0)

        copy_btn = Gtk.Button(label='Copy')
        copy_btn.connect('clicked', self._on_copy_password)
        pass_box.pack_start(copy_btn, False, False, 0)
        grid.attach(pass_box, 1, 2, 1, 1)

        # ── Action buttons ────────────────────────────────────────────────────
        self._stop_btn  = self.add_button('Stop',          Gtk.ResponseType.APPLY)
        self._again_btn = self.add_button('Share Again',   Gtk.ResponseType.ACCEPT)
        self._close_btn = self.add_button('_Close',        Gtk.ResponseType.CLOSE)

        self.connect('response',     self._on_response)
        self.connect('delete-event', self._on_delete)

        self._sync_buttons()
        _polish_dialog(self)
        self.show_all()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _sync_buttons(self):
        running = self._entry['state'] == 'running'
        self._stop_btn.set_visible(running)
        self._stop_btn.set_no_show_all(not running)
        self._again_btn.set_visible(not running)
        self._again_btn.set_no_show_all(running)

    def _on_copy_password(self, _):
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clip.set_text(self._entry['password'], -1)

    # ── Response handling ─────────────────────────────────────────────────────

    def _on_response(self, _dlg, response):
        if response == Gtk.ResponseType.APPLY:          # Stop
            self._stop_btn.set_sensitive(False)
            self._app._stop_share(self._entry)
        elif response == Gtk.ResponseType.ACCEPT:       # Share Again
            self._app._restart_share(self._entry)
        elif response in (Gtk.ResponseType.CLOSE,
                          Gtk.ResponseType.DELETE_EVENT,
                          Gtk.ResponseType.NONE):
            if self._entry['state'] == 'stopped':
                self._app._remove_share_entry(self._entry)
            self._entry['info_dlg'] = None
            self.hide()

    def _on_delete(self, _dlg, _event):
        self._on_response(self, Gtk.ResponseType.CLOSE)
        return True  # suppress default destroy

    # ── Live update from _on_share_exited ────────────────────────────────────

    def update_to_stopped(self):
        name = os.path.basename(self._entry['file_path'])
        self.set_title(f'Share Info — {name} ●')
        self._stop_btn.set_sensitive(True)   # reset in case it was disabled
        self._sync_buttons()
        self.show_all()

    def update_to_running(self):
        name = os.path.basename(self._entry['file_path'])
        self.set_title(f'Share Info — {name}')
        self._stop_btn.set_sensitive(True)
        self._sync_buttons()
        self.show_all()
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('susops.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
git add susops.py
git commit -m "feat: add ShareInfoDialog"
```

---

### Task 4: Add `FetchFileDialog`

**Files:**
- Modify: `susops.py` — insert class after `ShareInfoDialog`

`FetchFileDialog` uses `connect('response', …)` + `present()` instead of the modal `super().run()` loop so the dialog stays visible and shows "Downloading…" while `run_async` executes.

- [ ] **Step 1: Insert `FetchFileDialog` class**

Find:
```python
# ── About dialog ──────────────────────────────────────────────────────────────
class AboutDialog(Gtk.Dialog):
```

Insert immediately before it:
```python
# ── Fetch File dialog (non-blocking modal to allow download status display) ───
class FetchFileDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, app):
        super().__init__(title='Fetch File', transient_for=parent, modal=False)
        self._app     = app
        self._outfile = None
        self.set_default_size(440, -1)

        self.add_buttons('_Cancel', Gtk.ResponseType.CANCEL,
                         '_Fetch',  Gtk.ResponseType.OK)
        self._fetch_btn = self.get_widget_for_response(Gtk.ResponseType.OK)
        self._fetch_btn.set_sensitive(False)
        self.set_default_response(Gtk.ResponseType.OK)

        self._conn = _make_connection_row()
        self._port = Gtk.Entry(placeholder_text='e.g. 54321',
                               activates_default=True)

        # Password with eye toggle
        pass_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
                           hexpand=True)
        self._password = Gtk.Entry(placeholder_text='password',
                                   visibility=False, activates_default=True,
                                   hexpand=True)
        pass_box.pack_start(self._password, True, True, 0)
        eye_btn = Gtk.ToggleButton()
        eye_btn.add(Gtk.Image.new_from_icon_name('view-reveal-symbolic',
                                                  Gtk.IconSize.BUTTON))
        eye_btn.connect('toggled',
                        lambda b: self._password.set_visibility(b.get_active()))
        pass_box.pack_start(eye_btn, False, False, 0)

        # Save As with Browse button
        save_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
                           hexpand=True)
        self._save_label = Gtk.Label(label='(not chosen)', xalign=0.0,
                                     hexpand=True)
        self._save_label.get_style_context().add_class('dim-label')
        save_box.pack_start(self._save_label, True, True, 0)
        browse_btn = Gtk.Button(label='Browse…')
        browse_btn.connect('clicked', self._on_browse)
        save_box.pack_start(browse_btn, False, False, 0)

        # Status label shown during download
        self._status_label = Gtk.Label(label='Downloading…', margin_bottom=8)
        self._status_label.set_no_show_all(True)

        grid, _ = _labeled_grid([
            ('conn', 'Connection *:', self._conn),
            ('port', 'Port *:',       self._port),
            ('pass', 'Password *:',   pass_box),
            ('save', 'Save As *:',    save_box),
        ])
        box = self.get_content_area()
        box.add(grid)
        box.add(self._status_label)

        self._port.connect('changed',     self._on_input_changed)
        self._password.connect('changed', self._on_input_changed)

        self.connect('response',     self._on_response)
        self.connect('delete-event', lambda d, e: d.hide() or True)

        _polish_dialog(self)
        self.show_all()

    # ── Open / refresh ────────────────────────────────────────────────────────

    def open(self):
        tags = ConfigHelper.get_connection_tags()
        model = self._conn.get_model(); model.clear()
        for t in tags: self._conn.append_text(t)
        if tags:
            self._conn.set_active(0)
        if not tags:
            _alert(self._app._root, 'No Connection',
                   'Add a connection first.', Gtk.MessageType.ERROR)
            return
        self.present()

    # ── Validation ────────────────────────────────────────────────────────────

    def _on_input_changed(self, *_):
        ok = (bool(self._outfile)
              and is_valid_port(self._port.get_text().strip())
              and bool(self._password.get_text().strip()))
        self._fetch_btn.set_sensitive(ok)

    # ── File chooser ──────────────────────────────────────────────────────────

    def _on_browse(self, _):
        chooser = Gtk.FileChooserDialog(
            title='Save fetched file as',
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE)
        chooser.add_buttons('_Cancel', Gtk.ResponseType.CANCEL,
                            '_Save',   Gtk.ResponseType.OK)
        chooser.set_do_overwrite_confirmation(True)
        if chooser.run() == Gtk.ResponseType.OK:
            self._outfile = chooser.get_filename()
            self._save_label.set_text(self._outfile)
            self._save_label.get_style_context().remove_class('dim-label')
        chooser.destroy()
        self._on_input_changed()

    # ── Response handling ─────────────────────────────────────────────────────

    def _on_response(self, _dlg, response):
        if response in (Gtk.ResponseType.CANCEL, Gtk.ResponseType.DELETE_EVENT,
                        Gtk.ResponseType.CLOSE, Gtk.ResponseType.NONE):
            self.hide()
            return
        if response != Gtk.ResponseType.OK:
            return

        conn     = self._conn.get_active_text() or ''
        port     = self._port.get_text().strip()
        password = self._password.get_text().strip()

        if not all([conn, is_valid_port(port), password, self._outfile]):
            return  # button guard prevents this in practice

        self._fetch_btn.set_sensitive(False)
        self._status_label.show()

        cmd = (f'-c "{conn}" fetch {port} '
               f'{shlex.quote(password)} {shlex.quote(self._outfile)}')
        run_async(cmd, self._on_fetch_done, timeout=120)

    # ── Fetch callback ────────────────────────────────────────────────────────

    def _on_fetch_done(self, out: str, rc: int):
        self._status_label.hide()
        if rc == 0:
            saved = self._outfile
            self.hide()
            self._reset_fields()
            _alert(self._app._root, 'Download Complete',
                   f'File saved to:\n{saved}')
        else:
            self._fetch_btn.set_sensitive(True)
            _alert(self, 'Download Failed', out, Gtk.MessageType.ERROR)

    def _reset_fields(self):
        self._outfile = None
        self._save_label.set_text('(not chosen)')
        self._save_label.get_style_context().add_class('dim-label')
        self._port.set_text('')
        self._password.set_text('')
        self._on_input_changed()
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('susops.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
git add susops.py
git commit -m "feat: add FetchFileDialog"
```

---

### Task 5: Update `SusOpsApp.__init__` and `_build_menu`

**Files:**
- Modify: `susops.py` — `SusOpsApp.__init__` and `SusOpsApp._build_menu`

- [ ] **Step 1: Add new instance variables to `__init__`**

Find the block of persistent dialog instance variables in `__init__`:
```python
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
```

Replace with:
```python
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
        self._dlg_share        = None
        self._dlg_fetch        = None
        self._active_shares    = []
        self._ft_sub           = None   # File Transfer Gtk.Menu (for dynamic item insertion)
        self._share_sep        = None   # separator shown when shares list is non-empty
```

- [ ] **Step 2: Add File Transfer submenu to `_build_menu`**

Find:
```python
        # ── Reset All ─────────────────────────────────────────────────────────
        i = Gtk.MenuItem(label='Reset All')
        i.connect('activate', self._on_reset); m.append(i)
        m.append(Gtk.SeparatorMenuItem())
```

Insert the following block immediately before it:
```python
        # ── File Transfer submenu ─────────────────────────────────────────────
        ft_item      = Gtk.MenuItem(label='File Transfer')
        self._ft_sub = Gtk.Menu()

        share_mi = Gtk.MenuItem(label='Share File…')
        share_mi.connect('activate', self._on_share_file)
        self._ft_sub.append(share_mi)

        fetch_mi = Gtk.MenuItem(label='Fetch File…')
        fetch_mi.connect('activate', self._on_fetch_file)
        self._ft_sub.append(fetch_mi)

        self._share_sep = Gtk.SeparatorMenuItem()
        self._ft_sub.append(self._share_sep)
        self._share_sep.hide()

        ft_item.set_submenu(self._ft_sub)
        m.append(ft_item)
        m.append(Gtk.SeparatorMenuItem())

```

- [ ] **Step 3: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('susops.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 4: Commit**

```bash
git add susops.py
git commit -m "feat: add File Transfer submenu skeleton to tray menu"
```

---

### Task 6: Add share management methods to `SusOpsApp`

**Files:**
- Modify: `susops.py` — insert methods into `SusOpsApp` before `_on_about`

- [ ] **Step 1: Insert all share management methods**

Find:
```python
    # ── About ─────────────────────────────────────────────────────────────────

    def _on_about(self, _):
```

Insert immediately before it:
```python
    # ── File Transfer — Share ─────────────────────────────────────────────────

    def _on_share_file(self, _):
        if self._dlg_share is None:
            self._dlg_share = ShareFileDialog(self._root, self)
        self._dlg_share.run()

    def _start_share(self, conn: str, file_path: str, password: str, port: str):
        cmd = ([SUSOPS_SH] if SUSOPS_SH else ['susops']) + [
            '-c', conn, 'share', file_path, password, port]
        proc = subprocess.Popen(cmd, start_new_session=True,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)

        name = os.path.basename(file_path)
        item = Gtk.MenuItem(label=f'📤 {name} (port {port})')
        entry = {
            'proc':      proc,
            'port':      port,
            'password':  password,
            'file_path': file_path,
            'conn':      conn,
            'state':     'running',
            'menu_item': item,
            'info_dlg':  None,
        }
        item.connect('activate', lambda _, e=entry: self._on_share_item_clicked(e))
        self._ft_sub.append(item)
        item.show()
        self._share_sep.show()
        self._active_shares.append(entry)

        def _watch():
            proc.wait()
            GLib.idle_add(self._on_share_exited, entry)
        threading.Thread(target=_watch, daemon=True).start()

        dlg = ShareInfoDialog(self._root, self, entry)
        entry['info_dlg'] = dlg
        dlg.show()

    def _on_share_item_clicked(self, entry: dict):
        if entry['info_dlg'] is None:
            dlg = ShareInfoDialog(self._root, self, entry)
            entry['info_dlg'] = dlg
        entry['info_dlg'].present()

    def _on_share_exited(self, entry: dict) -> bool:
        entry['state'] = 'stopped'
        name = os.path.basename(entry['file_path'])
        entry['menu_item'].set_label(f'📤 {name} (port {entry["port"]}) ●')
        if entry['info_dlg']:
            entry['info_dlg'].update_to_stopped()
        self._poll()
        return False  # one-shot GLib.idle_add

    def _stop_share(self, entry: dict):
        try:
            os.killpg(os.getpgid(entry['proc'].pid), signal.SIGINT)
        except (ProcessLookupError, OSError):
            pass

    def _restart_share(self, entry: dict):
        if not os.path.isfile(entry['file_path']):
            _alert(self._root, 'File Not Found',
                   f'File no longer exists:\n{entry["file_path"]}',
                   Gtk.MessageType.ERROR)
            return
        cmd = ([SUSOPS_SH] if SUSOPS_SH else ['susops']) + [
            '-c', entry['conn'], 'share',
            entry['file_path'], entry['password'], entry['port']]
        proc = subprocess.Popen(cmd, start_new_session=True,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        entry['proc']  = proc
        entry['state'] = 'running'
        name = os.path.basename(entry['file_path'])
        entry['menu_item'].set_label(f'📤 {name} (port {entry["port"]})')
        if entry['info_dlg']:
            entry['info_dlg'].update_to_running()

        def _watch():
            proc.wait()
            GLib.idle_add(self._on_share_exited, entry)
        threading.Thread(target=_watch, daemon=True).start()

    def _remove_share_entry(self, entry: dict):
        if entry in self._active_shares:
            self._active_shares.remove(entry)
        entry['menu_item'].destroy()
        if not self._active_shares:
            self._share_sep.hide()

    # ── File Transfer — Fetch ─────────────────────────────────────────────────

    def _on_fetch_file(self, _):
        if self._dlg_fetch is None:
            self._dlg_fetch = FetchFileDialog(self._root, self)
        self._dlg_fetch.open()

```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('susops.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
git add susops.py
git commit -m "feat: add share/fetch management methods to SusOpsApp"
```

---

### Task 7: Update `_on_quit` to clean up active shares

**Files:**
- Modify: `susops.py` — `SusOpsApp._on_quit`

- [ ] **Step 1: Update `_on_quit`**

Find:
```python
    def _on_quit(self, _):
        if self.config.get('stop_on_quit', True):
            run_cmd('stop --keep-ports', timeout=15)
        Gtk.main_quit()
```

Replace with:
```python
    def _on_quit(self, _):
        for entry in list(self._active_shares):
            if entry['state'] == 'running':
                try:
                    os.killpg(os.getpgid(entry['proc'].pid), signal.SIGINT)
                except (ProcessLookupError, OSError):
                    pass
        if self.config.get('stop_on_quit', True):
            run_cmd('stop --keep-ports', timeout=15)
        Gtk.main_quit()
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('susops.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
git add susops.py
git commit -m "feat: clean up active share processes on quit"
```

---

### Task 8: Smoke test

No automated test framework is configured. Verify by running the app.

- [ ] **Step 1: Start the app**

```bash
python3 susops.py &
```

Check that the tray icon appears and the menu opens without errors.

- [ ] **Step 2: Verify File Transfer submenu**

Open the tray menu. Confirm:
- "File Transfer" submenu appears between "Launch Browser" and "Reset All"
- It contains "Share File…" and "Fetch File…"
- No separator or share items are visible yet

- [ ] **Step 3: Test ShareFileDialog**

Click "Share File…". Confirm:
- Dialog opens with Connection, File, Password, Port fields
- Clicking Share without selecting a file shows "No File Selected" error
- Selecting a file and clicking Share with password + port blank generates both automatically
- After clicking Share: dialog closes, "Share Info" dialog opens showing file/port/password
- Password is hidden by default; eye toggle reveals it; Copy button works
- "📤 filename (port XXXX)" item appears in the File Transfer submenu
- Separator becomes visible

- [ ] **Step 4: Test Share Info dialog — Stop**

With a running share, click "Stop":
- Stop button becomes insensitive immediately
- After process exits: dialog title gains `●`, Stop button replaced by "Share Again"
- Menu item label gains `●`

- [ ] **Step 5: Test Share Info dialog — Share Again**

Click "Share Again" on a stopped share:
- New process starts
- `●` removed from title and menu item label
- Stop button returns

- [ ] **Step 6: Test Share Info dialog — Close on running share**

Click "Close" while share is running:
- Dialog hides, share keeps running
- Menu item stays visible
- Clicking menu item re-opens Share Info dialog

- [ ] **Step 7: Test Share Info dialog — Close on stopped share**

Click "Close" on a stopped share's dialog:
- Menu item removed
- Separator hidden if no other shares active

- [ ] **Step 8: Test FetchFileDialog**

Click "Fetch File…". Confirm:
- Dialog opens with Connection, Port, Password, Save As fields
- Fetch button is insensitive until Save As path chosen
- Password hidden by default; eye toggle reveals it
- "Browse…" opens a file save dialog
- After choosing a save path, Fetch button becomes active
- Clicking Fetch: button goes insensitive, "Downloading…" label appears
- On completion (or error): appropriate alert shown

- [ ] **Step 9: Test quit with active share**

Start a share, then quit via the tray menu. Confirm no zombie share processes remain:

```bash
pgrep -fa susops-sh
```

Expected: no output (all share processes cleaned up).

- [ ] **Step 10: Final commit**

```bash
git add susops.py
git commit -m "feat: implement File Transfer menu (share + fetch)"
```
