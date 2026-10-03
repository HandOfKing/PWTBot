"""Round banner + counters (brief §3.2, §5.3, §5.4): Remaining, helmets, banner score.

Remaining (players alive in the lobby) drops at the TRUE elimination time; helmets (white alive / gray dead,
knocked stays white) say which team lost a player; the banner score says who won the round.
"""
import numpy as np
from .digits import DigitReader


class CounterReader:
    def __init__(self, profile):
        self.p = profile
        b = profile["banner"]
        self.blue_pts, self.red_pts = b["blue_pts"], b["red_pts"]
        self.blue_diff, self.red_diff = b["blue_min_diff"], b["red_min_diff"]
        self.alive, self.dead = b["helmet_alive_above"], b["helmet_dead_above"]
        self.remaining = DigitReader(profile.templates / "digits_remaining")
        self.banner_digits = DigitReader(profile.templates / "digits_banner")
        self._last_rem_crop, self._last_rem = None, None

    def banner_visible(self, im):
        """Score boxes are solid blue / red only while a round is live."""
        b = all(int(im[y, x][0]) - int(im[y, x][2]) > self.blue_diff for x, y in self.blue_pts)
        r = all(int(im[y, x][2]) - int(im[y, x][0]) > self.red_diff for x, y in self.red_pts)
        return b and r

    def read_remaining(self, im):
        """Remaining digits, re-read only when the box's pixels changed. None = unreadable/hidden."""
        x0, y0, x1, y1 = self.p["remaining_box"]
        crop = im[y0:y1, x0:x1]
        if self._last_rem_crop is not None and np.abs(crop.astype(np.int16) - self._last_rem_crop).mean() < 3:
            return self._last_rem
        v, _ = self.remaining.read(crop)
        self._last_rem_crop, self._last_rem = crop.astype(np.int16), v
        return v

    def helmet_state(self, im, x, y):
        v = np.percentile(im[y - 11:y + 11, x - 13:x + 13].astype(int).min(2), 90)
        return "alive" if v > self.alive else ("dead" if v > self.dead else None)

    def helmets(self, im, team_size):
        pos = self.p.helmets(team_size)
        return {team: [self.helmet_state(im, x, y) for x, y in pts] for team, pts in pos.items()}

    def scores(self, im):
        out = {}
        for team, key in (("blue", "blue_score_box"), ("red", "red_score_box")):
            x0, y0, x1, y1 = self.p["banner"][key]
            out[team] = self.banner_digits.read(im[y0:y1, x0:x1])[0]
        return out
