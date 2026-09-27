# DFS Lab — build spec for Claude Code

**Owner:** Savage (CoachSavDFS) · **Written:** Sep 27, 2026 · **Status:** version 1 spec

This file is written for Claude Code to build from, and for Savage to follow along. Savage has never coded, so every milestone ends with a plain-English check he can do himself.

---

## 0. How to use this spec (Savage, read this part)

1. Install Claude Code by following Anthropic's official guide: https://docs.claude.com/en/docs/claude-code
2. On your Mac, make a new empty folder called `dfs-lab` in your home folder. Don't reuse `savdfs`. Keep this project separate so nothing old gets overwritten.
3. Put this file in that folder and name it `SPEC.md`.
4. Open Claude Code in that folder and say:
   > Read SPEC.md. Build Milestone 1 only. When it's done, show me how to run the check at the end of the milestone, and stop.
5. Do one milestone at a time. Don't move on until the milestone's check passes.
6. Whenever you're unsure whether a number is right, bring the output back to your NFL DFS project in Claude. The "golden tests" in section 9 are numbers we've already verified by hand.

**Rules that never bend:**
- **Real money is on the line.** The tool must never make up a number. If a file is missing or a column doesn't match, it stops and says exactly what's wrong.
- **DraftKings' terms prohibit automated entry.** The tool only *writes a CSV*. You upload that CSV to DraftKings yourself. It never logs in to, scrapes, or clicks anything on DraftKings.
- **No hindsight.** Any build that's compared against SaberSim or DFS Army must use only information available before lock (section 7).

---

## 1. What the tool is for

The main goal is to answer: **"If I build lineups my own way from the same projections, do I do better or worse than SaberSim and DFS Army?"**

To make that a clean test, version 1 **uses the same inputs** you already export:
- SaberSim projections, percentiles and ownership.
- DFS Army exposures and settings.
- War Room and Codex tags.

Only the *lineup-building method* is the tool's own. Any difference in results then comes from how lineups are built, not from different projections.

**Four jobs:**
1. **Import:** read a slate's files from `~/Downloads` into a clean per-slate folder, checking every file.
2. **Build:** generate lineups with its own optimizer (classic main slate and showdown). Exposure caps come from War Room and Codex tags plus your own settings.
3. **Grade:** score any set of lineups (yours, SaberSim's, DFS Army's) against the real contest standings file after the games.
4. **Compare:** put builds side by side for the same slate and track results across weeks.

**Out of scope for version 1:** making its own projections, entering contests, pulling live news, and other sports.

---

## 2. Tech choices (Claude Code: use these unless there's a strong reason not to)

- **Language:** Python 3.11+.
- **Screens:** Streamlit, a local web page opened in the browser. It's the simplest option for a non-coder to run.
- **Optimizer:** PuLP with the CBC solver, or `scipy.optimize.milp`. Lineups are an integer program.
- **Data:** pandas and numpy. Store everything in SQLite (`dfs_lab.db`) plus the original files in per-slate folders.
- **Tests:** pytest. The golden tests in section 9 must pass before a milestone is called done.
- **Run command:** one command Savage can copy, e.g. `./run.sh`, which opens the app in his browser.
- Keep the code in a git repository, so every change can be undone.

**Folder layout:**
```
dfs-lab/
  SPEC.md
  run.sh
  app/            # Streamlit screens
  core/           # importers, optimizer, simulator, grader (no UI code)
  tests/          # golden tests
  slates/
    2026-wk03-main/
      raw/        # untouched copies of every imported file
      prelock/    # frozen pre-lock snapshot (section 7)
      builds/     # every lineup set: ours, SaberSim's, DFS Army's
      results/    # standings, payouts, grades
  dfs_lab.db
```

---

## 3. Input files (exact formats, verified from Savage's real files)

The importer must detect each type by its header row and reject anything that doesn't match.

### 3.1 SaberSim player export (classic and showdown)
CSV with header:
`DFS ID, Name, Pos, Team, Opp, Status, Salary, Actual, SS Proj, Live Proj, My Proj, Value, My Own, Adj Own, Min Exp, Max Exp, Saber Team, Saber Total, dk_points, dk_25_percentile, dk_50_percentile, dk_75_percentile, dk_85_percentile, dk_95_percentile, dk_99_percentile, …`
It also has FanDuel/Yahoo/OB columns (ignore them), plus `dk_std` and stat columns.

