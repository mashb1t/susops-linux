# PyInstaller spec for susops-tray
# Bundles the Python app into a single executable.
# System GTK3 / GI libraries are expected to be present (standard on GNOME/GTK desktops).

import os
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# GI typelibs to include (namespace, version)
_gi_typelibs = [
    ('Gtk',                  '3.0'),
    ('Gdk',                  '3.0'),
    ('GLib',                 '2.0'),
    ('GObject',              '2.0'),
    ('Gio',                  '2.0'),
    ('GdkPixbuf',            '2.0'),
    ('Pango',                '1.0'),
    ('PangoCairo',           '1.0'),
    ('AyatanaAppIndicator3', '0.1'),
    ('AppIndicator3',        '0.1'),
]

datas = []

# Collect typelib files from the system GI repository
_typelib_dirs = [
    '/usr/lib/girepository-1.0',
    '/usr/lib/x86_64-linux-gnu/girepository-1.0',
    '/usr/lib64/girepository-1.0',
]
for ns, ver in _gi_typelibs:
    typelib = f'{ns}-{ver}.typelib'
    for d in _typelib_dirs:
        path = os.path.join(d, typelib)
        if os.path.exists(path):
            datas.append((path, 'gi_typelibs'))
            break

# Bundle susops.sh and icon.png directly into the binary root
_susops_sh = os.path.join(os.path.dirname(SPEC), 'susops-cli', 'susops.sh')
if os.path.exists(_susops_sh):
    datas.append((_susops_sh, '.'))

# Bundle the app icon
_icon_candidates = [
    os.path.join(os.path.dirname(SPEC), 'susops-cli', 'icon.png'),
    os.path.join(os.path.dirname(SPEC), 'icon.png'),
]
for _icon in _icon_candidates:
    if os.path.exists(_icon):
        datas.append((_icon, '.'))
        break

a = Analysis(
    [os.path.join(os.path.dirname(SPEC), 'susops_tray.py')],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'gi',
        'gi.repository.Gtk',
        'gi.repository.GLib',
        'gi.repository.GObject',
        'gi.repository.Gio',
        'gi.repository.Gdk',
        'gi.repository.GdkPixbuf',
        'gi.repository.Pango',
        'gi.repository.PangoCairo',
    ],
    hookspath=[],
    hooksconfig={
        'gi': {
            'module-versions': {ns: ver for ns, ver in _gi_typelibs},
        },
    },
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='susops-tray',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    onefile=True,
)
