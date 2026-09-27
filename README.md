# DFS Lab

Your own lineup lab for DraftKings NFL, built from [SPEC.md](SPEC.md) one milestone at a time.

**Status:** Milestone 1 (import and check files) and Milestone 2 (the grader) are built.
Next up: Milestone 3 (comparison screen and late-swap grader).

---

## Start it

In Terminal, from the `dfs-lab` folder:

```
./run.sh
```

The first run sets things up (about a minute). After that it opens DFS Lab in your browser.
To stop it, go back to Terminal and press `Ctrl+C`.

You need Python 3.11 or newer. If `run.sh` says it's missing, install it from
https://www.python.org/downloads/ and run `./run.sh` again.

---

## Milestone 1 check (you can do this yourself)

1. Put the **Week 2 main slate** files in your Downloads folder:
   - the SaberSim **post-game** player export (the one with the `Actual` column filled in)
   - your DraftKings entries file(s) (`DKEntries.csv`)
   - the three Week 2 main-slate standings zips (`contest-standings-<contestID>.zip`)
   - payout files if you've typed any in (optional; see below)
2. Run `./run.sh`. On the **Import files** screen:
   - type the slate name `2026-wk02-main`
   - tick the Import box next to each Week 2 file
   - click **Import**
3. **Pass** = the big line at the top of the report reads

   > **242 entries · 3 standings files · 0 FPTS mismatches**

   and there are no red problem boxes.

If anything is red, the message says exactly which file and what's wrong. Bring it back to
your NFL DFS project in Claude if it doesn't make sense.

---

## Milestone 2 check: the grader

The grader is trusted once it reproduces the golden numbers you already checked by hand (SPEC section 9, G1–G4).

1. Import **Week 1 main** as slate `2026-wk01-main` and **Week 2 main** as slate `2026-wk02-main`: the
   post-game SaberSim export, your entries files, the standings zips, and the SaberSim fill files.
2. Put these labels in the fill files' names before importing, so the check can find them:
   `Unique Rank 3`, `Portfolio+`, `UR1`, `UR2`, `UR4`, `UR5` (for example `UR1 week2.csv`).
3. In Terminal, from the `dfs-lab` folder:

   ```
   DFS_LAB_GOLDEN=1 ./run.sh test tests/test_golden_m2.py -v
   ```

4. **Pass** = every line ends in `PASSED`. A failure prints the number DFS Lab got next to the one
   expected. Bring it to your NFL DFS project in Claude if it isn't obvious why.

## Grading lineups (the Grade lineups screen)

Pick a slate, a contest (any standings file in the slate) and one or more **lineup sets**, then click
**Grade**. The lineup sets are:

- **My entered lineups (from the standings):** your entries exactly as DraftKings scored them, late
  swaps included. This is the one to use for "how did I actually do".
- **Each entries file:** the lineups in that `DKEntries` file. If one disagrees with what DraftKings
  scored (for example a pre-swap file), the grader says so.
- **Each lineup file:** DFS Army exports, SaberSim fill files and so on.

Tick **Only entries entered in this contest** to grade just the entries you had in that contest.
Otherwise every lineup in the set is scored against that contest's field.

What you get:

| | |
|---|---|
| **Graded against** | Contest, field size, winning score, top-1% line, cash line (with a payout file) and the perfect lineup. |
| **Build summary** | One row per lineup set: average, median and best score; best finish; counts in the top 0.1/1/5/10/20%; cashed, won, fees and ROI (only with a payout file, never estimated); average salary left, total ownership, players shared, duplicates. |
| **Player exposure** | Each player's count and exposure, projected vs actual ownership, leverage (exposure minus actual ownership), captain/FLEX split, War Room tag, and how many of the contest's top-1% lineups had them. |
| **Lineups** | Every lineup with score, rank, top-%, prize and stack tag. Click a column to sort. |

How the numbers work:

