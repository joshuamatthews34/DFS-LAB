"""Settings Savage changes on screen (e.g. the simulator's tail widths), kept in dfs_lab.db."""

import json

from . import db, slate

DEFAULTS = {
    "sim.lower_tail": 1.0,
    "sim.upper_tail": 1.0,
    "sim.n_sims": 10_000,
    "sim.seed": 2026,
}


def get(key, root=None):
    conn = db.connect(slate.db_path(root))
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return json.loads(row[0]) if row else DEFAULTS.get(key)


def put(key, value, root=None):
    conn = db.connect(slate.db_path(root))
    try:
        with conn:
            conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))
    finally:
        conn.close()
