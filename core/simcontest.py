"""Simulated contests: your lineups against a field model, in the same simulated slates (SPEC 5.3, 5.5).

Scores are kept in whole half-hundredths of a point (a captain's 1.5x can end in a half), so
identical lineups tie exactly, as duplicates do on DraftKings. A field sample of F lineups stands
for N entries (each counts N/F). Your own lineups share the field with each other, and tied
lineups split the prizes of the ranks they share.

Fill values (used by the builder):
  ROIValue  - fill method 1: expected prize the lineup adds to the set, counting what it takes from
              your other lineups when it finishes above them.
  Top1Value - fill method 3: simulated slates in which the lineup finishes top 1% and none of the
              lineups already chosen does.
"""

import math
from dataclasses import dataclass

import numpy as np

TOP_SHARE = 0.01
SHIFT = 1 << 20                        # makes every score positive for the row trick in _count
ROW = 1 << 22                          # larger than any shifted score


@dataclass
class ContestTerms:
    contest_id: str
    name: str = ""
    size: int = None                   # entries in the contest
    fee: float = None                  # dollars per entry
    prizes: np.ndarray = None          # dollars for rank 1, 2, ...

    @property
    def last_paid(self):
        return int(np.nonzero(self.prizes)[0].max()) + 1 if self.prizes is not None and self.prizes.any() else 0


def player_cents(points):
    """Simulated DraftKings points (sims x players) in whole hundredths."""
    return np.rint(np.asarray(points, dtype=np.float64) * 100).astype(np.int32)


