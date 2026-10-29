from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from .episode import Turn


@dataclass
class Input:
    speaker: str
    text: str
    turn_index: int


@dataclass
class Segment:
    index: int
    inputs: list[Input] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return sum(len(i.text) for i in self.inputs)

    @property
    def text(self) -> str:
        return " ".join(i.text for i in self.inputs)

    def fingerprint(self, voice_map: dict[str, str], params: dict) -> str:
        payload = {
            "inputs": [(i.speaker, voice_map.get(i.speaker, ""), i.text) for i in self.inputs],
            "params": params,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[\"'(\[A-Z0-9])")


def _split_long_text(text: str, limit: int) -> list[str]:
    """Split one long turn at sentence boundaries (falling back to clause, then word, boundaries)."""
    if len(text) <= limit:
        return [text]
    pieces = _SENTENCE_END.split(text)
    out: list[str] = []
    cur = ""
    for piece in pieces:
        if len(piece) > limit:
            sub = re.split(r"(?<=[,;:—])\s+", piece)
            if any(len(s) > limit for s in sub):
                sub = piece.split(" ")
            for s in sub:
                cur = _append(cur, s, limit, out)
            continue
        cur = _append(cur, piece, limit, out)
    if cur:
        out.append(cur)
    return out


def _append(cur: str, piece: str, limit: int, out: list[str]) -> str:
    candidate = f"{cur} {piece}" if cur else piece
    if len(candidate) <= limit:
        return candidate
    if cur:
        out.append(cur)
    return piece


def segment_dialogue(turns: list[Turn], max_chars: int) -> list[Segment]:
    """Pack consecutive turns into requests of at most `max_chars` characters.

    Turns are never reordered. A turn is only split (at sentence boundaries) when it alone exceeds
    the limit. A new segment is preferred at section boundaries once the current one is half full,
    so joins fall on natural topic transitions.
    """
    inputs: list[Input] = []
    sections: list[str | None] = []
    for ti, t in enumerate(turns):
        for part in _split_long_text(t.text.strip(), max_chars):
            inputs.append(Input(t.speaker, part, ti))
            sections.append(t.section)

    segments: list[Segment] = []
    cur = Segment(0)
    prev_section = None
    for inp, section in zip(inputs, sections):
        new_section = section is not None and section != prev_section and cur.inputs
        too_big = cur.chars + len(inp.text) > max_chars
        if cur.inputs and (too_big or (new_section and cur.chars >= max_chars // 2)):
            segments.append(cur)
            cur = Segment(len(segments))
        cur.inputs.append(inp)
        prev_section = section
    if cur.inputs:
        segments.append(cur)
    return segments
