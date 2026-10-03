"""PWT HUD counters — prototype v0.1

Per sampled frame, reads:
  - Remaining (players alive in the lobby, top-left)  -> exact elimination times
  - banner helmets (white = alive, gray = dead)       -> which team lost a player
  - banner round score (blue / red)                   -> round winner + round-end time
Then aligns kill-feed eliminations to those true times.

Usage: python3 counters.py <frame_dir> <fps> <feed_events.csv> <out_prefix>
"""
import cv2, glob, os, sys, csv, subprocess, numpy as np

# ---- layout for THIS recording (GameLoop windowed, 2v2). Recalibrate per layout / team size.
REMAINING_BOX = (184, 60, 210, 88)                 # x0, y0, x1, y1 of the digits
HELMETS = {"blue": [(666, 76), (710, 76)], "red": [(1218, 76), (1262, 76)]}
SCORE_BOX = {"blue": (772, 66, 808, 116), "red": (1118, 66, 1156, 116)}
TEAM_OF = {"TheWolverine": "blue", "PARAbloodthirs": "blue",
           "RGODxEMPEROR": "red", "Makjets69": "red"}     # from the round scoreboard
WHITE, GRAY = 190, 80                               # helmet brightness bands (p90 of min-channel)


def ocr_digits(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    b = cv2.copyMakeBorder(b, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    out = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "7", "-c",
                          "tessedit_char_whitelist=0123456789"],
                         input=cv2.imencode(".png", b)[1].tobytes(), capture_output=True)
    s = out.stdout.decode().strip()
    return int(s) if s.isdigit() else None


def helmet_state(im, x, y):
    v = np.percentile(im[y - 11:y + 11, x - 13:x + 13].astype(int).min(2), 90)
    return "alive" if v > WHITE else ("dead" if v > GRAY else None)


BLUE_PTS, RED_PTS = [(770, 75), (805, 110), (760, 100)], [(1120, 75), (1150, 110), (1160, 100)]


def banner_visible(im):
    """Score boxes must be solidly blue / red (banner hidden pre-round and after the round ends)."""
    b = all(int(im[y, x][0]) - int(im[y, x][2]) > 80 for x, y in BLUE_PTS)
    r = all(int(im[y, x][2]) - int(im[y, x][0]) > 70 for x, y in RED_PTS)
    return b and r


def read_frame(path):
    im = cv2.imread(path)
    x0, y0, x1, y1 = REMAINING_BOX
    rem = ocr_digits(im[y0:y1, x0:x1])
    if not banner_visible(im): return rem, None
    helm = {team: [helmet_state(im, x, y) for x, y in pts] for team, pts in HELMETS.items()}
    return rem, helm


def stable(series, k=2):
    """Accept a new value once it is read k times in a row (unreadable frames skipped);
    its time is the FIRST frame it was read. A one-frame value in between (4 -> 3 -> 2) is
    absorbed: the drop is stamped at the first frame that left the old value."""
    out, cur, cand, n, cand_t, left_t = [], None, None, 0, None, None
    for t, v in series:
        if v is None: continue
        if cur is not None and v != cur and left_t is None: left_t = t
        if v == cand: n += 1
        else: cand, n, cand_t = v, 1, t
        if n >= k and v != cur:
            out.append((round(left_t if left_t is not None else cand_t, 3), cur, v))
            cur, left_t = v, None
        elif v == cur:
            left_t = None
    return out


def run(frame_dir, fps, feed_csv, prefix):
    files = sorted(glob.glob(os.path.join(frame_dir, "f*.jpg")))
    rem_series, helm_series = [], []
    for i, f in enumerate(files):
        t = round(i / fps, 3)
        rem, helm = read_frame(f)
        rem_series.append((t, rem))
        if helm: helm_series.append((t, helm))

    # 1) eliminations from Remaining drops (one row per player lost)
    drops = []
    for t, before, after in stable(rem_series):
        if before is not None and after < before:
            drops += [dict(t=t, team=None) for _ in range(before - after)]

    # 2) helmet deaths per team (alive -> dead transitions)
    # a slot counts as dead once it reads "dead" in 2 consecutive banner frames
    deaths, state, pend, last_t = [], {}, {}, None
    def flush():                       # banner vanished right after a gray read = round-ending death
        for (team, k), pt in list(pend.items()):
            deaths.append(dict(t=pt, team=team, slot=k + 1)); state[(team, k)] = "dead"
        pend.clear()
    for t, h in helm_series:
        if last_t is not None and t - last_t > 1.5 / fps: flush()
        last_t = t
        for team, slots in h.items():
            for k, s in enumerate(slots):
                key = (team, k)
                if s == "alive": state[key] = "alive"; pend.pop(key, None); continue
                if s == "dead" and state.get(key) == "alive":
                    if key in pend:
                        deaths.append(dict(t=pend.pop(key), team=team, slot=k + 1)); state[key] = "dead"
                    else: pend[key] = t
    flush()

    # 3) give each Remaining drop a team: the next unused helmet death within 1.0 s
    used = set()
    for d in drops:
        for j, hd in enumerate(deaths):
            if j not in used and 0 <= hd["t"] - d["t"] <= 1.0:
                d["team"] = hd["team"]; used.add(j); break

    # 4) align feed eliminations (in feed order) to the earliest unassigned drop of the victim's team
    feed = list(csv.DictReader(open(feed_csv)))
    taken = set()
    aligned = []
    for e in feed:
        row = dict(e)
        row["victim_team"] = TEAM_OF.get(e["victim"], "")
        row["true_time_s"], row["time_source"] = e["feed_first_seen_s"], "feed (approx)"
        if e["type"] in ("kill", "eliminated_knocked"):
            ft = float(e["feed_first_seen_s"])
            for j, d in enumerate(drops):
                if j in taken or d["t"] > ft: continue
                if d["team"] and row["victim_team"] and d["team"] != row["victim_team"]: continue
                row["true_time_s"] = d["t"]; row["time_source"] = "Remaining drop" + (" + helmet" if d["team"] else "")
                taken.add(j); break
        row["feed_delay_s"] = round(float(e["feed_first_seen_s"]) - float(row["true_time_s"]), 2)
        aligned.append(row)

    with open(prefix + "_aligned_events.csv", "w", newline="") as fh:
        cols = ["true_time_s", "time_source", "feed_first_seen_s", "feed_delay_s", "killer", "type",
                "weapon", "victim", "victim_team", "name_conf", "flag"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); w.writeheader()
        for r in aligned: w.writerow(r)
    return rem_series, drops, deaths, aligned


if __name__ == "__main__":
    rem, drops, deaths, aligned = run(sys.argv[1], float(sys.argv[2]), sys.argv[3], sys.argv[4])
    print("Remaining changes:", stable(rem))
    print("Eliminations (Remaining drops):", [(d["t"], d["team"]) for d in drops])
    print("Helmet deaths:", [(d["t"], d["team"], "slot", d["slot"]) for d in deaths])
    for r in aligned:
        print(f"  true {float(r['true_time_s']):6.2f}s [{r['time_source']}]  feed {float(r['feed_first_seen_s']):6.2f}s "
              f"(+{r['feed_delay_s']}s)  {r['killer']} --{r['type']}/{r['weapon'] or '-'}--> {r['victim']} ({r['victim_team']})")
