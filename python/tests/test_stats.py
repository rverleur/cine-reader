from __future__ import annotations

import numpy as np

from cine_reader.stats import average_from_frame_iter, robust_background_mad_stack, robust_background_topk


def test_average_from_frame_iter_matches_expected() -> None:
    frames = [
        np.array([[1, 2], [3, 4]], dtype=np.uint16),
        np.array([[3, 4], [5, 6]], dtype=np.uint16),
    ]
    avg, count = average_from_frame_iter(iter(frames), out_dtype=np.uint16, chunk_size=2)
    assert count == 2
    assert np.array_equal(avg, np.array([[2, 3], [4, 5]], dtype=np.uint16))


def test_robust_background_methods_reject_dark_outlier() -> None:
    frames = [
        np.full((3, 3), 100, dtype=np.uint16),
        np.full((3, 3), 100, dtype=np.uint16),
        np.full((3, 3), 20, dtype=np.uint16),
    ]

    mad = robust_background_mad_stack(iter(frames), q_bg=0.8, k_sigma=2.5, min_keep=2, out_dtype=np.uint16)
    topk = robust_background_topk(iter(frames), frame_count=len(frames), q_bg=0.8, min_keep=1, max_keep=2, out_dtype=np.uint16)

    assert np.all(mad >= 95)
    assert np.all(topk >= 95)


def test_robust_background_methods_support_color_frames() -> None:
    frames = [
        np.full((2, 2, 3), 100, dtype=np.uint16),
        np.full((2, 2, 3), 100, dtype=np.uint16),
        np.full((2, 2, 3), 20, dtype=np.uint16),
    ]

    mad = robust_background_mad_stack(iter(frames), q_bg=0.8, k_sigma=2.5, min_keep=2, out_dtype=np.uint16)
    topk = robust_background_topk(iter(frames), frame_count=len(frames), q_bg=0.8, min_keep=1, max_keep=2, out_dtype=np.uint16)

    assert mad.shape == frames[0].shape
    assert topk.shape == frames[0].shape
    assert np.all(mad >= 95)
    assert np.all(topk >= 95)
