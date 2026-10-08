"""Files that go next to PWT.exe in the Windows zip. Run by the build:

    python app/build_extras.py dist/PWT

  roster.txt  -- the player names from docs/roster.md, pre-filled in the app on first run
  README.txt  -- how to use it, for someone who has never seen the project
"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pwt import __version__  # noqa: E402

README = f"""PWT {__version__} - match stats from PUBG Mobile WoW recordings
==========================================================

What it does
  Reads an OBS recording of a spectated WoW custom room and writes a table of
  every knock and elimination (who, whom, when, which round) to Excel.
  Nothing is installed and nothing goes online.

Use it
  1. Unzip this whole folder somewhere (e.g. Documents\\PWT). Keep the files together.
  2. Double-click PWT.exe.
     The first time, Windows may say "Windows protected your PC" because the app
     is not code-signed. Click "More info", then "Run anyway".
  3. Browse... and pick the recording (.mkv or .mp4).
     It must be a first-person spectator recording of a 6v6 round-based room,
     GameLoop at 1920x1080. Other layouts are refused rather than guessed at.
  4. Check the "Player names" box: one name per line, spelled exactly as in the
     game, all 12 players of the match. Kill-feed names are matched against this
     list only, so a missing player goes unnamed. The box remembers the list from
     your last run. After a run, the result panel names anyone the final
     scoreboard showed who is not in the list: add them and run again.
  5. Press Start. The bar shows how long is left. You can Stop at any time; the
     part done so far is kept.

When recording
  At the end of the match, keep recording on the final scoreboard and scroll it
  slowly from the top to the bottom (and back up) so every player's row is on
  screen for a second or two. The app reads Eliminations, Assists, Damage
  Dealt, Damage Taken and Knock Outs for every row it sees.

Results
  Next to the recording:  <recording> - PWT.xlsx       the tables
                          <recording> - PWT events.csv  the same events, plain
                          <recording> - PWT log.txt     what happened, for checking
  Every match is also kept in the app (Matches tab), where you can export one
  or all of them again.

  Rows the app could not read for certain are flagged, never guessed:
    NO_FEED_ROW   someone died (the Remaining counter dropped) but no readable
                  kill-feed line said who -- killer and victim left empty
    UNRESOLVED    a kill-feed line was found but a name could not be read
    NO_DROP       a kill line the Remaining counter saw no death for (a repeat
                  or a misread icon) -- kept in the table, not counted

Where the data lives
  %LOCALAPPDATA%\\PWT  (the database and small evidence images of each feed line).
  To keep it next to the app instead, create an empty file named portable.txt
  beside PWT.exe.
"""


def roster(md):
    names = []
    for line in md.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) > 3 and cells[1].isdigit():
            m = re.match(r"`([^`]+)`", cells[2])
            if m: names.append(m.group(1))
    return names


def main(dest):
    dest = Path(dest)
    names = roster(ROOT / "docs" / "roster.md")
    assert len(names) >= 10, f"only {len(names)} names parsed from docs/roster.md"
    (dest / "roster.txt").write_text("# player names, one per line (from docs/roster.md)\n" + "\n".join(names) + "\n",
                                     encoding="utf-8")
    (dest / "README.txt").write_text(README, encoding="utf-8", newline="\r\n")   # Notepad-friendly
    print(f"wrote roster.txt ({len(names)} names) and README.txt to {dest}")


if __name__ == "__main__":
    main(sys.argv[1])
