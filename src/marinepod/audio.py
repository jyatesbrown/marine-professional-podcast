from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


class AudioError(Exception):
    pass


def _require(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise AudioError(f"{tool} not found on PATH. Install ffmpeg (e.g. `sudo apt install ffmpeg` or `brew install ffmpeg`).")
    return path


def probe(path: str | Path) -> dict:
    """Return {'duration': seconds, 'codec': ..., 'sample_rate': ..., 'bit_rate': ...}; raises if unreadable."""
    out = subprocess.run(
        [_require("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise AudioError(f"ffprobe could not read {path}: {out.stderr.strip()[:300]}")
    data = json.loads(out.stdout)
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise AudioError(f"No audio stream in {path}")
    s = streams[0]
    return {
        "duration": float(data["format"].get("duration") or s.get("duration") or 0),
        "codec": s.get("codec_name"),
        "sample_rate": int(s.get("sample_rate", 0)),
        "bit_rate": int(data["format"].get("bit_rate") or 0),
        "channels": int(s.get("channels", 0)),
    }


def assemble(segment_files: list[Path], out_path: Path, gap_ms: int, loudness_lufs: float, bitrate_k: int) -> Path:
    """Concatenate segments in order with short silences, normalise loudness, write one MP3.

    Every input is decoded and re-encoded once, so the output has a single consistent encoding
    regardless of how segments were produced.
    """
    if not segment_files:
        raise AudioError("No segments to assemble.")
    ffmpeg = _require("ffmpeg")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
        n = len(segment_files)
        for f in segment_files:
            args += ["-i", str(f)]
        filters = []
        labels = []
        for i in range(n):
            # 10 ms fades remove clicks at segment edges without audibly touching speech.
            filters.append(
                f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono,"
                f"afade=t=in:d=0.01,areverse,afade=t=in:d=0.01,areverse[s{i}]"
            )
            labels.append(f"[s{i}]")
            if i < n - 1 and gap_ms > 0:
                filters.append(f"anullsrc=r=44100:cl=mono,atrim=duration={gap_ms / 1000:.3f}[g{i}]")
                labels.append(f"[g{i}]")
        filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[cat]")
        filters.append(f"[cat]loudnorm=I={loudness_lufs}:TP=-1.5:LRA=11[out]")
        tmp_out = Path(td) / "out.mp3"
        args += ["-filter_complex", ";".join(filters), "-map", "[out]", "-ar", "44100",
                 "-c:a", "libmp3lame", "-b:a", f"{bitrate_k}k", "-id3v2_version", "3", str(tmp_out)]
        res = subprocess.run(args, capture_output=True, text=True)
        if res.returncode != 0:
            raise AudioError(f"ffmpeg assembly failed: {res.stderr.strip()[:500]}")
        shutil.move(str(tmp_out), out_path)
    return out_path


def silence_report(path: str | Path, min_silence_s: float = 2.5, noise_db: int = -45) -> list[tuple[float, float]]:
    """Return (start, duration) of silences longer than `min_silence_s` (possible dropouts)."""
    res = subprocess.run(
        [_require("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-af",
         f"silencedetect=noise={noise_db}dB:d={min_silence_s}", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    found = []
    start = None
    for line in res.stderr.splitlines():
        if "silence_start:" in line:
            start = float(line.split("silence_start:")[1].strip().split()[0])
        elif "silence_duration:" in line and start is not None:
            found.append((start, float(line.split("silence_duration:")[1].strip().split()[0])))
            start = None
    return found