- `SS Proj` is SaberSim's projection. `My Proj` is Savage's blend (SaberSim, LineStar and DFS Army). **If every row has `My Proj == SS Proj`, the blend wasn't loaded.** Show a warning.
- `My Own` is projected ownership (%). `Saber Team` is the team's implied total and `Saber Total` is the game total.
- `Actual` and `Live Proj` hold **post-game** scores once the games are played. **Never use them for building** (section 7). They're for grading only.
- **Showdown exports list each player twice:** a CPT row and a FLEX row, with **different DFS IDs**. The CPT row's salary is 1.5× the FLEX salary (Bijan: CPT $17,700 / FLEX $11,800).
- Some column names can contain a stray backslash. Strip `\` from headers.

### 3.2 DraftKings entries file (upload/download CSV)
- **Classic:** `Entry ID, Contest Name, Contest ID, Entry Fee, QB, RB, RB, WR, WR, WR, TE, FLEX, DST`. Cells are DFS IDs (integers). The fee looks like `$3`.
- **Showdown:** `Entry ID, Contest Name, Contest ID, Entry Fee, CPT, FLEX, FLEX, FLEX, FLEX, FLEX`.
- Rows can have blank lineup cells; skip them. Extra instruction columns to the right are ignored.
- The tool **exports** in this exact format, so Savage can upload it to DraftKings by hand.

### 3.3 DFS Army lineup export (showdown)
Header `CPT, FLEX, FLEX, FLEX, FLEX, FLEX`, which may start with a byte-order mark. Cells look like `Michael Penix Jr. (44225921)`. Take the number in brackets as the DFS ID.

### 3.4 DraftKings contest standings (after the games)
Download it from the contest page. It usually comes as a zip holding `contest-standings-<contestID>.csv`.

Header: `Rank, EntryId, EntryName, TimeRemaining, Points, Lineup, (blank), Player, Roster Position, %Drafted, FPTS`
- **Left block:** one row per entry. `Lineup` is a single string like `DST Panthers  FLEX Jake Ferguson QB Dak Prescott …`. Showdown uses `CPT` and `FLEX` tags.
  - To parse it, split before each position tag (`QB|RB|WR|TE|FLEX|DST|CPT`) that's followed by a space.
  - Some rows have an empty or odd lineup. Skip them, and count how many were skipped.
- **Right block:** one row per player, with the **actual ownership** (`%Drafted`, e.g. `32.79%`) and the actual DraftKings points (`FPTS`).
- **Sizes can be huge.** The Week 1 $3.5M Millionaire file was 167 MB with 832,342 entries. Read only the columns you need, in chunks if necessary.
- **Known problem:** DraftKings sometimes serves a **0-byte** file for its largest contests. Detect this and tell Savage to try again later, instead of crashing.
- Zips downloaded on macOS can be hard links. If a file can't be read, tell Savage to Duplicate it in Finder.

### 3.5 Payout table (typed in by Savage)
Standings files don't include prizes. Store payouts as a small CSV per contest, `rank_from, rank_to, prize`, which Savage fills in from the contest's prize screen. **Without a payout file, show ROI as "not available". Never estimate it.**

### 3.6 War Room tags and Codex caps
- **War Room exposure board:** JSON, `{player_name: "OVER"|"WITH"|"UNDER"|"FADE", …}` plus optional numeric caps. A Week 3 example already exists in Savage's project (`wk3_warroom_tags.json`).
- **Codex (showdown):** captain pool with tags (core / leverage / fade), captain min–max %, and archetype.
- Match names with the normalizer in section 4.4. **List every name that didn't match.** Never drop one silently.

---

## 4. DraftKings rules the tool must enforce

### 4.1 Classic (NFL main slate)
- Roster: QB, RB, RB, WR, WR, WR, TE, FLEX (RB/WR/TE), DST. The salary cap is $50,000.
- Players must come from at least 2 different games.

### 4.2 Showdown
- CPT + 5 FLEX, $50,000 cap. CPT scores 1.5× points and costs 1.5× salary.
- **Both teams must be represented.**
- The same player can't be used as both CPT and FLEX.

### 4.3 Scoring
For **grading**, use DraftKings' own numbers: `FPTS` from standings, or `Actual` from the SaberSim post-game export. Both matched DraftKings exactly on every player we checked across Weeks 1–2 and the showdowns. Don't recompute scoring for grading.

If the tool ever computes DK points itself (for example, from nflverse stats):
- **QB and skill positions:**
  - Pass yards 0.04, pass TD 4, INT −1, 300-yard passing bonus 3.
  - Rush yards 0.1, rush TD 6, 100-yard rushing bonus 3.
  - Reception 1, receiving yards 0.1, receiving TD 6, 100-yard receiving bonus 3.
  - Fumble lost −1, two-point conversion 2.
  - Return TDs 6.
- **DST:** include fumble-return TDs. An earlier version of our scoring missed them.
- **Validate:** it must match SaberSim `Actual` for every QB in Weeks 1–2 (0 mismatches). That's golden test G6.

### 4.4 Name matching
- Lowercase and strip accents.
- Remove `. ' -`.
- Remove suffixes: jr, sr, ii, iii, iv, v.
- Collapse spaces.
- Keep a small alias table for exceptions, e.g. `kenneth gainwell = kenny gainwell`.

