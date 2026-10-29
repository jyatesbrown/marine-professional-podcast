from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

Status = Literal["draft", "validated", "sample_rendered", "rendering", "rendered", "approved", "published"]


class Turn(BaseModel):
    speaker: str
    text: str
    section: Optional[str] = None

    @field_validator("text")
    @classmethod
    def _strip(cls, v: str) -> str:
        return " ".join(v.split())


class CostRecord(BaseModel):
    estimated_credits: Optional[int] = None
    estimated_usd: Optional[float] = None
    actual_credits: Optional[int] = None
    actual_usd: Optional[float] = None


class Episode(BaseModel):
    number: int
    title: str
    slug: str
    track: str
    subject: str
    target_minutes: float = 15
    learning_objectives: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    review_questions: list[str] = Field(default_factory=list)
    pronunciation_notes: list[str] = Field(default_factory=list)
    status: Status = "draft"
    audio_path: Optional[str] = None
    cost: CostRecord = Field(default_factory=CostRecord)
    dialogue: list[Turn]

    @property
    def speakers(self) -> list[str]:
        seen: list[str] = []
        for t in self.dialogue:
            if t.speaker not in seen:
                seen.append(t.speaker)
        return seen

    @property
    def spoken_chars(self) -> int:
        return sum(len(t.text) for t in self.dialogue)


class EpisodeError(Exception):
    pass


def load_episode(path: str | Path) -> Episode:
    p = Path(path)
    if p.is_dir():
        p = p / "episode.yaml"
    if not p.exists():
        raise EpisodeError(f"Episode file not found: {p}")
    data = yaml.safe_load(p.read_text()) or {}
    for t in data.get("dialogue") or []:
        if isinstance(t, dict) and "speaker" in t:
            t["speaker"] = str(t["speaker"]).strip().lower()
    return Episode.model_validate(data)


def save_episode(ep: Episode, path: str | Path) -> Path:
    p = Path(path)
    if p.is_dir() or p.suffix == "":
        p.mkdir(parents=True, exist_ok=True)
        p = p / "episode.yaml"
    data = ep.model_dump(mode="json")
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100))
    return p


_TAG = re.compile(r"\[[^\]]*\]")


def validate_episode(ep: Episode, voice_names: list[str]) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors block generation."""
    errors: list[str] = []
    warnings: list[str] = []
    if not ep.dialogue:
        errors.append("Episode has no dialogue.")
    unknown = sorted({t.speaker for t in ep.dialogue} - set(voice_names))
    if unknown:
        errors.append(f"Speakers without a configured voice: {unknown} (configured: {voice_names})")
    for i, t in enumerate(ep.dialogue):
        if not t.text.strip():
            errors.append(f"Turn {i + 1} ({t.speaker}) is empty.")
        if re.match(r"^\s*[A-Z][A-Za-z ]{1,20}:\s", t.text):
            warnings.append(f"Turn {i + 1} text starts with a speaker label: {t.text[:40]!r}")
        if t.text.count("[") != t.text.count("]"):
            warnings.append(f"Turn {i + 1} has unbalanced [audio tag] brackets.")
    for i in range(1, len(ep.dialogue)):
        a, b = ep.dialogue[i - 1], ep.dialogue[i]
        if a.text.strip() and a.text.strip() == b.text.strip():
            errors.append(f"Turns {i} and {i + 1} are identical (accidental repetition?).")
        if a.speaker == b.speaker:
            warnings.append(f"Turns {i} and {i + 1} are consecutive turns by {a.speaker}.")
    minutes = estimate_minutes(ep)
    if ep.target_minutes and not (0.6 * ep.target_minutes <= minutes <= 1.4 * ep.target_minutes):
        warnings.append(
            f"Estimated spoken length {minutes:.1f} min is far from target {ep.target_minutes:g} min."
        )
    return errors, warnings


SPOKEN_CHARS_PER_MINUTE = 900  # ~150 words/min conversational pace, ~6 chars/word incl. spaces


def estimate_minutes(ep: Episode) -> float:
    spoken = sum(len(_TAG.sub("", t.text)) for t in ep.dialogue)
    return spoken / SPOKEN_CHARS_PER_MINUTE
