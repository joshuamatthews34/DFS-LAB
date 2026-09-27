"""Payout table typed in by Savage (SPEC 3.5): rank_from, rank_to, prize."""

import csv

import pandas as pd

from ..io_utils import FileProblem, clean_header, open_text, parse_money_cents


def parse(path, contest_id):
    if not contest_id:
        raise FileProblem("Name the payout file after its contest ID, e.g. payouts-195648006.csv, "
                          "so DFS Lab knows which contest it belongs to.")
    with open_text(path) as f:
        rows = list(csv.reader(f))
    header = [h.lower() for h in clean_header(rows[0])]
    out = []
    for line_no, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        rec = dict(zip(header, row))
        try:
            lo, hi = int(rec["rank_from"]), int(rec["rank_to"])
            prize = parse_money_cents(rec["prize"])
        except (KeyError, ValueError):
            raise FileProblem(f"Payout file row {line_no} isn't 'rank_from, rank_to, prize' numbers: {row}") from None
        if lo < 1 or hi < lo:
            raise FileProblem(f"Payout file row {line_no}: rank_from {lo} / rank_to {hi} don't make sense.")
        out.append((lo, hi, prize))
    if not out:
        raise FileProblem("Payout file has no rows.")
    out.sort()
    for (a_lo, a_hi, _), (b_lo, _, _) in zip(out, out[1:]):
        if b_lo <= a_hi:
            raise FileProblem(f"Payout ranks overlap: {a_lo}-{a_hi} and a row starting at {b_lo}.")
        if b_lo != a_hi + 1:
            raise FileProblem(f"Payout ranks have a gap between {a_hi} and {b_lo}.")
    if out[0][0] != 1:
        raise FileProblem("Payout table must start at rank 1.")
    return pd.DataFrame(out, columns=["rank_from", "rank_to", "prize_cents"])
