"""Video decoder: yield sampled frames from a recording.

Reads with OpenCV VideoCapture, sampling at a fixed output fps regardless of
the recording's native fps.  Timestamp = sample_index / output_fps  (same
master clock as the prototype's frame-index approach).
"""
from __future__ import annotations
from pathlib import Path
from typing import Iterator
import cv2
import numpy as np


def decode_frames(
    path: str | Path,
    fps: float = 4.0,
) -> Iterator[tuple[int, float, np.ndarray]]:
    """Yield (sample_index, timestamp_s, bgr_image) sampled at *fps*.

    sample_index starts at 0.  timestamp_s = sample_index / fps.
    Reads the video sequentially (no seeking) for maximum compatibility with
    MKV containers.
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise IOError(f"Cannot open video: {path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    if video_fps <= 0:
        video_fps = 30.0   # safe fallback

    step = video_fps / fps   # native frames per sample
    native_idx = 0
    sample_idx = 0
    next_sample_at = 0.0     # next native frame index we want

    try:
        while True:
            ok, img = cap.read()
            if not ok:
                break
            if native_idx >= next_sample_at:
                timestamp = sample_idx / fps
                yield sample_idx, timestamp, img
                sample_idx += 1
                next_sample_at += step
            native_idx += 1
    finally:
        cap.release()


def video_duration(path: str | Path) -> float:
    """Return video duration in seconds (best-effort from metadata)."""
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return frames / fps if frames > 0 else 0.0
