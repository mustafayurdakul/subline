# PyInstaller spec: one-folder build with two executables sharing one
# runtime in dist/gametl/_internal:
#   gametl.exe      windowed tray app (output goes to %APPDATA%\gametl\gametl.log)
#   gametl-cli.exe  console build of the same entry point, for command-line
#                   use and `gametl-cli pretranslate ...`
# Models are not bundled; they download on first run into %APPDATA%\gametl\models.
# Build with:  uv run --group build python scripts/build.py

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

# config.yaml, default_models.yaml, fonts; not the models a dev install has
# downloaded into the package (they download on first run into %APPDATA%).
datas = [
    (src, dst)
    for src, dst in collect_data_files("rapidocr")
    if "/models/" not in src.replace("\\", "/")
]
binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("onnxruntime")
hiddenimports = (
    collect_submodules("rapidocr")
    + collect_submodules("gametl")
    + ["shapely", "pyclipper", "omegaconf", "sentencepiece", "ctranslate2", "windows_capture"]
)
excludes = [
    "tkinter", "unittest", "pydoc", "matplotlib", "IPython", "notebook", "torch", "transformers",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtNetwork", "PySide6.QtOpenGL", "PySide6.QtPdf",
    "PySide6.QtSvg", "PySide6.QtMultimedia", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel", "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtQuickWidgets",
    "PySide6.QtQuick3D", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtBluetooth",
    "PySide6.QtNfc", "PySide6.QtSerialPort", "PySide6.QtSensors", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtHttpServer",
    "PySide6.QtWebSockets", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
    "PySide6.QtPrintSupport", "PySide6.QtConcurrent", "PySide6.QtDBus", "PySide6.QtGraphs",
    "PySide6.QtSpatialAudio", "PySide6.QtSerialBus",
]

a = Analysis(
    ["src/gametl/app/main.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe_tray = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="gametl",
    icon="build/gametl.ico",
    console=False,
    disable_windowed_traceback=False,
    upx=False,
)
exe_cli = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="gametl-cli",
    icon="build/gametl.ico",
    console=True,
    upx=False,
)
coll = COLLECT(
    exe_tray,
    exe_cli,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="gametl",
)