---

## 5. The builder (the tool's own method)

### 5.1 Player outcome simulation
- Each player's outcome distribution comes from SaberSim's percentiles: `dk_25`, `dk_50`, `dk_75`, `dk_85`, `dk_95`, `dk_99`, with `dk_points` as the mean. Interpolate between the percentiles and extend the tails smoothly.
- **Calibration:** SaberSim's ranges ran narrow in our checks. 20.8% of actual scores landed above the 85th percentile (15% expected) and 17.5% below the 25th (25% expected). Add a tail-width setting, calibrated from past slates' `Actual` vs the percentiles, and show the calibration table on screen.
- **Correlation:** players in the same game move together. Estimate correlations from nflverse 2021–25 weekly stats: QB–own WR/TE, QB–own RB, QB–opposing pass-catchers, RB–own DST, QB–own DST (negative), and teammates' shared game total. Apply them with a Gaussian copula.
- Default: 10,000 simulated slates. A fixed random seed makes runs repeatable.

### 5.2 Lineup generation
- Optimize with random noise on projections to get a pool of candidate lineups (default 5,000–20,000). Add ~25% lognormal noise, or sample from the simulations.
- **Constraints Savage can set:**
  - Salary floor. Showdown default $48,000; our tests showed no floor left a quarter of lineups with $10,600+ unspent.
  - Min/max exposure per player and per captain.
  - Minimum unique players between lineups.
  - Max total projected ownership.
  - Stacking rules. Classic: QB + at least N pass-catchers, optional bring-back. Showdown: if the QB is captain, add at least one of his WR/TEs.
  - At most one K and at most one DST per showdown lineup.
  - Game coverage floor (see 5.4).
- **War Room tags → exposure caps** (editable defaults): OVER = projected ownership × 1.5, WITH = × 1.0, UNDER = × 0.6, FADE = 0–3%. **These multipliers are untested starting points I picked, not DFS Army's numbers.** The Week 2 grade found OVER picks had no leverage (0.95) and WITH picks had the most (2.08). Record which rule set each build used.
- **Codex → captain tiers** (showdown, from the frozen v4 template):
  - Four core captains at 15–25% each.
  - The favorite's QB at 7–12%.
  - Secondary players at 7–25%.
  - The other QB at 0–5%.
- **Late-game ownership:** in Week 2, SaberSim over-projected the ownership of 4:05/4:25 chalk (Lamb projected at 30%, actually 15–17%), apparently because the field late-swaps. Offer an optional "late-game ownership haircut" setting, off by default, and log whether it was used.

### 5.3 Filling entries (choosing which lineups to enter)
Build these fill methods so they can be tested against each other:
1. **Top by simulated ROI:** needs a payout file and a field model (5.5).
2. **Top by projection,** with N uniques.
3. **Portfolio (set-based):** greedily add the lineup that most increases the *set's* chance of a top-1% finish, given the lineups already chosen.

**Default uniques: 2.** Across Weeks 1–2, SaberSim fills with 1–2 uniques and Portfolio+ finished ahead of 4–5 uniques on every field tested. It's a lean, not proof; see the uniques backtest doc in the project.

Duplicate lineups within the same contest are never allowed.

### 5.4 Guardrails (from past mistakes)
- **Game coverage floor:** in a 150-lineup build, every game with a total of ~44+ gets at least ~0.5 players per lineup. In Week 1 we had 0.51 per lineup in CHI@CAR, the 96-point game.
- **Chalk warning:** flag when your exposure to a top-projected chalk player is well above the field. In Week 1: Chase 54% vs 40% field, and Mayer 60% vs 37%.
- **Ownership check:** show the build's average total ownership against the typical top-1% range. In Week 2, the top 1% averaged 104% vs Savage's 93%, with fewer sub-5% players.

