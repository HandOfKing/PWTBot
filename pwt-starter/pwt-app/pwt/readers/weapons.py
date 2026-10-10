"""Which weapon knocked someone down: the gun icon of a knock row, matched against a template per gun.

A knock row reads  killer name · gun icon · knock icon · victim name. The gun is somewhere in the
`win_px` columns left of the knock icon, so every template in templates/weapons/<name>.png is slid over
that window (binary top-hat mask, TM_CCOEFF_NORMED). A weapon is named only when

  - the best score is >= `thresh` (M4: a wrong gun is worse than "unknown"), and
  - no other gun scores within `margin` of it (two silhouettes that look alike at ~16 px are not told
    apart by guessing: AKM / S12K / Beryl M762 are the close ones).

Anything else is None. The library was learned from Chirag's labels of 36 icon groups seen in four
matches (docs/weapons.md); a gun that is not in it reads None. A row caught while it slides in shows a
partial icon, so the tracker votes over all sightings of a row (feed.Line.weapons).

Cutting the icon out by its ink gap first was tried and is NOT used: thin barrels break into pieces more
than 5 columns apart, which left 109 of 703 knock rows without an icon. Window search names 697 of the
703 (683 with the first 22 guns).
"""
import glob, os
import cv2, numpy as np

# Category of each gun, for the planned match highlights (nothing reads this yet). M249 is a light machine gun.
CATEGORY = {
    "M416": "AR", "AKM": "AR", "Beryl M762": "AR", "AUG A3": "AR", "Groza": "AR", "SCAR-L": "AR", "FAMAS": "AR",
    "G36C": "AR", "ACE32": "AR",
    "PP19 Bison": "SMG", "UMP45": "SMG", "Micro Uzi": "SMG", "Tommy Gun": "SMG", "P90": "SMG", "JS9": "SMG",
    "Vector": "SMG", "MP5K": "SMG", "DBS": "Shotgun", "S12K": "Shotgun", "S1897": "Shotgun",
    "M249": "LMG", "MG3": "LMG", "AWM": "Sniper",
    "Grenade": "Grenade", "Molotov": "Molotov", "Pan": "Melee", "Car": "Vehicle", "Zone": "Zone",
}


class WeaponReader:
    def __init__(self, folder, thresh=0.80, margin=0.05, win_px=150):
        self.thresh, self.margin, self.win = thresh, margin, win_px
        self.templates = {}
        for p in sorted(glob.glob(os.path.join(str(folder), "*.png"))):
            t = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
            if t is not None:
                self.templates[os.path.basename(p)[:-4]] = (t > 127).astype(np.float32)

    def scores(self, mask, knock_x0):
        """{gun: best template score} over the window left of the knock icon at column knock_x0."""
        if not self.templates:
            return {}
        win = cv2.copyMakeBorder(mask[:, max(0, knock_x0 - self.win):knock_x0 + 4].astype(np.float32),
                                 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=0)
        out = {}
        for name, t in self.templates.items():
            if t.shape[0] > win.shape[0] or t.shape[1] > win.shape[1]:
                out[name] = -1.0
            else:
                out[name] = float(cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED).max())
        return out

    def read(self, mask, knock_x0):
        """The gun's name, or None (unknown gun, partly drawn icon, or two guns that look alike)."""
        s = self.scores(mask, knock_x0)
        if not s:
            return None
        ranked = sorted(s.items(), key=lambda kv: -kv[1])
        best, sc = ranked[0]
        if sc < self.thresh:
            return None
        if len(ranked) > 1 and sc - ranked[1][1] < self.margin:
            return None
        return best
