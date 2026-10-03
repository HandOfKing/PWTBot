"""Frame sources: live screen capture and file replay. Both yield (t_seconds, BGR frame) and feed the
identical engine (CLAUDE.md). t is the master clock: seconds since the source started."""
from __future__ import annotations
import time
from pathlib import Path
import cv2, numpy as np


class FileReplaySource:
    """A recording, resampled to `fps`. t = sample index / fps. Never drops frames."""
    live = False

    def __init__(self, path, fps=12.0, realtime=False):
        self.path, self.fps, self.realtime = Path(path), float(fps), realtime
        if not self.path.exists(): raise FileNotFoundError(self.path)

    def frames(self):
        cap = cv2.VideoCapture(str(self.path))
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        i, k, t0 = 0, 0, time.perf_counter()
        try:
            while True:
                if not cap.grab(): break
                if i / src_fps + 1e-6 >= k / self.fps:          # first source frame at/after the sample time
                    ok, frame = cap.retrieve()
                    if not ok: break
                    t = k / self.fps
                    if self.realtime:
                        delay = t - (time.perf_counter() - t0)
                        if delay > 0: time.sleep(delay)
                    yield t, frame
                    k += 1
                i += 1
        finally:
            cap.release()


class LiveScreenSource:
    """GameLoop on screen via DXcam (Desktop Duplication API), falling back to mss. Windows only.
    Run as administrator if GameLoop is elevated. Black first frames usually mean a privilege mismatch or the
    hybrid-GPU issue (put Python on the same GPU as GameLoop: Settings > System > Display > Graphics)."""
    live = True

    def __init__(self, region=None, fps=12.0, log=print):
        self.region, self.fps, self.log = (tuple(region) if region else None), float(fps), log
        self._stop = False

    def stop(self):
        self._stop = True

    def frames(self):
        grab, close = self._open()
        t0, n, black = time.perf_counter(), 0, 0
        try:
            while not self._stop:
                target = t0 + n / self.fps
                d = target - time.perf_counter()
                if d > 0: time.sleep(d)
                frame = grab()
                if frame is None: continue
                n += 1
                if n <= 12 and float(frame.mean()) < 3:
                    black += 1
                    if black == 6:
                        self.log("WARNING: capture is black - run PWT as administrator, or set Python to the same GPU "
                                 "as GameLoop (Settings > System > Display > Graphics)")
                yield time.perf_counter() - t0, frame
        finally:
            close()

    def _open(self):
        try:
            import dxcam
            cam = dxcam.create(output_color="BGR")
            cam.start(target_fps=int(self.fps), video_mode=True, region=self.region)
            return cam.get_latest_frame, cam.stop
        except Exception as e:                                 # noqa: BLE001
            self.log(f"dxcam unavailable ({e}); using mss")
            import mss
            sct = mss.mss()
            box = sct.monitors[1] if not self.region else dict(
                left=self.region[0], top=self.region[1],
                width=self.region[2] - self.region[0], height=self.region[3] - self.region[1])
            return (lambda: cv2.cvtColor(np.asarray(sct.grab(box)), cv2.COLOR_BGRA2BGR)), sct.close