def score(cents, cols, mult2):
    """Half-hundredth scores (lineups x sims) for lineups given as sim columns and 2x multipliers
    (2 for a player, 3 for a captain)."""
    cols = np.asarray(cols)
    out = np.empty((len(cols), cents.shape[0]), dtype=np.int32)
    step = max(1, 3_000_000 // max(1, cents.shape[0] * cols.shape[1]))
    for a in range(0, len(cols), step):
        g = cents[:, cols[a:a + step]]                               # sims x l x k
        out[a:a + step] = (g * np.asarray(mult2[a:a + step], dtype=np.int32)[None]).sum(axis=2).T
    return out


def _count(sorted_rows, queries, chunk=400):
    """sorted_rows: sims x D, ascending. queries: L x sims. Returns (strictly higher, equal), L x sims."""
    sims, depth = sorted_rows.shape
    offs = np.arange(sims, dtype=np.int64) * ROW
    flat = (sorted_rows.astype(np.int64) + SHIFT + offs[:, None]).ravel()
    start = np.arange(sims, dtype=np.int64) * depth
    higher = np.empty(queries.shape, dtype=np.int32)
    equal = np.empty(queries.shape, dtype=np.int32)
    for a in range(0, len(queries), chunk):
        q = queries[a:a + chunk].astype(np.int64) + SHIFT + offs[None, :]
        right = np.searchsorted(flat, q, side="right") - start
        left = np.searchsorted(flat, q, side="left") - start
        higher[a:a + chunk] = depth - right
        equal[a:a + chunk] = right - left
    return higher, equal


class Scorer:
    """The field's scores in every simulated slate (only as deep as prizes and the top 1% need)."""

    def __init__(self, cents, field_cols, field_mult2, terms, size=None):
        self.terms = terms
        self.sims = cents.shape[0]
        self.F = len(field_cols)
        self.size_known = bool(size)
        self.size = int(size or self.F)
        self.w = self.size / self.F
        depth = max(TOP_SHARE * self.size, terms.last_paid if terms.prizes is not None else 0)
        self.D = min(self.F, int(math.ceil(depth / self.w)) + 2)
        self.top = np.empty((self.sims, self.D), dtype=np.int32)
        step = max(1, 20_000_000 // max(1, self.F * np.asarray(field_cols).shape[1]))
        for a in range(0, self.sims, step):
            sc = score(cents[a:a + step], field_cols, field_mult2)       # F x chunk
            if self.D < self.F:
                sc = -np.partition(-sc, self.D - 1, axis=0)[:self.D]
            self.top[a:a + step] = np.sort(sc, axis=0).T
        self.cum = np.concatenate([[0.0], np.cumsum(terms.prizes)]) if terms.prizes is not None else None

    @property
    def has_prizes(self):
        return self.cum is not None and self.terms.fee is not None and self.size_known

    def against_field(self, S):
        """Field entries strictly above, and tied with, each score (L x sims), in contest entries."""
        h, e = _count(self.top, S)
        if self.D < self.F:
            beyond = (h == self.D) & (e == 0) & (S < self.top[None, :, 0])
            h = np.where(beyond, self.F, h)
        return (h * self.w).astype(np.float32), (e * self.w).astype(np.float32)

    def prize(self, h, t):
        """Average prize for ranks h+1 .. h+t: h entries above, t tied (counting this one)."""
        return (self._cum_at(h + t) - self._cum_at(h)) / t

    def _cum_at(self, x):
        """Total prize money for ranks 1..x, straight-line between whole ranks."""
        last = len(self.cum) - 1                                     # the last paid rank
        x = np.clip(np.asarray(x, dtype=np.float64), 0, last)
        if not last:
            return np.zeros(x.shape)
        i = np.minimum(x.astype(np.int64), last - 1)
        return self.cum[i] + (x - i) * (self.cum[i + 1] - self.cum[i])

    def top1(self, Hf):
        return Hf <= TOP_SHARE * self.size + 1e-6

    def evaluate(self, S):
        """Your set in the simulated contest. Returns per-lineup arrays and set-level numbers."""
        Hf, Tf = self.against_field(S)
        oh, oe = _count(np.sort(S.T, axis=1), S)                     # your other lineups (oe counts itself)
        hit = self.top1(Hf)
        out = {"top1": hit.mean(axis=1), "any_top1": float(hit.any(axis=0).mean())}
        if self.has_prizes:
            pr = self.prize(Hf + oh, Tf + oe)
            out["ev"] = pr.mean(axis=1)
            out["cash"] = (pr > 0).mean(axis=1)
        return out


class ROIValue:
    """Fill method 1: each lineup's expected prize given the field and your lineups chosen so far."""

    def __init__(self, scorer, S):
        self.sc, self.S = scorer, S
        self.Hf, Tf = scorer.against_field(S)
        self.t = Tf + 1
        self.alone = np.concatenate([scorer.prize(self.Hf[a:a + 500], self.t[a:a + 500]).mean(axis=1)
                                     for a in range(0, len(S), 500)])
        self.J, self.hJ, self.tJ, self.loss = [], None, None, None

    def bound(self, i):
        return float(self.alone[i])

    def secondary(self, i):
        return 0.0

    def exact(self, i):
        if not self.J:
            return float(self.alone[i])
        s = self.S[i]
        SJ = self.S[self.J]
        above = (SJ > s).sum(axis=0)
        mine = self.sc.prize(self.Hf[i] + above, self.t[i])
        return float((mine - (self.loss * (SJ < s)).sum(axis=0)).mean())

    def add(self, i):
        s = self.S[i]
        if self.J:
            SJ = self.S[self.J]
            h_new = self.Hf[i] + (SJ > s).sum(axis=0)
            self.hJ = np.vstack([self.hJ + (s > SJ), h_new])
            self.tJ = np.vstack([self.tJ, self.t[i]])
        else:
            self.hJ, self.tJ = self.Hf[i][None].astype(np.float64), self.t[i][None]
        self.J.append(i)
        # What each chosen lineup loses if one more lineup finishes above it.
        self.loss = self.sc.prize(self.hJ, self.tJ) - self.sc.prize(self.hJ + 1, self.tJ)


class Top1Value:
    """Fill method 3: new simulated slates where the set gets a top-1% finish."""

    def __init__(self, scorer, S):
        Hf, _ = scorer.against_field(S)
        self.hits = scorer.top1(Hf)
        self.total = self.hits.sum(axis=1)
        self.covered = np.zeros(S.shape[1], dtype=bool)

    def bound(self, i):
        return float(self.total[i])

    def secondary(self, i):
        return float(self.total[i])

    def exact(self, i):
        return float((self.hits[i] & ~self.covered).sum())

    def order(self):
        """Every candidate, best first: new top-1% slates, then top-1% slates overall."""
        gain = self.hits[:, ~self.covered].sum(axis=1)
        return np.lexsort((np.arange(len(gain)), -self.total, -gain))

    def add(self, i):
        self.covered |= self.hits[i]
