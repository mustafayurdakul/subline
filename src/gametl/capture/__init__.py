"""Window-targeted screen capture.

Yields frames of one game window together with its on-screen rectangle.
The backend is Windows Graphics Capture, which captures only the target
window, so the overlay is never fed back into OCR.
"""
