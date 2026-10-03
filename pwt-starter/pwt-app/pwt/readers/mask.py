"""White-text mask that survives the round-end dim (brief §5.1)."""
import cv2, numpy as np

_KERNEL = cv2.getStructuringElement(cv2.MORPH_RECT, (23, 23))


def white_mask(crop):
    """Near-neutral pixels much brighter than their local background (white top-hat), relative threshold.
    Normal frames: text ~245 on ~60. Dimmed frames: text ~49 on ~7-20. Returns uint8 0/1."""
    c = crop.astype(np.int16)
    mn = c.min(2).astype(np.uint8)
    mx = c.max(2)
    th = cv2.morphologyEx(mn, cv2.MORPH_TOPHAT, _KERNEL).astype(np.int16)
    t = max(18, 0.45 * np.percentile(th, 99.8))
    return ((th > t) & (mx - mn.astype(np.int16) < 45)).astype(np.uint8)
