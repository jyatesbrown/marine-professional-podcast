from __future__ import annotations

import re
from pathlib import Path

from .episode import Episode, Turn

_LABEL = re.compile(r"^\s*(?:\*\*)?([A-Z][A-Za-z]{1,20})(?:\*\*)?\s*[:：](?:\*\*)?\s*(.*)$")
_HEADING = re.compile(r"^\s*#{1,6}\s+(.*?)\s*#*\s*$|^\s*\[(?:SEGMENT|SECTION)[^\]]*[:\-]\s*(.*?)\]\s*$", re.I)
_STAGE = re.compile(r"^\s*[\(\[].*[\)\]]\s*$")


def parse_script(text: str, speakers: list[str]) -> tuple[list[Turn], list[str]]:
    """Parse 'NAME: line' scripts (ChatGPT style). Returns (turns, notes about skipped lines).

    Continuation lines without a label are appended to the current turn. Markdown headings become
    section names. Lines that are only a bracketed/parenthesised stage direction are skipped and
    reported, because they would otherwise be spoken aloud.
    """
    wanted = {s.lower() for s in speakers}
    turns: list[Turn] = []
    notes: list[str] = []
    section = None
    has_headings = any(_HEADING.match(raw.strip()) for raw in text.splitlines())
    block = 1
    pending_break = False
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            pending_break = bool(turns)
            continue
        if set(line) <= {"-", "*", "_", "="}:
            continue
        h = _HEADING.match(line)
        if h:
            section = (h.group(1) or h.group(2) or "").strip() or section
            continue
        if not has_headings:
            # Scripts without headings: blank-line-separated blocks become numbered sections.
            if pending_break:
                block += 1
            pending_break = False
            section = f"Part {block}"
        m = _LABEL.match(line)
        if m and m.group(1).lower() in wanted:
            body = m.group(2).strip()
            turns.append(Turn(speaker=m.group(1).lower(), text=body, section=section))
            continue
        if m and m.group(1).lower() not in wanted and m.group(1).isupper():
            notes.append(f"line {n}: unknown speaker {m.group(1)!r}, skipped: {line[:60]!r}")
            continue
        if _STAGE.match(line):
            notes.append(f"line {n}: stage direction skipped: {line[:60]!r}")
            continue
        if turns:
            turns[-1].text = f"{turns[-1].text} {line}".strip()
        else:
            notes.append(f"line {n}: text before first speaker label skipped: {line[:60]!r}")
    for t in turns:
        t.text = re.sub(r"\*\*|__", "", t.text).strip()
    return [t for t in turns if t.text], notes


def import_script(path: str | Path, speakers: list[str], **meta) -> tuple[Episode, list[str]]:
    turns, notes = parse_script(Path(path).read_text(), speakers)
    return Episode(dialogue=turns, **meta), notes
