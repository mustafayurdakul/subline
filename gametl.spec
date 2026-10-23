# PyInstaller spec: one-folder build with two executables sharing one
# runtime in dist/gametl/_internal:
#   gametl.exe      windowed tray app (output goes to %APPDATA%\gametl\gametl.log)
#   gametl-cli.exe  console build of the same entry point, for command-line
#                   use and `gametl-cli pretranslate ...`
# Models are not bundled; they download on first run into %APPDATA%\gametl\models.
# The licence, the third-party notices and every bundled component's licence
# text go next to the executables (LICENSE, THIRD_PARTY_NOTICES.md, licenses/).
# Build with:  uv run --group build python scripts/build.py

import re
from importlib import metadata
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

RUNTIME_DEPENDENCIES = [
    "windows-capture", "rapidocr", "onnxruntime-directml", "opencv-python-headless", "numpy", "pillow",
    "pyside6", "anthropic", "requests", "ctranslate2", "sentencepiece", "cryptography",
]  # fmt: skip


def runtime_distributions() -> list[metadata.Distribution]:
    """Every installed distribution the app depends on, transitively."""
    seen: dict[str, metadata.Distribution] = {}
    todo = list(RUNTIME_DEPENDENCIES)
    while todo:
        name = todo.pop()
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        seen[key] = dist
        for requirement in dist.requires or []:
            if "extra ==" in requirement:
                continue  # optional extras are not installed
            todo.append(re.split(r"[\s;<>=!~\[(]", requirement, maxsplit=1)[0])
    return sorted(seen.values(), key=lambda d: d.metadata["Name"].lower())


def licence_files() -> list[tuple[str, str]]:
    """(source, destination folder) pairs: each component's licence texts
    from its dist-info, plus texts the wheels do not carry."""
    pairs: list[tuple[str, str]] = []
    for dist in runtime_distributions():
        folder = f"licenses/{dist.metadata['Name']}"
        for file in dist.files or []:
            parts = file.parts
            if ".dist-info" not in parts[0]:
                continue
            name = parts[-1].lower()
            inside_licenses = len(parts) > 2 and parts[1] == "licenses"
            if inside_licenses or name.startswith(("license", "licence", "copying", "notice")):
                pairs.append((str(dist.locate_file(file)), folder))
    pairs += [
        (str(path), f"licenses/{path.parent.name}") for path in Path("licenses").glob("*/*")
    ]
    onnxruntime = Path(metadata.distribution("onnxruntime-directml").locate_file("onnxruntime"))
    for name in ("LICENSE", "ThirdPartyNotices.txt"):
        if (onnxruntime / name).exists():
            pairs.append((str(onnxruntime / name), "licenses/onnxruntime-directml"))
    return pairs


# config.yaml, default_models.yaml, fonts; not the models a dev install has
# downloaded into the package (they download on first run into %APPDATA%).
datas = [
    (src, dst)
    for src, dst in collect_data_files("rapidocr")
    if "/models/" not in src.replace("\\", "/")
]
datas += [("LICENSE", "."), ("THIRD_PARTY_NOTICES.md", ".")]
datas += licence_files()
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
]  # fmt: skip

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
