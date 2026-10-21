"""Text detection and recognition.

Backends: RapidOCR (PP-OCR models on ONNX Runtime, default) and Windows.Media.Ocr
(zero-install fallback). Output is a list of text lines with pixel boxes.
"""
