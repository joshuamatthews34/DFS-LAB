# DFS Lab

Your own lineup lab for DraftKings NFL, built from [SPEC.md](SPEC.md) one milestone at a time.

**Status:** Milestone 1 (import and check files) is built. Next up: Milestone 2 (the grader).

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
./run.sh test                                  # run the automated checks
```

The Milestone 1 check can also run as a test. Put only the Week 2 files in a folder, then:

```
DFS_LAB_WEEK2_DIR=~/Downloads/week2 ./run.sh test tests/test_m1_week2_check.py
```

---

## Not built yet

- Codex captain caps: SPEC 3.6 doesn't give the file layout yet, so there's no importer for them.
- The grader, comparison screen, simulator and builder are Milestones 2–7.