### 5.5 Field model (for simulated ROI)
- **Backtests:** use the *real* field lineups from the standings file. That's the most honest option.
- **Future contests:** build a synthetic field from projected ownership, with the field's stacking and salary habits taken from past standings (e.g., most field lineups use nearly the full $50K).
- **Your own lineups share the field with each other.** If two of yours tie, they split the prize.

---

## 6. Grading and comparison screens

Your buddy's dashboard is a good model. Build these screens.

### 6.1 Build summary (one row per build, tabs to switch)
- Average, median and best score.
- Best finish: rank and top-X%.
- Counts in the top 0.1%, 1%, 5%, 10% and 20%.
- Cashed count, dollars won, fees and ROI. Show these only if a payout file exists.
- Average salary left, average total ownership (actual), average players shared between lineups, duplicate count.
- A line saying what it was graded against, e.g. "Graded against NFL Showdown $100K mini-MAX (ATL @ GB), 237,812 entries, winning score 152.1, top 1% 144.3, cash line 124.7, perfect lineup 152.1."
- **Percentile definition:** the share of the field scoring *strictly higher*. "Top 5%" means that share is 5% or less.

### 6.2 Player exposure table
- Position, team, player, salary, projection and final score.
- Count and exposure %.
- Projected ownership, actual ownership, and leverage (your exposure minus actual ownership).
- A captain/FLEX split for showdown, and the War Room tag.
- The top-1% share: how many of the contest's top-1% lineups had this player.

### 6.3 Player pairings
The most common pairs and stacks in your build, next to how often those pairs appeared in the contest's top 1%.

### 6.4 Lineup viewer
- Each lineup with its rank, top-X% and prize, sortable by final score.
- Tags such as `QB+2|2` for stack shape.

### 6.5 Head-to-head comparison (the main point)
- **Pick a slate, then pick 2–6 builds**: e.g. "SaberSim Unique Rank 3 (entered)", "SaberSim Portfolio+", "DFS Army v4 template", "DFS Lab default".
- **Show:** all 6.1 metrics side by side, exposure differences (which players each build leaned into and how they scored), and shared lineups between builds.
- **Statistics:** Mann-Whitney on lineup scores and Fisher's exact test on top-5% counts. **Always add the warning:** "All lineups on one slate share one set of game results; these p-values are too generous."
- **Season view:** a running table across slates of each method's top-1%, top-5%, cash rate and ROI. Add a line saying how many slates are in it and that about 10+ are needed before switching methods.

### 6.6 Late-swap grader
- Pair the pre-swap and post-swap entry files by Entry ID, or by matching early-game players if the IDs were reshuffled.
- Report each swap's point gain or loss and the total.
- For reference: Week 1 late swap gained +1,069 points and Week 2 lost −1,028 (133 of 240 lineups changed; 42 better, 90 worse).
- Reject any swap that produces an illegal roster.

---

## 7. No-hindsight rules (the tool enforces these)

- At build time, the tool saves a **pre-lock snapshot**: every input file, a hash of each, and the time. All builds and comparisons read only from this snapshot.
- Build code may **never** read `Actual`, `Live Proj`, `FPTS`, `%Drafted` or anything from standings.
- **Refills of past slates in SaberSim are marked "refill".** When Savage reopened Weeks 1–2, SaberSim generated a *new lineup pool*: 0 lineups in common with what he entered. So a refill can be compared fairly with other refills, but not with the original entries.
- **Hand-set minimums added after a game** (like the Hooper and Sturdivant minimums in DFS Army v4) are marked "hindsight" and excluded from method comparisons.
- The comparison screen shows each build's projection average. A build whose pre-lock projection doesn't match the snapshot gets flagged.

---

## 8. Milestones (build in this order)

Each milestone ends with a check Savage can do in plain English.

**M1 — Import and check files.**
- Import a slate from `~/Downloads`: SaberSim export, entries files, DFS Army CSV, standings zip, payout CSV.
- Validate headers and show a file report: rows, players, blend loaded or not, unmatched names, 0-byte files.
- *Check:* import the Week 2 main slate files. The report says 242 entries, 3 standings files, and 0 FPTS mismatches between SaberSim `Actual` and standings `FPTS`.

**M2 — Grader.**
- Grade any entries file against any standings file (sections 6.1, 6.2, 6.4).
- *Check:* golden tests G1–G4 match.

