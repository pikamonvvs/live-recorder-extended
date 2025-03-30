# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# streamlink 관련 모듈과 데이터 파일 수집
streamlink_hiddenimports = collect_submodules('streamlink.plugins')
streamlink_datas = collect_data_files('streamlink')

a = Analysis(
    ['main.py', 'utils.py', 'live-recorder/live_recorder.py'],
    pathex=[],
    binaries=[],
    datas=[
        *streamlink_datas,  # streamlink 데이터 파일 추가
    ],
    hiddenimports=[
        *streamlink_hiddenimports,  # streamlink 플러그인 모듈 추가
        'streamlink.plugins.*',
        'engineio.async_drivers.anyio',
        'charset_normalizer.md__mypyc',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure, 
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
