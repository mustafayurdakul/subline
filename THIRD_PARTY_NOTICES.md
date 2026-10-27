# Third-party notices

gametl is proprietary software (see LICENSE). It bundles the open-source
components below, each of which stays under its own licence. The full
licence texts ship in the `licenses` folder of the packaged build, one
subfolder per component (the Qt LGPL and GPL texts under `licenses/qt`).
In the source tree, `licenses/` holds only the texts the wheels do not
carry; the build collects the rest from the installed packages.

| Component | Used for | Licence |
| --- | --- | --- |
| [Python](https://www.python.org/) 3.12 | runtime | PSF License |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | text detection and recognition | Apache-2.0 |
| PP-OCR models ([PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)) | downloaded on first run | Apache-2.0 |
| [ONNX Runtime](https://onnxruntime.ai/) (onnxruntime-directml) | running the OCR models | MIT |
| Microsoft DirectML (`DirectML.dll`, shipped inside onnxruntime-directml) | GPU OCR | Microsoft's DirectML licence, as redistributed with that package |
| [OpenCV](https://opencv.org/) (opencv-python-headless) | image handling | Apache-2.0 |
| [NumPy](https://numpy.org/) | arrays | BSD-3-Clause (with parts under 0BSD, MIT, Zlib, CC0) |
| [Pillow](https://python-pillow.org/) | images, screenshots | MIT-CMU (HPND) |
| [Qt for Python](https://doc.qt.io/qtforpython-6/) (PySide6, shiboken6) and Qt 6 | overlay window, settings window, tray | LGPL-3.0 (see below) |
| [Source Sans 3](https://github.com/adobe-fonts/source-sans) (Adobe), [Fira Sans](https://github.com/mozilla/Fira) (Mozilla, Telefonica), [Barlow Semi Condensed](https://github.com/jpt/barlow) (Jeremy Tribby) | subtitle fonts shipped with the app (`_internal/gametl/fonts`) | SIL Open Font License 1.1 (texts in `licenses/source-sans-3`, `licenses/fira-sans`, `licenses/barlow-semi-condensed`) |
| [windows-capture](https://github.com/NiiightmareXD/windows-capture) | Windows Graphics Capture | MIT |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | offline translation; not bundled, downloaded on demand (see below) | MIT |
| [SentencePiece](https://github.com/google/sentencepiece) | tokenisation for offline models; downloaded with CTranslate2 | Apache-2.0 |
| [anthropic](https://github.com/anthropics/anthropic-sdk-python) SDK, with pydantic, httpx, anyio, jiter, distro, sniffio, typing-extensions | Claude translation | MIT, BSD-3-Clause, Apache-2.0, PSF |
| [requests](https://requests.readthedocs.io/), with urllib3, certifi, charset-normalizer, idna | DeepL translation, downloads | Apache-2.0, MIT, MPL-2.0, BSD-3-Clause |
| [cryptography](https://cryptography.io/) (with OpenSSL) | licence-key signatures | Apache-2.0 or BSD-3-Clause; OpenSSL under Apache-2.0 |
| [OmegaConf](https://github.com/omry/omegaconf), [Shapely](https://shapely.readthedocs.io/), [pyclipper](https://github.com/fonttools/pyclipper), [PyYAML](https://pyyaml.org/), [tqdm](https://tqdm.github.io/), [colorlog](https://github.com/borntyping/python-colorlog), six | RapidOCR's dependencies | BSD-3-Clause, BSD-3-Clause, MIT (Clipper: Boost), MIT, MPL-2.0 and MIT, MIT, MIT |
| [PyInstaller](https://pyinstaller.org/) | building the packaged folder (bootloader included in the build) | GPL-2.0 with the bootloader exception, which permits proprietary builds |

## Qt and the LGPL

PySide6 and Qt are used under the GNU Lesser General Public License,
version 3. The Qt libraries ship as separate DLL files in the packaged
build, so you can replace them with your own build of the same Qt version
by copying it over the files in `_internal/PySide6`. The LGPL text is in
`licenses/qt`. Qt source code is available from [qt.io](https://www.qt.io/).

## Downloaded at run time (not bundled)

- The offline translator's runtime, fetched from PyPI into
  `%APPDATA%\gametl\runtime` when the user first presses Download on the
  Translation page: the CTranslate2 wheel (MIT; it carries Intel's OpenMP
  runtime, `libiomp5md.dll`, under the Intel Simplified Software License)
  and the SentencePiece wheel (Apache-2.0). Each wheel's licence texts
  unpack with it.
- PP-OCR detection and recognition models: Apache-2.0.
- OPUS-MT translation models by Helsinki-NLP (converted with
  `scripts/convert_offline_model.py`): CC-BY-4.0; the model id is
  recorded in `gametl.json` next to the converted model.
- Argos Translate packages (`gametl --download-model`): the licence stated
  in each package's metadata.

## Services

Translation through DeepL or Anthropic uses the licensee's own account and
is subject to those services' terms.

## Demo footage

The README clip is the author's own gameplay recording of Alan Wake 2
(Remedy Entertainment), shown to demonstrate the software; the game and
its subtitles are the property of their owners.
