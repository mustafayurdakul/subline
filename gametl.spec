# PyInstaller spec: one-folder build with two executables sharing one
# runtime in dist/gametl/_internal:
#   gametl.exe      windowed tray app (output goes to %APPDATA%\gametl\gametl.log)
#   gametl-cli.exe  console build of the same entry point, for command-line
#                   use and `gametl-cli pretranslate ...`
# Models are not bundled; they download on first run into %APPDATA%\gametl\models.
# Neither is the offline translator's runtime (CTranslate2, SentencePiece, 60 MB
# for a translator most players never turn on): translate/offline.py fetches
# its wheels into %APPDATA%\gametl\runtime on the first download.
# The settings window is Qt Quick: its QML pages ship under gametl/app/qml and
# the Qt QML modules they import (QtQuick, Controls.Basic, Layouts) come from
# PySide6's qml folder, pruned to those modules. Qt itself is pruned to the
# libraries and plugins those modules and the widgets need (QT_LIBS, QT_PLUGINS
# below): PySide6 Essentials alone is 200 MB unpacked, mostly styles, tools
# and modules this app never loads.
# The licence, the third-party notices and every bundled component's licence
# text go next to the executables (LICENSE, THIRD_PARTY_NOTICES.md, licenses/).
# Build with:  uv run --group build python scripts/build.py

import re
from importlib import metadata
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

RUNTIME_DEPENDENCIES = [
    "windows-capture", "rapidocr", "onnxruntime-directml", "opencv-python-headless", "numpy", "pillow",
    "pyside6-essentials", "anthropic", "requests", "cryptography",
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
datas += [(str(path), "gametl/app/qml") for path in Path("src/gametl/app/qml").iterdir() if path.is_file()]
datas += [(str(path), "gametl/fonts") for path in Path("src/gametl/fonts").glob("*.ttf")]
datas += licence_files()
binaries = collect_dynamic_libs("onnxruntime")
hiddenimports = (
    collect_submodules("rapidocr")
    + collect_submodules("gametl")
    + ["shapely", "pyclipper", "omegaconf", "windows_capture"]
    + ["PySide6.QtQml", "PySide6.QtQuick"]
)
excludes = [
    "tkinter", "unittest", "pydoc", "matplotlib", "IPython", "notebook", "torch", "transformers",
    "ctranslate2", "sentencepiece",  # downloaded on demand, see above
    # PySide6 Essentials modules the app never imports (the add-ons are not installed at all)
    "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtXml",
    "PySide6.QtQuickWidgets", "PySide6.QtQuickTest", "PySide6.QtQuickControls2", "PySide6.QtOpenGLWidgets",
    "PySide6.QtPrintSupport", "PySide6.QtConcurrent", "PySide6.QtDBus", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtUiTools", "PySide6.QtLabsStyleKit",
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

# What of PySide6 ships, by destination path. The hooks collect far more than
# the app loads: every Qt library a QML plugin links against (the add-ons when
# installed), every Controls style, the software OpenGL fallback (20 MB, unused
# with the raster widgets and the software scene graph), tools and plugins.
# The hooks place PySide6's files under PySide6/ (Windows wheels) or PySide6/Qt/.
QML_KEEP = (
    "PySide6/qml/QtQml/",
    "PySide6/qml/QtQuick/qmldir",
    "PySide6/qml/QtQuick/plugins.qmltypes",
    "PySide6/qml/QtQuick/qtquick2plugin",
    "PySide6/qml/QtQuick/Controls/qmldir",
    "PySide6/qml/QtQuick/Controls/plugins.qmltypes",
    "PySide6/qml/QtQuick/Controls/qtquickcontrols2plugin",
    "PySide6/qml/QtQuick/Controls/Basic/",
    "PySide6/qml/QtQuick/Controls/impl/",
    "PySide6/qml/QtQuick/Templates/",
    "PySide6/qml/QtQuick/Layouts/",
    "PySide6/qml/QtQuick/Window/",
)
# Qt6<Name> libraries: what the widgets, QtQuick, Controls.Basic, Layouts and
# the QtQml modules link against (ldd over the kept plugins), plus Svg for the
# icon and image plugins.
QT_LIBS = {
    "Core", "Gui", "Widgets", "Network", "DBus", "OpenGL", "Svg",
    "Qml", "QmlModels", "QmlMeta", "QmlWorkerScript", "QmlCore", "QmlLocalStorage", "QmlNetwork",
    "QmlXmlListModel", "QmlDesignSupport",
    "Quick", "QuickTemplates2", "QuickControls2", "QuickControls2Impl", "QuickControls2Basic",
    "QuickControls2BasicStyleImpl", "QuickLayouts",
}  # fmt: skip
QT_PLUGINS = {"platforms", "styles", "imageformats", "iconengines", "platforminputcontexts", "generic", "tls",
              "networkinformation", "platformthemes", "xcbglintegrations"}  # fmt: skip
QT_PLATFORMS = {"qwindows", "qoffscreen", "qminimal", "qxcb"}  # the app, the CI check, and a Linux dev build
DROP_NAMES = ("opengl32sw", "opencv_videoio_ffmpeg")  # software OpenGL; cv2's video reader (30 MB, never used)

_QT_LIB = re.compile(r"^PySide6/(?:lib/)?(?:lib)?Qt6([A-Za-z0-9]+)\.(?:dll|so)")


def keep(entry) -> bool:
    dest = entry[0].replace("\\", "/").replace("PySide6/Qt/", "PySide6/")
    name = dest.rsplit("/", 1)[-1]
    if name.startswith(DROP_NAMES):
        return False
    if dest.startswith("PySide6/qml/"):
        return dest.startswith(QML_KEEP)
    if dest.startswith("PySide6/translations/"):
        return False  # Qt's own UI strings in 30 languages; the app's UI is English
    if dest.startswith("PySide6/plugins/"):
        parts = dest.split("/")
        if len(parts) < 4 or parts[2] not in QT_PLUGINS:
            return False
        return parts[2] != "platforms" or name.split(".")[0].removeprefix("lib") in QT_PLATFORMS
    match = _QT_LIB.match(dest)
    return match is None or match.group(1) in QT_LIBS


a.datas = [entry for entry in a.datas if keep(entry)]
a.binaries = [entry for entry in a.binaries if keep(entry)]

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
