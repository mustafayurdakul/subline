"""Window-targeted screen capture.

Yields frames of one game window plus its on-screen rectangle. Backend: Windows
Graphics Capture (WGC), which captures only the target window, so the overlay is
never fed back into OCR.
"""
