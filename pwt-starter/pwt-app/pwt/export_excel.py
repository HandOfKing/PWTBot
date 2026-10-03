"""Excel export: one match, or every match in a date range."""
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="1F3A5F")
FLAG_FILL = PatternFill("solid", fgColor="FFF2CC")
TITLE = Font(bold=True, size=14)


def _mmss(s):
    if s is None: return None
    s = float(s); return f"{int(s // 60):02d}:{s % 60:05.2f}"


def _table(ws, headers, rows, start_row=1, flag_col=None, widths=None):
    for j, h in enumerate(headers, 1):
        c = ws.cell(row=start_row, column=j, value=h)
        c.font, c.fill, c.alignment = HEAD, HEAD_FILL, Alignment(horizontal="center", vertical="center")
    for i, r in enumerate(rows, start_row + 1):
        for j, v in enumerate(r, 1):
            ws.cell(row=i, column=j, value=v)
        if flag_col is not None and r[flag_col]:
            for j in range(1, len(headers) + 1):
                ws.cell(row=i, column=j).fill = FLAG_FILL
    last = start_row + max(len(rows), 1)
    ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(headers))}{last}"
    ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
    for j, h in enumerate(headers, 1):
        w = (widths or {}).get(h) or max([len(str(h))] + [len(str(r[j - 1])) for r in rows if r[j - 1] is not None]) + 2
        ws.column_dimensions[get_column_letter(j)].width = min(max(w, 8), 40)


EVENT_HEADERS = ["Date & time", "Round", "True time (s)", "True time", "Feed time (s)", "Feed delay (s)",
                 "Time source", "Type", "Killer", "Weapon", "Victim", "Victim team", "Confidence", "Flag", "Reviewed"]


def _event_rows(events):
    return [[e["recorded_at"], e["round_no"], e["true_time_s"], _mmss(e["true_time_s"]), e["feed_time_s"],
             e["feed_delay_s"], e["time_source"], e["event_type"], e["killer"], e["weapon"], e["victim"],
             e["victim_team"], e["confidence"], e["flag"], "yes" if e["reviewed"] else ""] for e in events]


PLAYER_HEADERS = ["Player", "Nickname", "Team", "Eliminations", "Knocks", "Deaths", "Times knocked",
                  "Damage dealt", "Scoreboard elims", "Check"]


def _player_rows(players):
    rows = []
    for p in players:
        sb = p["scoreboard_eliminations"]
        check = "" if sb is None else ("OK" if int(sb) == p["eliminations"] else f"feed {p['eliminations']} vs board {int(sb)}")
        rows.append([p["ign"], p["nickname"], p["team"], p["eliminations"], p["knocks"], p["deaths"],
                     p["times_knocked"], p["damage_dealt"], sb, check])
    return rows


def export_match(conn, match_id, path):
    from .db import match_detail
    d = match_detail(conn, match_id)
    m = d["match"]
    wb = Workbook()
    ws = wb.active; ws.title = "Summary"
    ws["A1"] = f"Match {m['recorded_at']}"; ws["A1"].font = TITLE
    info = [("Recorded", m["recorded_at"]), ("Room code", m["room_code"]), ("Mode", m["mode"]),
            ("Team size", m["team_size"]), ("Rounds", m["rounds_played"]), ("Winner", m["winner_team"]),
            ("Status", m["status"]), ("Source file", m["source_file"]), ("Processed", m["processed_at"]),
            ("Pipeline", m["pipeline_version"])]
    for i, (k, v) in enumerate(info, 3):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True)
        ws.cell(row=i, column=2, value=v).alignment = Alignment(horizontal="left")
    _table(ws, PLAYER_HEADERS, _player_rows(d["players"]), start_row=len(info) + 5)
    ws.column_dimensions["A"].width = max(ws.column_dimensions["A"].width or 0, 16)
    ws.column_dimensions["B"].width = max(ws.column_dimensions["B"].width or 0, 22)

    ws = wb.create_sheet("Events")
    _table(ws, EVENT_HEADERS, _event_rows(d["events"]), flag_col=13)

    ws = wb.create_sheet("Rounds")
    _table(ws, ["Round", "Start (s)", "End (s)", "Winner", "Result", "Blue score", "Red score"],
           [[r["round_no"], r["start_s"], r["end_s"], r["winner_team"], r["result_text"], r["blue_score"],
             r["red_score"]] for r in d["rounds"]])

    ws = wb.create_sheet("Scoreboard")
    _table(ws, ["Round", "Player", "Stat", "Value", "Confidence"],
           [[s["round_no"] if s["round_no"] is not None else "match", s["ign"], s["stat_name"], s["value"],
             s["confidence"]] for s in d["stats"]])
    wb.save(path)
    return path


def export_range(conn, path, date_from=None, date_to=None):
    """Every match between two dates: match list, player totals, per-match player lines, all events."""
    from .db import list_matches
    matches = list_matches(conn, date_from, date_to)
    ids = [m["id"] for m in matches] or [-1]
    marks = ",".join("?" * len(ids))
    wb = Workbook()
    ws = wb.active; ws.title = "Matches"
    _table(ws, ["Date & time", "Room code", "Mode", "Team size", "Rounds", "Winner", "Players", "Eliminations",
                "Rows to review", "Status"],
           [[m["recorded_at"], m["room_code"], m["mode"], m["team_size"], m["rounds_played"], m["winner_team"],
             m["players"], m["eliminations"], m["to_review"], m["status"]] for m in matches])

    ws = wb.create_sheet("Player totals")
    rows = conn.execute(f"""SELECT ign, nickname, COUNT(DISTINCT match_id) AS matches, SUM(eliminations) AS el,
                                   SUM(knocks) AS kn, SUM(deaths) AS de, SUM(times_knocked) AS tk, SUM(damage_dealt) AS dmg
                            FROM v_player_match WHERE match_id IN ({marks})
                            GROUP BY player_id ORDER BY el DESC""", ids).fetchall()
    _table(ws, ["Player", "Nickname", "Matches", "Eliminations", "Knocks", "Deaths", "Times knocked", "Damage dealt",
                "Elims per death"],
           [[r["ign"], r["nickname"], r["matches"], r["el"], r["kn"], r["de"], r["tk"], r["dmg"],
             round(r["el"] / max(r["de"], 1), 2)] for r in rows])

    ws = wb.create_sheet("Player per match")
    rows = conn.execute(f"SELECT * FROM v_player_match WHERE match_id IN ({marks}) ORDER BY recorded_at DESC, team, eliminations DESC", ids).fetchall()
    _table(ws, ["Date & time"] + PLAYER_HEADERS, [[r["recorded_at"]] + pr for r, pr in zip(rows, _player_rows(rows))])

    ws = wb.create_sheet("All events")
    ev = conn.execute(f"SELECT * FROM v_events WHERE match_id IN ({marks}) ORDER BY recorded_at, true_time_s", ids).fetchall()
    _table(ws, EVENT_HEADERS, _event_rows(ev), flag_col=13)
    wb.save(path)
    return path
