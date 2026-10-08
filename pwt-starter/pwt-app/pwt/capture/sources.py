"""The frame source: a recording, resampled. Yields (t_seconds, BGR frame); t is the master clock."""
from __future__ import annotations
from pathlib import Path
import cv2, numpy as np


class FileReplaySource:
    """A recording, resampled to `fps`. t = sample index / fps. Never drops frames."""
    live = False

    def __init__(self, path, fps=12.0):
        self.path, self.fps = Path(path), float(fps)
        if not self.path.exists(): raise FileNotFoundError(self.path)

    def frames(self):
        cap = cv2.VideoCapture(str(self.path))
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        i, k = 0, 0
        try:
            while True:
                if not cap.grab(): break
                if i / src_fps + 1e-6 >= k / self.fps:          # first source frame at/after the sample time
                    ok, frame = cap.retrieve()
                    if not ok: break
                    yield k / self.fps, frame
                    k += 1
                i += 1
        finally:
            cap.release()
