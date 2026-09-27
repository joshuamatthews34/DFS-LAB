# DFS Lab

Your own lineup lab for DraftKings NFL, built from [SPEC.md](SPEC.md) one milestone at a time.

**Status:** Milestones 1–3 are built: import and check files, the grader, and the comparison screen
and late-swap grader. Next up: Milestone 4 (the simulator).

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

## Milestone 3 check: comparison and late swap

1. Import the **Week 3 TNF ATL@GB showdown** as slate `2026-wk03-tnf`: the post-game SaberSim export,
   your entries file, and the mini-MAX standings zip (contest 195943225).
2. In slate `2026-wk02-main`, put `pre-swap` in the name of the entries file from **before** the late
   swap. You can also put `post-swap` in the one from after it. If you don't, your entered lineups from
   the standings are used as the after-swap lineups.
3. In Terminal:

   ```
   DFS_LAB_GOLDEN=1 ./run.sh test tests/test_golden_m3.py -v
   ```

4. **Pass** = every line ends in `PASSED`: the mini-MAX has 237,812 entries and a 152.1 winner, the
   perfect lineup is CPT London / Bijan / Watson / Golden / B. Robinson Jr. / Hooper = 152.10
   ($48,600), your best entered lineup scored 146.33 (rank #1,170), and the Week 2 late swap shows
   133 of 240 changed, net −1,028.3 (42 better, 90 worse).

## Comparing builds (the Compare builds screen)

1. Pick a slate. Open **Name your builds** and give each lineup set you care about a **name** and a
   **method**, e.g. name "SaberSim Unique Rank 3 (entered)", method "SaberSim UR3". Tick:
   - **Refill** for lineups SaberSim rebuilt after the fact. They're only fairly compared with other refills.
   - **Hindsight** for anything with settings added after the games (like hand-set minimums).
     These are left out of comparisons and never saved to the season.
2. Pick a contest and 2–6 builds, then click **Compare**.

You get every build-summary number side by side (including each build's **projection average**),
the players each build leaned into compared with the others (and how they scored), the full
exposure-difference table, how many identical lineups the builds share, and two statistics:
Mann-Whitney on lineup scores and Fisher's exact test on top-5% counts. All lineups on one slate
share one set of game results, so those p-values are too generous; the screen always says so.

Projection averages use the pre-lock SaberSim export when the slate has one. If it only has the
post-game export, the screen warns that the projections may include news from after lock.

## Season (the Season screen)

Every comparison saves each named, non-hindsight build's result. The Season screen shows each
method across slates: top-1% and top-5% rates, cash rate and ROI. Refills get their own rows. It
also says how many slates are in it. About 10+ are needed before switching methods.

## Late swap (the Late swap screen)

Pick the lineups from **before** the swap (usually your pre-swap `DKEntries` file) and **after** it
(usually "My entered lineups", which is exactly what DraftKings scored). DFS Lab pairs them by Entry
ID. If the IDs were reshuffled and none match, it pairs them on the players in games that had
already started. It then shows each swap's gain or loss and the total. A swap that makes an illegal
roster (over the cap, wrong positions, same player twice) is rejected and not counted.

"Games already locked when you swapped" defaults to the earliest kickoff. Change it if you swapped
later, e.g. after the 4:05 games started.

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
./run.sh label 2026-wk02-main KEY --name "UR3" --method "SaberSim UR3"   # name a build
./run.sh compare 2026-wk02-main 195648006 --set KEY --set KEY           # compare builds
./run.sh lateswap 2026-wk02-main BEFORE_KEY [AFTER_KEY]                 # grade a late swap
./run.sh season                                                         # the season table
./run.sh test                                  # run the automated checks
```

The Milestone 1 check can also run as a test. Put only the Week 2 files in a folder, then:

```
DFS_LAB_WEEK2_DIR=~/Downloads/week2 ./run.sh test tests/test_m1_week2_check.py
```

---

## Not built yet

- Codex captain caps: SPEC 3.6 doesn't give the file layout yet, so there's no importer for them.
- Player pairings (6.3); the simulator, builder, fill methods and simulated ROI (Milestones 4–6).
- Flagging a build whose pre-lock projection doesn't match the pre-lock snapshot (section 7): the
  snapshot is created at build time, which arrives with the builder in Milestone 5.
