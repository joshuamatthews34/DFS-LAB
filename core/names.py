"""Player-name matching (SPEC section 4.4).

Lowercase, strip accents, remove . ' -, drop trailing suffixes
(jr sr ii iii iv v), collapse spaces, then apply the alias table.
Aliases live in core/aliases.csv so new ones can be added without code.
"""

import csv
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
ALIASES_FILE = Path(__file__).with_name("aliases.csv")

_PUNCT = re.compile(r"[.'\-’]")


def _basic(name):
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _PUNCT.sub("", s.lower())
    tokens = s.split()
    while len(tokens) > 1 and tokens[-1] in SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


@lru_cache(maxsize=1)
def _aliases():
    table = {}
    if ALIASES_FILE.exists():
        with ALIASES_FILE.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name, same_as = row.get("name"), row.get("same_as")
                if name and same_as:
                    table[_basic(name)] = _basic(same_as)
    return table


def normalize_name(name):
    """Matching key for a player name. Empty string for blank input."""
    if name is None or (isinstance(name, float) and name != name):
        return ""
    key = _basic(name)
    return _aliases().get(key, key)
