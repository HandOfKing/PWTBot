---
name: cut-clip
description: Cut a short clip (or still frames) out of a full PWT match recording around a given time, so a problem can be reproduced without the 2 GB file. Use when a run analysis points at a time, when a NO_FEED_ROW / UNRESOLVED / NO_DROP row needs looking at, or when Chirag says "look at round N" or "around minute X".
argument-hint: "<recording> <start> <end>   (times as seconds or mm:ss)"
---

# Cut a clip: $ARGUMENTS

Never ask Chirag to upload a full match. Work from the file on his computer and cut what is needed.

1. Find the recording. Full matches live in `C:\Users\Chirag\Desktop\PWT Videos`; clips go to
   `C:\Users\Chirag\Desktop\PWT Videos\Output\clips`. Confirm the file exists before cutting.
2. Pad the window: feed rows lag deaths by up to ~9 s in a backlog, so for a death at T cut
   `T-3 s` to `T+12 s` unless told otherwise. For a round, cut from the round start to its board.
3. Cut without re-encoding, so OCR sees the original pixels:
   ```
   ffmpeg -hide_banner -ss <start> -to <end> -i "<recording>" -c copy -an "<out>"
   ```
   Name it `<match-stem>_r<round>_<mm-ss>-<mm-ss>.mp4`. `-c copy` snaps to keyframes, so the clip may
   start up to a couple of seconds early; note the clip's real start offset from `ffprobe` and
   convert times back to match time when reporting.
   If ffmpeg is not installed, say so and offer the OpenCV fallback (re-encodes, so mention that
   OCR results on it can differ slightly from the original).
4. For a single moment, also save stills: `ffmpeg -ss <t> -i "<recording>" -frames:v 1 "<out>.png"`
   and look at them before drawing conclusions.
5. Run on the clip one replay at a time, with a scratch database:
   `python -m pwt --db <scratch>/clip.db replay "<clip>" --out <scratch> --replace --quiet --roster <names>`
6. Report times in **match time** (clip time + offset) so they line up with the full run's output.

Never commit clips or videos (`*.mp4`, `*.mkv`); `clips/` is gitignored.
