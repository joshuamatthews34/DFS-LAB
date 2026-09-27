"""Work out what kind of file something is from its header row (SPEC section 3).

Anything that doesn't match a known header is reported as unknown, never guessed.
"""

import json
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import rosters
from .io_utils import contest_id_from_name, read_header, UNREADABLE_HINT

SABERSIM = "sabersim"
DK_ENTRIES = "dk_entries"
LINEUPS = "lineups"
STANDINGS = "standings"
PAYOUTS = "payouts"
WARROOM = "warroom"
EMPTY = "empty"
UNREADABLE = "unreadable"
UNKNOWN = "unknown"

LABELS = {
    SABERSIM: "SaberSim player export",
    DK_ENTRIES: "DraftKings entries file",
    LINEUPS: "Lineup export (DFS Army)",
    STANDINGS: "DraftKings contest standings",
    PAYOUTS: "Payout table",
    WARROOM: "War Room tags",
    EMPTY: "Empty file (0 bytes)",
    UNREADABLE: "Can't be read",
    UNKNOWN: "Not recognized",
}

ENTRIES_LEFT = ["Entry ID", "Contest Name", "Contest ID", "Entry Fee"]
STANDINGS_LEFT = ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup"]
PAYOUT_HEADER = ["rank_from", "rank_to", "prize"]

SUPPORTED_SUFFIXES = {".csv", ".zip", ".json"}


@dataclass
class Detected:
    path: Path
    kind: str
    reason: str = ""
    member: str = None       # CSV inside a zip, when the file is a zip
    fmt: str = None          # classic / showdown when the header tells us
    contest_id: str = None

    @property
    def label(self):
        return LABELS[self.kind]


def detect(path):
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        return Detected(path, UNREADABLE, UNREADABLE_HINT)
    if size == 0:
        return Detected(path, EMPTY, _empty_reason(path))

    suffix = path.suffix.lower()
    try:
        if suffix == ".zip":
            return _detect_zip(path)
        if suffix == ".json":
            return _detect_json(path)
        if suffix == ".csv":
            return _detect_csv(path, read_header(path))
    except (OSError, PermissionError):
        return Detected(path, UNREADABLE, UNREADABLE_HINT)
    return Detected(path, UNKNOWN, f"DFS Lab reads .csv, .zip and .json files, not {suffix or 'files without an extension'}.")


def _empty_reason(path):
    if "standings" in path.name.lower():
        return ("DraftKings served an empty (0-byte) file. This happens with its largest contests. "
                "Try downloading the standings again later.")
    return "The file is empty (0 bytes). Download or export it again."


def _detect_zip(path):
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return Detected(path, UNREADABLE, "The zip file is damaged or only partly downloaded. Download it again.")
    with zf:
        csvs = [i for i in zf.infolist() if i.filename.lower().endswith(".csv") and not i.filename.startswith("__MACOSX")]
    if not csvs:
        return Detected(path, UNKNOWN, "The zip has no CSV inside.")
    if len(csvs) > 1:
        return Detected(path, UNKNOWN, "The zip has more than one CSV inside; expected one contest-standings file.")
    info = csvs[0]
    if info.file_size == 0:
        return Detected(path, EMPTY, _empty_reason(Path(info.filename)), member=info.filename)
    det = _detect_csv(path, read_header(path, info.filename))
    det.member = info.filename
    if det.kind == STANDINGS:
        det.contest_id = contest_id_from_name(info.filename) or contest_id_from_name(path.name)
    return det


def _detect_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return Detected(path, UNKNOWN, "The JSON file couldn't be parsed.")
    if isinstance(data, dict) and data and all(isinstance(k, str) for k in data):
        return Detected(path, WARROOM)
    return Detected(path, UNKNOWN, "The JSON isn't a War Room tag board ({player name: tag, ...}).")


def _detect_csv(path, header):
    if header[:6] == STANDINGS_LEFT:
        return Detected(path, STANDINGS, contest_id=contest_id_from_name(path.name))
    if header[:4] == ENTRIES_LEFT:
        for fmt, slots in rosters.SLOTS.items():
            if header[4:4 + len(slots)] == slots:
                return Detected(path, DK_ENTRIES, fmt=fmt)
        return Detected(path, UNKNOWN, "Looks like a DraftKings entries file, but the roster columns aren't classic or showdown.")
    for fmt, slots in rosters.SLOTS.items():
        if header[:len(slots)] == slots:   # extra columns to the right (projections etc.) are ignored
            return Detected(path, LINEUPS, fmt=fmt)
    if [h.lower() for h in header] == PAYOUT_HEADER:
        return Detected(path, PAYOUTS, contest_id=contest_id_from_name(path.name))
    if "DFS ID" in header and "SS Proj" in header:
        return Detected(path, SABERSIM)
    shown = ", ".join(header[:6]) or "(blank)"
    return Detected(path, UNKNOWN, f"The header row doesn't match any file DFS Lab knows. It starts: {shown}")


def scan_folder(folder, max_age_days=None, now=None):
    """Detect every supported file directly inside `folder`, newest first."""
    folder = Path(folder).expanduser()
    now = now or time.time()
    found = []
    for p in folder.iterdir():
        if not p.is_file() or p.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = now
        if max_age_days is not None and now - mtime > max_age_days * 86400:
            continue
        found.append((mtime, detect(p)))
    found.sort(key=lambda t: t[0], reverse=True)
    return [(det, mtime) for mtime, det in found]
