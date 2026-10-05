# PWT roster — exact in-game spellings

Taken from the in-game player list, 2026-10-05. **Spelling matters.** Name
resolution works by fuzzy-matching garbled OCR to this list, so a wrong entry
either fails to match or, worse, looks like a second player and makes the
matcher refuse both. Copy these exactly.

| # | Name | Notes |
|---|---|---|
| 1 | `Sarthakkkd` | three k's |
| 2 | `RGODxEMPEROR` | plain `O`, **not** `Ø` |
| 3 | `KG696969` | digit-heavy; OCR reads it as `KGBSEIES`, the glyph fold repairs it |
| 4 | `KhajwaKILL3R` | `3`, not `E` |
| 5 | `PARABloodthirs` | capital `B` in the middle |
| 6 | `OmkarKurhade` | |
| 7 | `TheWolverine` | |
| 8 | `Strike333` | |
| 9 | `DeathwishツSpy` | katakana `ツ`; stripped before matching, compares as `DeathwishSpy` |
| 10 | `Makjets69` | |
| 11 | `StarJohnnysins` | |
| 12 | `Vatsal099999` | digit-heavy |
| 13 | `InnocentDevil` | capital `I` and `D`, **no** trailing digit |
| 14 | `enriquelatin` | all lower case |
| 15 | `Anoydyne15op` | |
| 16 | `TrishaSingh` | |
| 17 | `BruceWayne³` | superscript `³`; stripped before matching, compares as `BruceWayne` |
| 18 | `WonderWoman888` | full `Woman` |

## Verified safe
`names.check_roster_collisions` passes: all 18 fold to distinct strings. The
closest pair is `PARABloodthirs` vs `StarJohnnysins` at 0.57, well under the
0.85 where a swap becomes possible. Measured on 205 real OCR strings from
`Video_Project_9.mp4`, the full 18-name roster resolves the same number of rows
as a 12-name one — **adding players costs nothing as long as the spellings are right.**

What *does* break it is two entries for the same person (`WonderWoma888` and
`WonderWoman888`). Those fold alike, the margin rule can't separate them, and it
correctly refuses both — dropping resolution from 68% to 17% in a test. If
someone changes their in-game name, add it with `pwt rename OLD NEW`, which
keeps the old spelling as an **alias** rather than a second player.

## Load it once
```
python -m pwt players --add Sarthakkkd RGODxEMPEROR KG696969 KhajwaKILL3R PARABloodthirs OmkarKurhade TheWolverine Strike333 DeathwishツSpy Makjets69 StarJohnnysins Vatsal099999 InnocentDevil enriquelatin Anoydyne15op TrishaSingh BruceWayne³ WonderWoman888
```
After that, `pwt replay` matches against the saved roster and `--roster` is optional.
A match only ever contains ~12 of these; the extra names are harmless.
