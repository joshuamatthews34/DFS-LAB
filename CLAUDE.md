# DFS Lab: notes for Claude Code

- SPEC.md is the source of truth. Build one milestone at a time and stop when its check is ready.
- Savage has never coded. Every milestone ends with a plain-English check he can run, and README.md says how.
- Never make up a number. On a missing file or mismatched column, stop and say exactly what's wrong (raise `core.io_utils.FileProblem` with a plain-English message).
- Never automate anything on DraftKings. The tool only reads and writes CSVs.
- No hindsight: build code must never read `player_results`, `standings_players`, `Actual`, `Live Proj`, `FPTS` or `%Drafted` (SPEC 7).
  The synthetic field (core/fieldmodel.py) learns salary/stack habits only from *other* slates' standings. The only
  build that reads its own slate's standings is an explicit "real field" backtest, and it is marked hindsight.
- Real contest files never go in git (the repo is public). Tests use the fake files in `tests/builders.py`.
- Layout: `core/` (no UI code), `app/app.py` (Streamlit), `tests/` (pytest). Run everything with `./run.sh`; tests with `./run.sh test` or `python -m pytest`.