**M3 — Comparison screen and late-swap grader** (6.5, 6.6).
- *Check:* golden tests G5 and G7 match.

**M4 — Simulator.**
- Distributions, calibration table and correlations (5.1).
- *Check:* the calibration table on Weeks 1–2 reproduces the "20.8% above the 85th percentile" finding within ±2 points.

**M5 — Builder, showdown first, then classic** (5.2–5.4).
- Exports a DraftKings-ready entries CSV.
- *Check:* on ATL@GB, every generated lineup is legal (both teams, cap, CPT rules), and the file uploads to DraftKings' entry editor without errors. Savage does the upload by hand.

**M6 — Fill methods and simulated ROI** (5.3, 5.5).
- *Check:* grade DFS Lab's ATL@GB build against the real mini-MAX field next to SaberSim's entered 150 and DFS Army v4 (with the hindsight minimums removed).

**M7 — Season tracker.**
- Every new slate adds a row per method.

---

## 9. Golden tests (numbers already verified by hand in Savage's NFL DFS project)

The grader isn't trusted until these reproduce exactly.

**G1: Week 2 main, Play-Action $3 20-max** (contest 195648006, **317,082 entries**)
- Savage's final entered lineups: best rank **#2,406** (top 0.76%).
- Scored against the full Play-Action field, all **242** of his lineups have a best finish of top 0.27% (190.18 points).
- Counts: **4** in the top 1%, **14** in the top 5%, **74** in the top 20%. Median 38.7th percentile.

**G2: Week 2 main, fill files scored against the Play-Action field** (top 1% / 5% / 20%)

| file | top 1% / 5% / 20% |
|---|---|
| Unique Rank 3, pre-swap build | 5 / 21 / 83 |
| Portfolio+ | 8 / 36 / 87 |
| UR1 | 8 / 36 / 90 |
| UR2 | 7 / 33 / 85 |
| UR4 | 4 / 21 / 77 |
| UR5 | 5 / 27 / 77 |

**G3: Week 1 main, $3.5M Millionaire** (contest 193028206)
- **832,342 entries**, winner **273.98**.
- Lines: top 1% **209.0**, top 5% **189.6**, top 20% **166.3**.
- UR1 fill: 2 / 7 / 28 in the top 1% / 5% / 20%.

**G4: Week 1 main, $2.5M Millionaire** (contest 193028199)
- **27,777 entries**, winner **244.60**.
- Lines: top 1% **210.6**, top 5% **192.0**.

**G5: Week 3 TNF ATL@GB showdown**
- mini-MAX (contest 195943225): **237,812 entries**, winning score **152.1**.
- **Legal optimal** = CPT London / Bijan / Watson / Golden / B. Robinson Jr. / Hooper = **152.10** ($48,600).
- Savage's best entered lineup: **146.33**, rank **#1,170** in the mini-MAX.

**G6: DK scoring** (only if the tool computes points itself)
- Computed QB DK points match SaberSim `Actual` for all 27 QBs in Week 1 and all 32 in Week 2.

**G7: Week 2 late swap**
- 133 of 240 paired entries changed, net **−1,028.3** points (42 better, 90 worse).

---

## 10. What "similar or different to SaberSim / DFS Army" will mean

After each slate, the comparison screen answers three questions:
1. **Same inputs, different method:** did DFS Lab's build finish better or worse than SaberSim's and DFS Army's builds on the same slate and field?
2. **Where did they differ:** which players and stacks each build leaned into, and whether those leans paid.
3. **Is it real yet:** the running season table and the slate count, with the reminder that one slate's p-values are too generous and about 10+ slates are needed.

**Expected outcome, stated up front:**
- With the same projections, most of the difference will come from exposure choices and fill method, not the solver.
- Early weeks will swing a lot. Don't switch the money to DFS Lab until it has beaten both tools over a real sample of slates, forward-tested without being entered.

---

## 11. Weekly routine once it's built

**Before lock:**
1. Export the SaberSim player file with `My Proj` loaded.
2. Export the DFS Army lineups.
3. Save the War Room and Codex tags.
4. Import them all into DFS Lab. It freezes the pre-lock snapshot.
5. Build DFS Lab lineups.
6. Enter whichever build you choose, uploading the CSV to DraftKings by hand.

**After the games:**
1. Download the standings zip for each contest, plus the SaberSim post-game export.
2. Type in the payout tables.
3. Import them, and grade every build on the comparison screen.
4. Bring anything surprising back to the NFL DFS project for a second look.