- **Scores** come from SaberSim's `Actual` (M1 checked it matches DraftKings). A captain scores 1.5 × the player's FLEX score.
- **Top X%** means the share of the field scoring *strictly higher* is X% or less.
- Each lineup is ranked against the real field on its own. Your entries that were in the contest keep their real place.
- **Ties** split the prize the way DraftKings does: the tied places' prizes are averaged.
- **Stack tags:** `QB+2|1` = QB with 2 of his own WR/TE and 1 RB/WR/TE from the other team. Showdown shows the captain's position and the team split, e.g. `QB CPT 4-2`.

Results are saved in `slates/<slate>/results/grades/<contest>/` (a text report plus CSVs you can open in Excel).

---

## What the report tells you

| Line | Meaning |
|---|---|
| **entries** | Your entries with a full lineup, counted once per Entry ID. If the same entry appears in a pre-swap and a post-swap file, it's counted once and the newest file wins. Blank reservations are skipped and counted separately. |
| **standings files** | DraftKings standings files that read cleanly, one per contest. |
| **FPTS mismatches** | Every player in the standings is compared with SaberSim's `Actual` score. They should agree exactly. "Not run" means there's no post-game SaberSim export or no standings file. |
| **Blend** | "NOT loaded" means `My Proj` equals `SS Proj` on every row: your SaberSim/LineStar/DFS Army blend wasn't loaded before you exported. |
| **Unmatched names** | Names that couldn't be matched to a SaberSim player. None are ever dropped silently. If a name is the same player spelled differently, add a line to `core/aliases.csv`. |
| **0-byte files** | DraftKings sometimes serves an empty standings file for its biggest contests. Download it again later. |

---

## Files DFS Lab reads

It works out each file's type from its header row and rejects anything it doesn't recognise.

| File | How to get it |
|---|---|
| SaberSim player export | Export from SaberSim. Before lock, load `My Proj` first. |
| DraftKings entries file | "Edit entries" → download CSV (`DKEntries.csv`). |
| DFS Army lineup export | DFS Army's lineup CSV (header `CPT, FLEX, ...`). |
| Contest standings | The zip from the contest page after the games. |
| Payout table | Type it in yourself (see below). |
| War Room tags | JSON, e.g. `{"Dak Prescott": "OVER", "Kenneth Walker III": {"tag": "UNDER", "max": 12}}` |

**Payout files** are a small CSV per contest, named after the contest ID, for example
`payouts-195648006.csv`:

```
rank_from,rank_to,prize
1,1,$10000
2,2,$5000
3,5,$1000
```

Without a payout file, ROI shows as "not available". It is never estimated.

---

## Where your data goes

- `slates/<slate name>/raw/`: untouched copies of every file you import
- `slates/<slate name>/results/import_report.txt`: the report, as text
- `dfs_lab.db`: everything DFS Lab has read

None of this goes into git. This repository is public, so your contest files stay on your computer.

---

## Command-line versions (optional)

```
./run.sh scan --folder ~/Downloads             # list files DFS Lab recognises
./run.sh import 2026-wk02-main FILE FILE ...   # import and print the report
./run.sh recheck 2026-wk02-main                # re-read a slate's saved files
./run.sh report 2026-wk02-main                 # print the last report
./run.sh sets 2026-wk02-main                   # list contests and lineup sets
./run.sh grade 2026-wk02-main 195648006        # grade every lineup set against that contest
./run.sh test                                  # run the automated checks
```

The Milestone 1 check can also run as a test. Put only the Week 2 files in a folder, then:

```
DFS_LAB_WEEK2_DIR=~/Downloads/week2 ./run.sh test tests/test_m1_week2_check.py
```

---

## Not built yet

- Codex captain caps: SPEC 3.6 doesn't give the file layout yet, so there's no importer for them.
- Player pairings (6.3), the head-to-head comparison and late-swap grader (Milestone 3), and the
  simulator, builder and season tracker (Milestones 4–7).
