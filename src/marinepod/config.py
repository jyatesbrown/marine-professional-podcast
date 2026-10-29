from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

OUTPUT_FORMATS = {
    ("mp3", "standard"): "mp3_44100_128",
    ("mp3", "high"): "mp3_44100_192",
}
DIALOGUE_MODELS = ("eleven_v4", "eleven_v3")
HARD_MAX_CHARS_PER_REQUEST = 2000


class Podcast(BaseModel):
    title: str
    target_minutes: float = 15


class Voice(BaseModel):
    voice_id: str = ""
    role: str = ""


class Audio(BaseModel):
    format: Literal["mp3"] = "mp3"
    quality: Literal["standard", "high"] = "high"
    gap_ms: int = Field(350, ge=0, le=3000)
    loudness_lufs: float = Field(-16, ge=-30, le=-9)

    @property
    def output_format(self) -> str:
        return OUTPUT_FORMATS[(self.format, self.quality)]


class Settings(BaseModel):
    stability: Optional[float] = Field(0.5, ge=0, le=1)
    similarity: Optional[float] = Field(0.75, ge=0, le=1)


class Generation(BaseModel):
    model_id: str = "eleven_v4"
    language_code: Optional[str] = "en"
    max_chars_per_request: int = Field(1800, ge=200, le=HARD_MAX_CHARS_PER_REQUEST)
    continuity: Literal["previous_text", "request_ids", "none"] = "previous_text"
    seed: Optional[int] = None
    settings: Settings = Settings()

    @field_validator("model_id")
    @classmethod
    def _dialogue_model(cls, v: str) -> str:
        if v not in DIALOGUE_MODELS:
            raise ValueError(f"Text to Dialogue supports {DIALOGUE_MODELS}, got {v!r}")
        return v


class Limits(BaseModel):
    max_credits_per_run: int = 25000
    max_credits_per_month: int = 120000
    max_segments_per_run: int = 40


class Cost(BaseModel):
    plan: str = "creator"
    limits: Limits = Limits()


class Config(BaseModel):
    podcast: Podcast
    voices: dict[str, Voice]
    audio: Audio = Audio()
    generation: Generation = Generation()
    cost: Cost = Cost()

    def voice_map(self, require_ids: bool = True) -> dict[str, str]:
        missing = [name for name, v in self.voices.items() if not v.voice_id.strip()]
        if require_ids and missing:
            raise ConfigError(
                "No voice_id configured for: " + ", ".join(missing)
                + ". Paste the voice IDs you chose into config.yaml (voices.<name>.voice_id)."
            )
        return {name: v.voice_id.strip() for name, v in self.voices.items()}


class ConfigError(Exception):
    pass


def load_config(path: str | Path = "config.yaml") -> Config:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Config file not found: {p}")
    data = yaml.safe_load(p.read_text()) or {}
    data["voices"] = {k.lower(): v for k, v in (data.get("voices") or {}).items()}
    return Config.model_validate(data)
