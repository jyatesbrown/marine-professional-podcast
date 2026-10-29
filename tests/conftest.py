from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest
import yaml

from marinepod.config import load_config
from marinepod.episode import Episode, Turn

FAKE_KEY = "sk_test_DO_NOT_LEAK_1234567890"


def make_mp3(seconds: float, freq: int = 440) -> bytes:
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         f"sine=frequency={freq}:duration={seconds:.2f}:sample_rate=44100", "-ac", "1",
         "-c:a", "libmp3lame", "-b:a", "128k", "-f", "mp3", "pipe:1"],
        capture_output=True, check=True,
    )
    return out.stdout


class FakeElevenLabs:
    """httpx transport that imitates POST /v1/text-to-dialogue with real (synthetic) MP3 audio."""

    def __init__(self, fail_on_call: dict[int, int] | None = None, chars_per_second: float = 15.0):
        self.calls: list[dict] = []
        self.fail_on_call = fail_on_call or {}
        self.cps = chars_per_second

    def __call__(self, request: httpx.Request) -> httpx.Response:
        n = len(self.calls) + 1
        body = json.loads(request.content) if request.content else {}
        self.calls.append({"path": request.url.path, "params": dict(request.url.params), "body": body,
                           "headers": dict(request.headers)})
        if n in self.fail_on_call:
            status = self.fail_on_call[n]
            return httpx.Response(status, json={"detail": {"status": "error", "message": f"simulated {status}"}})
        if request.url.path == "/v1/text-to-dialogue":
            chars = sum(len(i["text"]) for i in body["inputs"])
            return httpx.Response(200, content=make_mp3(max(chars / self.cps, 0.3)),
                                  headers={"content-type": "audio/mpeg", "request-id": f"req{n}",
                                           "x-character-count": str(chars)})
        if request.url.path == "/v1/user/subscription":
            return httpx.Response(200, json={"tier": "creator", "character_count": 10, "character_limit": 121000})
        return httpx.Response(404, json={"detail": "not found"})

    @property
    def dialogue_calls(self):
        return [c for c in self.calls if c["path"] == "/v1/text-to-dialogue"]


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    data = yaml.safe_load(Path(__file__).parent.parent.joinpath("config.yaml").read_text())
    data["voices"]["alex"]["voice_id"] = "VOICE_ALEX"
    data["voices"]["morgan"]["voice_id"] = "VOICE_MORGAN"
    data["generation"]["max_chars_per_request"] = 400
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


@pytest.fixture
def cfg(cfg_path):
    return load_config(cfg_path)


def sample_episode(turns: int = 12) -> Episode:
    dialogue = []
    for i in range(turns):
        spk = "alex" if i % 2 == 0 else "morgan"
        dialogue.append(Turn(speaker=spk, section=f"Part {i // 4 + 1}",
                             text=f"Line {i + 1}. " + "The switchboard distributes power to each bus. " * 2))
    return Episode(number=1, title="Test", slug="test-ep", track="Engineering", subject="Power",
                   target_minutes=0, dialogue=dialogue)
