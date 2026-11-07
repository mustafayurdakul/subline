"""Type aliases shared across the package."""

Box = tuple[int, int, int, int]
"""A pixel rectangle as (x0, y0, x1, y1); x1 and y1 exclusive."""

BGR = tuple[int, int, int]
"""A colour in OpenCV's channel order."""

RGB = tuple[int, int, int]
