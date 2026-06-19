# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for vepub-backend sidecar.

Build:
    cd backend
    pyinstaller vepub-backend.spec

Output: backend/dist/vepub-backend/  (onedir)
Then copy the whole vepub-backend/ folder to:
    apps/desktop/src-tauri/binaries/vepub-backend-x86_64-pc-windows-msvc/

Tauri 2 externalBin expects a directory named after the target triple
if the binary is a directory (onedir). Or rename the exe to the triple suffix.
"""
import os
import sys

block_cipher = None

# llama_bin/ must be bundled so the server can find llama-server.exe at runtime
_llama_bin = os.path.join(os.getcwd(), "llama_bin")
_llama_datas = []
if os.path.isdir(_llama_bin):
    for f in os.listdir(_llama_bin):
        _llama_datas.append(
            (os.path.join(_llama_bin, f), "llama_bin")
        )

a = Analysis(
    ["sidecar_main.py"],
    pathex=[os.getcwd()],
    binaries=[],
    datas=[
        # 路由、服務、設定
        ("routers",  "routers"),
        ("services", "services"),
        ("config.py", "."),
        ("main.py",   "."),
    ] + _llama_datas,
    hiddenimports=[
        # FastAPI / Starlette
        "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
        "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan", "uvicorn.lifespan.on",
        # Pydantic / anyio
        "pydantic.v1", "anyio.from_thread",
        # sqlite3
        "sqlite3",
        # 常見 backend imports
        "ebooklib", "bs4", "lxml", "PIL",
        "httpx", "psutil",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 不打包 torch / diffusers / transformers（太大，執行時才 import）
        # 使用者須在 ~/.epub-tts/ 安裝這些 wheels，或透過系統 Python
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="vepub-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,   # 保留 console，sidecar 由 Tauri 在背景執行
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="vepub-backend",
)
