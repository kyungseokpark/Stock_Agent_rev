# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


project_root = Path(SPECPATH).parent
ttkb_datas, ttkb_binaries, ttkb_hidden = collect_all("ttkbootstrap")
data_files = [
    (str(path), str(Path("data") / path.relative_to(project_root / "data").parent))
    for path in (project_root / "data").rglob("*")
    if path.is_file()
    and "cache" not in path.relative_to(project_root / "data").parts
    and path.name != "screener_history.db"
]


a = Analysis(
    [str(project_root / "desktop_app.py")],
    pathex=[str(project_root)],
    binaries=[
        *ttkb_binaries,
    ],
    datas=[
        (str(project_root / "configs"), "configs"),
        *data_files,
        (str(project_root / "tickers.csv"), "."),
        (str(project_root / "tickers_kr.csv"), "."),
        (str(project_root / "매뉴얼.html"), "."),
        *ttkb_datas,
    ],
    hiddenimports=[
        *ttkb_hidden,
        "bs4",
        "html5lib",
        "lxml",
        "matplotlib",
        "matplotlib.backends.backend_tkagg",
        "pyarrow",
        "pyarrow.compute",
        "pyarrow.lib",
        "pyarrow.parquet",
        "pykrx",
        "yfinance",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StockAgentDAD",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="StockAgentDAD",
)
