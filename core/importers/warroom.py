"""War Room exposure board (SPEC 3.6).

{"Player Name": "OVER", ...} or, with caps,
{"Player Name": {"tag": "UNDER", "min": 0, "max": 12}, ...}
"""

import json

import pandas as pd

from ..io_utils import FileProblem
from ..names import normalize_name

TAGS = ("OVER", "WITH", "UNDER", "FADE")


def parse(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = []
    for player, value in data.items():
        cap_min = cap_max = None
        if isinstance(value, dict):
            tag = value.get("tag")
            cap_min, cap_max = value.get("min"), value.get("max")
        else:
            tag = value
        tag = str(tag).strip().upper() if tag is not None else ""
        if tag not in TAGS:
            raise FileProblem(f"War Room tag for '{player}' is '{tag}'; it must be one of {', '.join(TAGS)}.")
        for label, cap in (("min", cap_min), ("max", cap_max)):
            if cap is not None and not (isinstance(cap, (int, float)) and 0 <= cap <= 100):
                raise FileProblem(f"War Room {label} cap for '{player}' must be a number from 0 to 100.")
        rows.append({"player": player.strip(), "name_key": normalize_name(player), "tag": tag,
                     "cap_min": cap_min, "cap_max": cap_max})
    return pd.DataFrame(rows)
