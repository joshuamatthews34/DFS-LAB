# DFS Lab

Your own lineup lab for DraftKings NFL, built from [SPEC.md](SPEC.md) one milestone at a time.

**Status:** Milestones 1–5 are built: import and check files, the grader, the comparison screen and
late-swap grader, the simulator, and the builder. Next up: Milestone 6 (fill methods and simulated ROI).

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

## Milestone 4 check: the simulator

1. Make sure Weeks 1 and 2 main are imported (`2026-wk01-main`, `2026-wk02-main`) with their
   post-game SaberSim exports. Add each week's pre-lock export too if you have it.
2. In Terminal (the internet is needed once, for the nflverse download G6 uses):

   ```
   DFS_LAB_GOLDEN=1 ./run.sh test tests/test_golden_m4.py -v -s
   ```

3. **Pass** = every line ends in `PASSED`:
   - the calibration table shows about **20.8%** of actual scores above SaberSim's 85th percentile
     (within 2 points), the finding from your NFL DFS project;
   - **G6:** the QB DraftKings points DFS Lab computes from nflverse match SaberSim's `Actual` for all
     27 Week 1 QBs and all 32 Week 2 QBs.

## The simulator (the Simulator screen)

**Calibration tab.** For every past slate with results, the table compares where actual scores
landed with where SaberSim's percentiles said they would. For example: expected 15% above the 85th
percentile, SaberSim X%, with tail widths Y%. DFS Lab fits two **tail widths** (lower and upper)
that bring the actual rates in line. Click **Use the fitted tail widths** to have the simulator use
them. 1.0 means SaberSim's ranges as they are, and 1.3 means 30% wider. The average (`dk_points`)
stays the same either way. By default only players projected 5+ points count; you can change that.

**Correlations tab.** How DraftKings scores move together, estimated from nflverse weekly stats
2021–2025 (2,718 team-weeks). For example, QB1 with his own WR1 is +0.47 and QB1 with the defense
he faces is −0.44. `./run.sh correlations --refresh` re-downloads and re-estimates.

**Simulate tab.** 10,000 simulated slates by default, with a fixed seed so the same settings give
the same result. Each player's outcomes follow a smooth curve through SaberSim's 25th–99th
percentiles, and the average equals `dk_points`. Players in the same game move together. The table
shows each player's simulated average and range next to SaberSim's.

**No hindsight:** the simulator reads the slate's **pre-lock** SaberSim export (projections and
percentiles). It never reads `Actual` or `Live Proj`. If the slate only has the post-game export, it
uses that export's projections and warns that they may include news from after lock.

---

## Milestone 5 check: the builder

1. Make sure the Week 3 TNF ATL@GB showdown is imported as `2026-wk03-tnf` with its **DraftKings
   entries file** and the **pre-lock** SaberSim export (the post-game export works for this check).
2. In Terminal:

   ```
   DFS_LAB_GOLDEN=1 ./run.sh test tests/test_golden_m5.py -v -s
   ```

   It builds lineups for every entry and checks each one against DraftKings' own player pool from
   your entries file: real IDs, captain IDs in the CPT column, both teams, under the $50,000 cap, no
   player twice, and your Entry IDs.
3. It prints the path of the upload file. **Upload that file in DraftKings' entry editor yourself.**
   **Pass** = the test says `PASSED` and DraftKings accepts the file without errors. (You don't have
   to keep the lineups.)

## Building lineups (the Build lineups screen)

1. Import the slate's **pre-lock SaberSim export** (with My Proj loaded), your **DKEntries** file (so
   DFS Lab knows which entries to fill), and your **War Room tags** if you have them.
2. Pick the slate, name the build (e.g. `default`), and pick the contests to fill.
3. Adjust anything you want (every setting has a sensible default), then click **Build**.
4. Check the results, then click **Download the DraftKings upload file** and upload it in
   DraftKings' entry editor yourself.

What it does:

- **Pre-lock snapshot:** the SaberSim export, entries file and War Room tags are copied into
  `slates/<slate>/prelock/<build>-<time>/` with a fingerprint (hash) of each and the time. The
  build reads only those copies. Actual scores, FPTS, ownership and standings are never read.
- **Candidates:** thousands of optimal lineups (5,000 by default), each for projections with
  ~25% random noise, or for one simulated slate. Players with a max exposure are left out of
  candidates in proportion, so the pool already fits your limits.
- **Rules you can set:** salary floor (showdown default $48,000), unique players between
  lineups (default 2), max total projected ownership. Stacking: classic QB + N of his WR/TEs
  with an optional bring-back; in showdown a QB captain gets one of his WR/TEs. At most one K and
  one DST in showdown. Game coverage floor (classic: games with a 44+ total get at least 0.5
  players per lineup).
- **Exposure limits:** War Room tags turn into max exposures: OVER = projected ownership × 1.5,
  WITH × 1.0, UNDER × 0.6, FADE = 3% max. These are untested starting points you can change, and
  every build records the rules it used. You can also set any player's min/max, and captain tiers
  (core 15–25%, favorite's QB 7–12%, secondary 7–25%, other QB 0–5%) or exact captain limits.
- **Late-game ownership haircut:** optional and off by default. It cuts the projected ownership of
  4:05/4:25 players (the field late-swaps off them). Every build records whether it was used.
- **Filling:** top by projection with your unique-players rule, keeping every min/max, captain
  limit and the game coverage floor. If something can't be met, it says so rather than hiding it.
- **Checks:** every lineup is checked against DraftKings' rules. Then the guardrails:
  - **chalk warning:** your exposure is 10+ points above a 20%+ projected-owned player;
  - **game coverage table;**
  - **ownership check:** the build's average total projected ownership and sub-5% players, against
    what your past contests' top-1% lineups had.
- **The file:** `slates/<slate>/builds/dfslab-<name>.csv`, in DraftKings' entries format with your
  Entry IDs. In classic, the FLEX slot holds a late-game player when possible, for late swap. If
  the slate has no entries file, it writes plain lineups to upload as new lineups instead.

Builds show up as lineup sets everywhere else ("DFS Lab build: default"), so you can grade and
compare them after the games. A DFS Lab build whose projections no longer match its pre-lock
snapshot is flagged on the Compare screen.

If a slate only has a post-game SaberSim export, you can still build (tick the box), but that
build is marked as a **refill**: its projections may include news from after lock.

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
./run.sh calibrate [--save]                     # calibration table; --save uses the fitted tail widths
./run.sh simulate 2026-wk03-main                # simulate a slate
./run.sh correlations [--refresh]               # the correlation estimates
./run.sh build 2026-wk03-tnf --name default     # build lineups and write the DraftKings file
./run.sh test                                  # run the automated checks
```

The Milestone 1 check can also run as a test. Put only the Week 2 files in a folder, then:

```
DFS_LAB_WEEK2_DIR=~/Downloads/week2 ./run.sh test tests/test_m1_week2_check.py
```

---

## Not built yet

- Codex captain caps: SPEC 3.6 doesn't give the file layout yet, so there's no importer for them.
- Player pairings (6.3); fill methods 1 and 3 (top by simulated ROI, portfolio) and the field model
  (Milestone 6); the season tracker (Milestone 7).
- Codex captain tiers are set by hand on the Build screen until the Codex file layout is known.
