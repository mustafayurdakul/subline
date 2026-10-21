"""Text detection and recognition.

One backend: RapidOCR running PP-OCR models on ONNX Runtime. Output is a
list of text lines, each with its pixel box and a confidence score.
"""
