"""File helpers shared by the importers."""

import codecs
import contextlib
import csv
import hashlib
import io
import re
import zipfile
from pathlib import Path


class FileProblem(Exception):
    """A problem with an input file, worded for Savage. Imports stop on these."""


UNREADABLE_HINT = (
    "The file couldn't be read. Files unzipped on a Mac are sometimes hard links: "
    "right-click the file in Finder, choose Duplicate, and import the copy."
)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def contest_id_from_name(name):
    """First run of 6+ digits in a file name, e.g. contest-standings-195648006.zip."""
    m = re.search(r"(\d{6,})", Path(name).name)
    return m.group(1) if m else None


def _open_binary(path, member=None):
    if member is None:
        return open(path, "rb")
    return zipfile.ZipFile(path).open(member)


def _guess_encoding(path, member=None):
    """UTF-8 (with or without a byte-order mark) unless the start of the file says otherwise."""
    with _open_binary(path, member) as f:
        sample = f.read(1 << 20)
    try:
        codecs.getincrementaldecoder("utf-8")().decode(sample, final=False)
        return "utf-8-sig"
    except UnicodeDecodeError:
        return "cp1252"


@contextlib.contextmanager
def open_text(path, member=None):
    """Open a CSV (or a CSV inside a zip) as text, handling the byte-order mark."""
    encoding = _guess_encoding(path, member)
    raw = _open_binary(path, member)
    try:
        yield io.TextIOWrapper(raw, encoding=encoding, newline="")
    finally:
        raw.close()


def clean_header(cols):
    """Strip byte-order marks, stray backslashes and surrounding spaces from column names."""
    return [str(c).replace("﻿", "").replace("\\", "").strip() for c in cols]


def read_header(path, member=None):
    with open_text(path, member) as f:
        row = next(csv.reader(f), [])
    header = clean_header(row)
    while header and header[-1] == "":
        header.pop()
    return header


def parse_money_cents(text):
    """'$3' -> 300, '$1,000.50' -> 100050. Raises ValueError on anything else."""
    s = str(text).strip().replace("$", "").replace(",", "")
    if not s:
        raise ValueError("blank amount")
    return int(round(float(s) * 100))
