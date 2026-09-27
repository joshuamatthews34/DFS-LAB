"""The file report shown after an import (SPEC M1)."""

from dataclasses import asdict, dataclass, field


@dataclass
class FileReport:
    name: str
    kind: str
    label: str
    bytes: int
    sha256: str = ""
    status: str = "ok"            # ok / warning / error / ignored
    summary: str = ""
    problems: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def problem(self, text):
        self.problems.append(text)
        self.status = "error"

    def warn(self, text):
        self.warnings.append(text)
        if self.status == "ok":
            self.status = "warning"


@dataclass
class Report:
    slate_id: str
    generated_at: str
    fmt: str = None
    files: list = field(default_factory=list)

    players: int = 0
    sabersim_files: int = 0
    blend_loaded: object = None
    entries: int = 0                  # unique Entry IDs with a full lineup
    entries_files: int = 0
    reservations: int = 0
    lineup_files: int = 0
    lineups: int = 0
    standings_files: int = 0
    contests: list = field(default_factory=list)
    payout_contests: list = field(default_factory=list)

    fpts_checked: bool = False
    fpts_note: str = ""
    fpts_compared: int = 0
    fpts_mismatches: list = field(default_factory=list)
    unmatched_names: dict = field(default_factory=dict)
    unknown_ids: dict = field(default_factory=dict)
    zero_byte_files: list = field(default_factory=list)

    problems: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def headline(self):
        fpts = (f"{len(self.fpts_mismatches)} FPTS mismatch{'es' if len(self.fpts_mismatches) != 1 else ''}"
                if self.fpts_checked else "FPTS check not run")
        return (f"{self.entries:,} entr{'y' if self.entries == 1 else 'ies'} · {self.standings_files} standings "
                f"file{'s' if self.standings_files != 1 else ''} · {fpts}")

    @property
    def ok(self):
        return not self.problems and not any(f.status == "error" for f in self.files)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d["files"] = [FileReport(**f) for f in d.get("files", [])]
        return cls(**d)

    def to_text(self):
        blend = {True: "loaded", False: "NOT loaded", None: "unknown (My Proj blank)"}[self.blend_loaded]
        lines = [
            f"DFS Lab import report: {self.slate_id}  ({self.generated_at})",
            "",
            self.headline(),
            "",
            f"Slate type: {self.fmt or 'unknown'}",
            f"Players (SaberSim): {self.players:,} from {self.sabersim_files} export(s); blend {blend}",
            f"Your entries: {self.entries:,} from {self.entries_files} entries file(s)"
            + (f"; {self.reservations} blank reservation(s) skipped" if self.reservations else ""),
            f"Lineup exports (DFS Army etc.): {self.lineups:,} lineups in {self.lineup_files} file(s)",
            f"Standings files: {self.standings_files}",
        ]
        for c in self.contests:
            lines.append(f"  - contest {c['contest_id']} {c.get('contest_name') or ''}: {c['entries']:,} field lineups read, "
                         f"{c['skipped']:,} skipped, winning score {c['top_score']}, "
                         f"payouts {'loaded' if c['has_payouts'] else 'not loaded (ROI not available)'}")
        lines.append(f"FPTS check: {self.fpts_note}")
        for m in self.fpts_mismatches[:50]:
            lines.append(f"  - {m['player']}: standings {m['standings_fpts']} vs SaberSim {m['sabersim_actual']}")
        if self.zero_byte_files:
            lines.append("0-byte files: " + ", ".join(self.zero_byte_files))
        for source, names in self.unmatched_names.items():
            if names:
                lines.append(f"Unmatched names ({source}): " + ", ".join(names))
        for source, ids in self.unknown_ids.items():
            if ids:
                lines.append(f"DFS IDs not in the SaberSim export ({source}): " + ", ".join(map(str, ids)))
        problems = self.problems + [f"{f.name}: {p}" for f in self.files for p in f.problems]
        if problems:
            lines += ["", "PROBLEMS (fix these before trusting any numbers):"] + [f"  ! {p}" for p in problems]
        if self.warnings:
            lines += ["", "Warnings:"] + [f"  * {w}" for w in self.warnings]
        lines += ["", "Files:"]
        for f in self.files:
            lines.append(f"  [{f.status}] {f.name} - {f.label}" + (f": {f.summary}" if f.summary else ""))
            lines += [f"      ! {p}" for p in f.problems] + [f"      * {w}" for w in f.warnings]
        return "\n".join(lines)
