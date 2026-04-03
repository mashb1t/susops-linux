# File Transfer Menu Items — Design Spec

**Date:** 2026-04-03
**Feature:** Add "Share File" and "Fetch File" to the SusOps tray app

---

## Overview

Add a **File Transfer** submenu exposing `susops share` (long-running file server) and `susops fetch` (one-shot download) via GUI. Multiple simultaneous shares are supported. Each active share appears as its own menu item; clicking it opens a Share Info dialog.

---

## Menu Structure

New submenu placed after "Launch Browser", before the separator above "Reset All":

```
File Transfer
  ├─ Share File…
  ├─ Fetch File…
  ├─ ─── (separator — hidden when no shares in list)
  ├─ 📤 document.pdf (port 54321)      ← RUNNING share
  └─ 📤 notes.txt (port 54987) ●       ← STOPPED share (stopped indicator)
```

Active-share menu items are added/removed dynamically. The separator is shown whenever `_active_shares` is non-empty, hidden otherwise.

---

## Share lifecycle

```
User clicks "Share File…"
  → ShareFileDialog collects inputs
  → tray app generates password (if blank) and port (if blank)
  → Popen started; entry appended to _active_shares (state=RUNNING)
  → menu item added; separator shown
  → ShareInfoDialog opened (non-modal) showing file/port/password

Share process exits (any reason)
  → _on_share_exited(entry) called on GTK main thread
  → entry['state'] = 'stopped'; menu item label updated (add ●)
  → if entry['info_dlg'] is open: switch dialog to STOPPED state
  → _poll() called (CLI restarts proxy on clean exit)

User clicks "Share Again" in stopped ShareInfoDialog
  → new Popen with same file/password/port
  → entry updated (state=RUNNING, new proc)
  → menu item label restored (remove ●)
  → dialog switches back to RUNNING state

User clicks "Close" on stopped ShareInfoDialog
  → entry removed from _active_shares
  → menu item removed; hide separator if list now empty

User clicks "Close" on running ShareInfoDialog
  → dialog dismissed; share keeps running; entry['info_dlg'] = None
```

---

## ShareFileDialog

Fields (`_labeled_grid`):

| Field | Widget | Required | Notes |
|---|---|---|---|
| Connection | `ComboBoxText` | Yes | `ConfigHelper.get_connection_tags()` |
| File | `Gtk.FileChooserButton` (open mode) | Yes | |
| Password | `Gtk.Entry`, placeholder "auto-generated" | No | Blank → `secrets.token_hex(16)` |
| Port | `Gtk.Entry`, placeholder "auto" | No | Blank → `_free_port()` |

Validation before starting:
- Connection selected
- File exists and is readable (`os.path.isfile`)
- Port in 1–65535 if specified

Command:
```python
subprocess.Popen(
    [SUSOPS_SH, '-c', conn, 'share', file_path, password, str(port)],
    start_new_session=True,   # gives the process its own process group for clean SIGINT
)
```

---

## ShareInfoDialog

Non-modal `Gtk.Dialog`. Opened when user clicks an active-share menu item (or immediately after starting a share).

Layout:
```
Share Info — <basename>

File:      /full/path/to/file.txt
Port:      54321
Password:  [Entry visibility=False]  [👁 toggle button]

[Stop]    [Close]        ← RUNNING state
  — or —
[Share Again]  [Close]   ← STOPPED state
```

- **Eye toggle**: `entry.set_visibility(not entry.get_visibility())`
- **Copy Password** button (always visible): copies password to `Gtk.Clipboard`
- **Stop**: `os.killpg(os.getpgid(proc.pid), signal.SIGINT)`; button becomes insensitive immediately to prevent double-clicks
- **Share Again**: new `Popen` with same params; entry updated in place; dialog switches to RUNNING state
- **Close (RUNNING)**: `dialog.hide()`; `entry['info_dlg'] = None`
- **Close (STOPPED)**: removes entry from `_active_shares`, removes menu item, hides separator if list empty, destroys dialog

`_on_share_exited(entry)` updates an open dialog live:
- Replaces "Stop" button with "Share Again" (hide/show)
- Appends `●` to dialog title

---

## FetchFileDialog

Fields (`_labeled_grid`):

| Field | Widget | Required | Notes |
|---|---|---|---|
| Connection | `ComboBoxText` | Yes | |
| Port | `Gtk.Entry` | Yes | Port the share server is listening on |
| Password | `Gtk.Entry` | Yes | With eye toggle (hidden by default) |
| Save As | `Gtk.Label` (shows chosen path) + "Browse…" `Gtk.Button` | Yes | |

- "Browse…" opens `Gtk.FileChooserDialog` (save mode); on confirm path stored, label updated
- **OK / Fetch button insensitive** until save path chosen
- On Fetch: button goes insensitive, a "Downloading…" label shown inside dialog
- Command: `run_async(f'-c "{conn}" fetch {port} {password} {shlex.quote(outfile)}', callback, timeout=120)`

`_on_fetch_done(out, rc)`:
- `rc == 0`: close dialog, `_alert` "File saved to `<outfile>`"
- `rc != 0`: re-enable button, hide spinner label, show error alert (dialog stays open for retry)

---

## New utility

```python
def _free_port() -> int:
    """Return a random free local port."""
    with socket.socket() as s:
        s.bind(('', 0))
        return s.getsockname()[1]
```

---

## New `SusOpsApp` state

```python
self._active_shares   = []     # list of share entry dicts (see below)
self._share_sep       = None   # Gtk.SeparatorMenuItem — hidden when list empty
self._dlg_share       = None   # ShareFileDialog (persistent, reused)
self._dlg_fetch       = None   # FetchFileDialog (persistent, reused)
```

Share entry dict:
```python
{
    'proc':      Popen,
    'port':      str,
    'password':  str,
    'file_path': str,
    'state':     'running' | 'stopped',
    'menu_item': Gtk.MenuItem,
    'info_dlg':  ShareInfoDialog | None,
}
```

---

## Error / edge cases

| Scenario | Handling |
|---|---|
| Share starts but proxy not running | CLI exits non-zero; `_on_share_exited` shows error; entry moves to STOPPED |
| Port conflict on "Share Again" | Same: CLI exits non-zero, entry back to STOPPED |
| File deleted before "Share Again" | Re-validate `os.path.isfile` before new `Popen`; show error if missing |
| Fetch wrong password | CLI exits non-zero; dialog stays open for retry |
| No connections configured | Guard check before opening either dialog; `_alert` "Add a connection first." |
| App quit while shares active | `_on_quit` iterates `_active_shares`, sends SIGINT to each running proc's group before `Gtk.main_quit()` |