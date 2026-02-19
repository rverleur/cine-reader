"""cine_reader package."""

from .cine import Cine
from .headers import BitmapHeader, CineHeader, ImageOffsets, Setup
from .image_ops import (
    demosaic_bilinear,
    replace_dead_pixels,
    replace_dead_pixels_bayer,
    replace_dead_pixels_mono,
    replace_dead_pixels_rgb,
)
from .stats import average_from_frame_iter, robust_background_mad_stack, robust_background_topk
from .unpack import unpack_10bit_data, unpack_10bit_numpy

__all__ = [
    "Cine",
    "CineHeader",
    "BitmapHeader",
    "ImageOffsets",
    "Setup",
    "unpack_10bit_data",
    "unpack_10bit_numpy",
    "replace_dead_pixels",
    "replace_dead_pixels_mono",
    "replace_dead_pixels_bayer",
    "replace_dead_pixels_rgb",
    "demosaic_bilinear",
    "average_from_frame_iter",
    "robust_background_mad_stack",
    "robust_background_topk",
]
