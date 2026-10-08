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
        self.blue_diff, self.red_diff = b["blue_min_diff"], b["red_min_diff"]
        self.box_min_frac = b.get("box_min_frac", 0.25)
        self.alive, self.dead = b["helmet_alive_above"], b["helmet_dead_above"]
        self.remaining = DigitReader(profile.templates / "digits_remaining")
        self.banner_digits = DigitReader(profile.templates / "digits_banner")
        self._last_rem_crop, self._last_rem = None, None

    def _box_frac(self, im, key, blue):
        x0, y0, x1, y1 = self.p["banner"][key]
        c = im[y0:y1, x0:x1].astype(np.int16)
        d = c[..., 0] - c[..., 2] if blue else c[..., 2] - c[..., 0]
        return float((d > (self.blue_diff if blue else self.red_diff)).mean())

    def banner_visible(self, im):
        """Score boxes are solid blue / red only while a round is live.

        Measured as the SHARE of each score box that is team-coloured, not as a
        few sample pixels. The sample pixels sat where a second digit is drawn:
        once blue reached 10 the "0" covered one of them and every later round
        went undetected (2026-10-04 22-55-47: 22 rounds found of 25; rounds 16-25
        merged). Shares on Video_Project_9 / _13: 0.61-0.83 with one digit,
        0.38-0.40 with "10", 0.00 whenever the banner is hidden (round end,
        boards, loading). Both boxes must pass, so blue sky in one is not enough.
        """
        return (self._box_frac(im, "blue_score_box", True) >= self.box_min_frac
                and self._box_frac(im, "red_score_box", False) >= self.box_min_frac)

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
        """Per-slot helmet state, or {} when this profile has no measured
        positions for this team size.

        Helmets give an elimination its TEAM. Without them the kill feed still
        reads and events still land -- they just fall back to feed time and get
        flagged. Guessing coordinates would silently mis-assign teams, and
        refusing to run at all would make the feed useless, so neither.
        """
        try:
            pos = self.p.helmets(team_size)
        except KeyError as e:
            if not getattr(self, "_helmet_warned", False):
                self._helmet_warned = True
                print(f"   NOTE: {e.args[0]}\n"
                      f"         Continuing without helmets: eliminations keep feed time "
                      f"and are flagged NO_HELMETS.")
            return {}
        return {team: [self.helmet_state(im, x, y) for x, y in pts] for team, pts in pos.items()}

    def scores(self, im):
        out = {}
        for team, key in (("blue", "blue_score_box"), ("red", "red_score_box")):
            x0, y0, x1, y1 = self.p["banner"][key]
            out[team] = self.banner_digits.read(im[y0:y1, x0:x1])[0]
        return out
