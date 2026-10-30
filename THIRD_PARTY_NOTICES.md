# Third-party notices

Subline (package and executables: gametl) is proprietary software (see
LICENSE). It bundles the open-source components below, each of which stays
under its own licence. The full licence texts ship in the `licenses` folder
of the packaged build, one subfolder per component (the Qt LGPL and GPL
texts under `licenses/qt`). In the source tree, `licenses/` holds only the
texts the wheels do not carry, including those of the offline runtime
downloaded on demand; the build collects the rest from the installed
packages.

## Bundled

| Component | Used for | Licence |
| --- | --- | --- |
| [Python](https://www.python.org/) 3.12 | runtime | PSF License |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | text detection and recognition | Apache-2.0 |
| [ONNX Runtime](https://onnxruntime.ai/) (onnxruntime-directml) | running the OCR models | MIT |
| Microsoft DirectML (`DirectML.dll`, shipped inside onnxruntime-directml) | GPU OCR | Microsoft's DirectML licence, as redistributed with that package |
| [OpenCV](https://opencv.org/) (opencv-python-headless) | image handling | Apache-2.0 (the libraries it carries: see its `LICENSE-3RD-PARTY.txt`) |
| [NumPy](https://numpy.org/) | arrays | BSD-3-Clause (with parts under 0BSD, MIT, Zlib, CC0-1.0) |
| [Pillow](https://python-pillow.org/) | images, screenshots | MIT-CMU (HPND) |
| [Qt for Python](https://doc.qt.io/qtforpython-6/) (PySide6 Essentials, shiboken6) and Qt 6 | overlay window, settings window, tray | LGPL-3.0 (see below) |
| [windows-capture](https://github.com/NiiightmareXD/windows-capture) | Windows Graphics Capture | MIT |
| [anthropic](https://github.com/anthropics/anthropic-sdk-python) SDK | Claude translation | MIT |
| [requests](https://requests.readthedocs.io/) | DeepL translation, downloads | Apache-2.0 |
| [cryptography](https://cryptography.io/) (with OpenSSL) | licence-key signatures | Apache-2.0 or BSD-3-Clause; OpenSSL under Apache-2.0 |
| [PyInstaller](https://pyinstaller.org/) | building the packaged folder (bootloader included in the build) | GPL-2.0 with the bootloader exception, which permits proprietary builds |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | the installer (`Subline-v<version>-setup.exe`; its setup stub is part of the file) | Inno Setup licence, which permits distributing the installers it makes |

The components above bring these with them:

| Component | Brought in by | Licence |
| --- | --- | --- |
| annotated-types | pydantic | MIT |
| anyio | anthropic | MIT |
| certifi | requests | MPL-2.0 |
| cffi | cryptography | MIT-0 |
| charset-normalizer | requests | MIT |
| colorama | tqdm, colorlog | BSD-3-Clause |
| [colorlog](https://github.com/borntyping/python-colorlog) | RapidOCR | MIT |
| docstring-parser | anthropic | MIT |
| flatbuffers | ONNX Runtime | Apache-2.0 |
| h11 | httpcore2 | MIT |
| httpcore2 | httpx2 | BSD-3-Clause |
| httpx2 | anthropic | BSD-3-Clause |
| idna | requests, httpx2, anyio | BSD-3-Clause |
| jiter | anthropic | MIT |
| mpmath | SymPy | BSD-3-Clause |
| [OmegaConf](https://github.com/omry/omegaconf), with the ANTLR 4 runtime it carries | RapidOCR | BSD-3-Clause; ANTLR: BSD-3-Clause |
| opentelemetry-api | anthropic | Apache-2.0 |
| packaging | ONNX Runtime | Apache-2.0 or BSD-2-Clause |
| protobuf | ONNX Runtime | BSD-3-Clause |
| [pyclipper](https://github.com/fonttools/pyclipper) | RapidOCR | MIT (the Clipper library: Boost Software License 1.0) |
| pycparser | cffi | BSD-3-Clause |
| pydantic, pydantic-core | anthropic | MIT |
| [PyYAML](https://pyyaml.org/) | RapidOCR, OmegaConf | MIT |
| [Shapely](https://shapely.readthedocs.io/), with the GEOS library it carries | RapidOCR | BSD-3-Clause; GEOS: LGPL-2.1 (see below) |
| six | RapidOCR | MIT |
| sniffio | anthropic | MIT or Apache-2.0 |
| SymPy | ONNX Runtime | BSD-3-Clause |
| [tqdm](https://tqdm.github.io/) | RapidOCR | MPL-2.0 and MIT |
| truststore | httpx2, httpcore2 | MIT |
| typing-extensions | anthropic, pydantic, anyio and others | PSF-2.0 |
| typing-inspection | pydantic | MIT |
| urllib3 | requests | MIT |

## Qt, GEOS and the LGPL

PySide6 and Qt are used under the GNU Lesser General Public License,
version 3. The Qt libraries ship as separate DLL files in the packaged
build, so you can replace them with your own build of the same Qt version
by copying it over the files in `_internal/PySide6`. The LGPL text is in
`licenses/qt`. Qt source code is available from [qt.io](https://www.qt.io/).

Shapely carries the GEOS geometry library, used under the GNU Lesser
General Public License, version 2.1, as separate DLL files (`geos-*.dll`,
`geos_c-*.dll`) that can be replaced the same way. Its licence text is in
`licenses/shapely`; the source code is available from
[libgeos.org](https://libgeos.org).

## Downloaded at run time (not bundled)

- The offline translator's runtime, fetched from PyPI into
  `%APPDATA%\gametl\runtime` when the user first presses Download on the
  Translation page: the CTranslate2 wheel (MIT; it also carries Intel's
  OpenMP runtime, `libiomp5md.dll`, under the Intel Simplified Software
  License, and NVIDIA's `cudnn64_9.dll`, under the NVIDIA cuDNN licence)
  and the SentencePiece wheel (Apache-2.0). Neither wheel carries its
  licence text; both texts ship in the packaged build under
  `licenses/ctranslate2` and `licenses/sentencepiece`.
- PP-OCR detection and recognition models
  ([PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)), including the
  PP-OCRv5 recognisers for Korean, Cyrillic and Arabic: Apache-2.0.
- OPUS-MT translation models by Helsinki-NLP (converted with
  `scripts/convert_offline_model.py`): CC-BY-4.0; the model id is
  recorded in `gametl.json` next to the converted model.
- Argos Translate packages (Download on the Translation page, or
  `gametl-cli --download-model`): the licence stated
  in each package's metadata.

## Services

Translation through DeepL or Anthropic uses the licensee's own account and
is subject to those services' terms.

## Demo footage

The README clip is the author's own gameplay recording of Alan Wake 2
(Remedy Entertainment), shown to demonstrate the software; the game and
its subtitles are the property of their owners.
