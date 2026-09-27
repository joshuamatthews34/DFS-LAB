"""SQLite storage (dfs_lab.db).

Post-game numbers live in their own tables (player_results, standings_players)
so build code can be kept away from them (SPEC section 7).
"""

import sqlite3

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS slates (
    slate_id TEXT PRIMARY KEY, fmt TEXT, analyzed_at TEXT, report_json TEXT);
CREATE TABLE IF NOT EXISTS files (
    slate_id TEXT, file_name TEXT, kind TEXT, bytes INTEGER, sha256 TEXT, status TEXT,
    PRIMARY KEY (slate_id, file_name));
CREATE TABLE IF NOT EXISTS players (
    slate_id TEXT, source_file TEXT, dfs_id INTEGER, name TEXT, name_key TEXT, pos TEXT,
    team TEXT, opp TEXT, status TEXT, roster_slot TEXT, salary REAL, ss_proj REAL,
    my_proj REAL, value REAL, my_own REAL, adj_own REAL, min_exp REAL, max_exp REAL,
    saber_team REAL, saber_total REAL, dk_points REAL, dk_std REAL, dk_25 REAL, dk_50 REAL,
    dk_75 REAL, dk_85 REAL, dk_95 REAL, dk_99 REAL);
CREATE TABLE IF NOT EXISTS player_results (
    slate_id TEXT, source_file TEXT, dfs_id INTEGER, actual REAL, live_proj REAL);
CREATE TABLE IF NOT EXISTS dk_pool (
    slate_id TEXT, source_file TEXT, dfs_id INTEGER, name TEXT, pos TEXT,
    roster_position TEXT, salary INTEGER, game_info TEXT, team TEXT);
CREATE TABLE IF NOT EXISTS entries (
    slate_id TEXT, source_file TEXT, entry_id TEXT, contest_id TEXT, contest_name TEXT,
    fee_cents INTEGER, fmt TEXT, player_ids TEXT);
CREATE TABLE IF NOT EXISTS lineups (
    slate_id TEXT, source_file TEXT, idx INTEGER, fmt TEXT, player_ids TEXT);
CREATE TABLE IF NOT EXISTS contests (
    slate_id TEXT, contest_id TEXT, source_file TEXT, contest_name TEXT, fmt TEXT,
    entries INTEGER, skipped INTEGER, top_score REAL);
CREATE TABLE IF NOT EXISTS standings_players (
    slate_id TEXT, contest_id TEXT, player TEXT, name_key TEXT, roster_position TEXT,
    pct_drafted REAL, fpts REAL);
CREATE TABLE IF NOT EXISTS payouts (
    slate_id TEXT, contest_id TEXT, rank_from INTEGER, rank_to INTEGER, prize_cents INTEGER);
CREATE TABLE IF NOT EXISTS season_results (
    slate_id TEXT, contest_id TEXT, build_key TEXT, method TEXT, name TEXT, refill INTEGER,
    lineups INTEGER, top1 INTEGER, top5 INTEGER, cashed INTEGER, won REAL, fees REAL, graded_at TEXT,
    PRIMARY KEY (slate_id, contest_id, build_key));
CREATE TABLE IF NOT EXISTS warroom_tags (
    slate_id TEXT, source_file TEXT, player TEXT, name_key TEXT, tag TEXT,
    cap_min REAL, cap_max REAL, dfs_id INTEGER);
"""

# Re-importing a slate replaces these. season_results is kept: it's the running record.
SLATE_TABLES = ["files", "players", "player_results", "dk_pool", "entries", "lineups",
                "contests", "standings_players", "payouts", "warroom_tags"]


def connect(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def replace_slate(conn, slate_id, fmt, analyzed_at, report_json, tables):
    """Swap in a slate's rows in one transaction. `tables` maps table name -> DataFrame."""
    with conn:
        for t in SLATE_TABLES:
            conn.execute(f"DELETE FROM {t} WHERE slate_id = ?", (slate_id,))
        conn.execute("INSERT OR REPLACE INTO slates VALUES (?, ?, ?, ?)",
                     (slate_id, fmt, analyzed_at, report_json))
        for table, df in tables.items():
            if df is None or df.empty:
                continue
            df = df.assign(slate_id=slate_id)
            cols = [c for c in df.columns]
            sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
            conn.executemany(sql, [tuple(_plain(v) for v in row) for row in df.itertuples(index=False)])


def _plain(v):
    """numpy/pandas scalars -> Python values sqlite understands; NaN/NA -> NULL."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        v = v.item()
    return v
