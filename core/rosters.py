"""DraftKings roster layouts (SPEC section 4)."""

from collections import Counter

CLASSIC = "classic"
SHOWDOWN = "showdown"

# Column order DraftKings uses in entries files and lineup exports.
SLOTS = {
    CLASSIC: ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"],
    SHOWDOWN: ["CPT", "FLEX", "FLEX", "FLEX", "FLEX", "FLEX"],
}

# Position tags that appear inside a standings-file lineup string.
LINEUP_TAGS = ("QB", "RB", "WR", "TE", "FLEX", "DST", "CPT")

SALARY_CAP = 50_000


def format_for_slots(slots):
    """Return CLASSIC/SHOWDOWN if `slots` is exactly one of the layouts, else None."""
    for fmt, layout in SLOTS.items():
        if list(slots) == layout:
            return fmt
    return None


def format_for_tags(tags):
    """Match a standings lineup's tags (any order) to a layout, else None."""
    counts = Counter(tags)
    for fmt, layout in SLOTS.items():
        if counts == Counter(layout):
            return fmt
    return None
