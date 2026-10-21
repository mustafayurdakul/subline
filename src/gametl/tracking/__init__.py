"""From OCR lines to tracked text blocks.

`blocks` groups lines into blocks (a subtitle, a dialogue box, a label) and
follows them from frame to frame with stable ids, a stability count and a
few frames of grace when OCR misses one. `filters` drops lines the user
never wants translated.
"""
