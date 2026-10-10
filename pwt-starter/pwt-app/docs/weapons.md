# Weapons: what the knock rows say

A kill-feed **knock** row reads `killer · gun icon · knock icon · victim`. `pwt/readers/weapons.py` names
the gun from its icon; the result is the `weapon` column of the events. A gun is named only when its
template scores >= 0.80 **and** no other gun is within 0.05 of it (profile `feed.weapon_thresh`,
`feed.weapon_margin`); otherwise the column is empty ("unknown"), never a guess. Only knock rows are read
(Chirag, 2026-10-09: knocks only). Kill and tombstone rows keep the old UMP45-only reading.

## The library (`pwt/templates/weapons/<name>.png`, 28 icons)
Names and categories are Chirag's (2026-10-09, from the label sheets of 36 icon groups seen in the four
matches of 2026-10-01..04, plus his answers on the "unknown" and "look-alike" sheets).
`CATEGORY` in `weapons.py` is the table the planned highlight roles will use (no highlight code exists yet).

| Category | Guns |
|---|---|
| AR | M416, AKM, Beryl M762, AUG A3, Groza, SCAR-L, FAMAS, G36C, ACE32 |
| SMG | PP19 Bison, UMP45, Micro Uzi, Tommy Gun, P90, JS9, Vector, MP5K |
| Shotgun | DBS, S12K, S1897 |
| LMG | M249, MG3 (Chirag called the M249 a "DMR"; it is filed as an LMG) |
| Sniper | AWM |
| Other | Grenade, Molotov, Pan (melee), Car (a vehicle knock), Zone (the blue zone; the "killer" is not a player) |

Dictation notes taken as: "PP90 Bison" = PP19 Bison (same icon as the other Bison group), "Karel" = SCAR-L
(same icon as the other SCAR-L group), "M4" = M416.
The six guns added from the unknown sheet (G36C, ACE32, MP5K, S1897, Molotov, Car) have few sightings:
G36C 3, ACE32 4 (two of them AKM-looking rows the reader had called AKM; Chirag confirms), MP5K 2, S1897 1,
Molotov 4, Car 3. They are single-match-quality templates; check any new match that names one.

## How it was built and how well it works
- Templates: one per gun, the most typical clean icon (medoid) of that gun's sightings in **22-55-47 and
  20-27-36** only. 2026-10-01 and 2026-10-03 were held out.
- Groups whose crop also held the killer's name mix several guns (purity 0.64-0.71) and were not used as
  labels; the matcher splits them gun by gun (and agrees with Chirag's labels wherever a group was one gun).
- Held-out matches (2026-10-01, 2026-10-03), icons that could be cut out and labelled: **220 correct,
  5 disagreed, 0 unknown** of 225. The 5 are labelling errors in my groups (Beryl vs S12K, S12K vs AKM,
  matched at 0.97-0.99 to the other gun's template), not matcher errors; Chirag is asked to confirm.
- All 703 knock rows of the four matches: **697 named (99%)**, 6 unknown (with 22 guns: 683 named, 20
  unknown; Chirag labelled all 20, which added the six guns above). Adding the six guns changed 17 rows:
  14 unknown -> the guns he named, 3 AKM -> ACE32; no other row moved and the held-out result was unchanged.
  Not independent: the six new guns were built from rows of the same four matches.
- In the final full runs (the tracker votes over every sighting of a row) knock rows with a weapon: 196/198
  (22-55-47), 133/134 (20-27-36), 155/155 (10-01), 216/216 (10-03). The weapon column does not change with
  `--fps` (VP9 at 4, 12 and 24 fps).
- Selection bias to remember: the labelled set only contains icons that were easy to cut out. The hard
  ones (thin barrels) were named by window search and checked by eye on a sample, not against labels.
- Cost: about 4 ms per knock row.

## Known limits
- **Look-alikes:** AKM, S12K and Beryl M762 (and M416) are close silhouettes at ~16 px. The 0.05 margin
  refuses a pair that is too close. A rifle read as S12K counts as a shotgun in the highlights, so
  Chirag's confirmation of those three matters most.
- **Partly drawn icons:** a row caught while it slides in shows part of the icon. The tracker takes the most
  frequent gun over every sighting of the row (`feed.Line.weapons`), so a partial reading is outvoted.
- **Guns not in the library read empty.** The check sheets (`Output/weapon_check/`) list the unknowns.
- **Zone:** a knock by the blue zone has no killer; the highlight code must exclude it.

## Adding a gun
1. Collect its knock-row evidence crops (`<data folder>/evidence/match_N/ev_*.png`, rows with a weapon
   column that is empty) and show them to Chirag for a name.
2. Cut the icon (the ink left of the knock icon), pick the most typical one as `templates/weapons/<name>.png`
   (binary, white = ink, 2 px border), never hand-edit it.
3. Check it on a match it was not cut from: no other gun may score within 0.05 of it, and the held-out
   rows of every gun must stay correct. Add a fixture frame to `tests/fixtures` and a test.
