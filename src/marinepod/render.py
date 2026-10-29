from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import audio
from .client import ElevenLabsClient, ElevenLabsError
from .config import Config
from .cost import LimitExceeded, enforce_limits, estimate
from .episode import Episode, save_episode, validate_episode
from .ledger import Ledger
from .segment import Segment, segment_dialogue

log = logging.getLogger("marinepod.render")

# Speech normally runs ~13-17 characters per second. Much faster than this means audio was cut short.
MAX_CHARS_PER_SECOND = 30.0
MIN_CHARS_PER_SECOND = 6.0


class RenderError(Exception):
    pass


@dataclass
class Plan:
    episode: Episode
    segments: list[Segment]
    voice_map: dict[str, str]
    params: dict
    seg_dir: Path
    fingerprints: list[str] = field(default_factory=list)

    def seg_path(self, seg: Segment) -> Path:
        return self.seg_dir / f"{seg.index:03d}_{self.fingerprints[seg.index]}.mp3"

    def cached(self, seg: Segment) -> bool:
        p = self.seg_path(seg)
        return p.exists() and p.stat().st_size > 0

    @property
    def missing(self) -> list[Segment]:
        return [s for s in self.segments if not self.cached(s)]


def build_plan(cfg: Config, ep: Episode, out_root: Path, require_voices: bool = True,
               max_segments: int | None = None) -> Plan:
    voice_map = cfg.voice_map(require_ids=require_voices)
    errors, warnings = validate_episode(ep, list(voice_map))
    for w in warnings:
        log.warning("validate: %s", w)
    if errors:
        raise RenderError("Episode failed validation:\n  - " + "\n  - ".join(errors))
    g = cfg.generation
    params = {
        "model_id": g.model_id,
        "output_format": cfg.audio.output_format,
        "settings": g.settings.model_dump(),
        "language_code": g.language_code,
        "seed": g.seed,
        "continuity": g.continuity,
    }
    segments = segment_dialogue(ep.dialogue, g.max_chars_per_request)
    if max_segments is not None:
        segments = segments[:max_segments]
    plan = Plan(ep, segments, voice_map, params, out_root / ep.slug / "segments")
    plan.fingerprints = [s.fingerprint(voice_map, params) for s in segments]
    return plan


def describe_plan(plan: Plan, cfg: Config) -> list[str]:
    full = estimate(plan.segments, cfg.generation.model_id, cfg.cost.plan)
    todo = estimate(plan.missing, cfg.generation.model_id, cfg.cost.plan)
    lines = [
        f"Episode {plan.episode.number:02d}: {plan.episode.title}",
        f"model {cfg.generation.model_id}, output {cfg.audio.output_format}, "
        f"<= {cfg.generation.max_chars_per_request} chars/request",
        "",
        "Whole episode:",
        *("  " + x for x in full.lines()),
        "",
        f"Still to generate ({len(plan.missing)} of {len(plan.segments)} segments; cached segments are free):",
        *("  " + x for x in todo.lines()),
        "",
        "Segments:",
    ]
    for s in plan.segments:
        spk = "/".join(dict.fromkeys(i.speaker for i in s.inputs))
        mark = "cached" if plan.cached(s) else "to generate"
        lines.append(f"  {s.index:03d}  {s.chars:>5} chars  {len(s.inputs):>2} turns  {spk:<13} {mark}  "
                     f"{s.inputs[0].text[:50]!r}")
    return lines


def _neighbour_context(plan: Plan, seg: Segment) -> dict:
    mode = plan.params["continuity"]
    i = seg.index
    if mode == "previous_text":
        ctx = {}
        if i > 0:
            ctx["previous_text"] = plan.segments[i - 1].text[-100:]
        if i + 1 < len(plan.segments):
            ctx["future_text"] = plan.segments[i + 1].text[:100]
        return ctx
    if mode == "request_ids":
        ids = []
        for prev in plan.segments[max(0, i - 3):i]:
            meta = plan.seg_path(prev).with_suffix(".json")
            if meta.exists():
                rid = json.loads(meta.read_text()).get("request_id")
                if rid:
                    ids.append(rid)
        return {"previous_request_ids": ids} if ids else {}
    return {}


def check_segment_audio(path: Path, chars: int) -> list[str]:
    info = audio.probe(path)
    dur = info["duration"]
    problems = []
    if dur <= 0:
        problems.append("zero duration")
    else:
        cps = chars / dur
        if cps > MAX_CHARS_PER_SECOND:
            problems.append(f"{dur:.1f}s for {chars} chars ({cps:.0f} chars/s): likely truncated")
        if cps < MIN_CHARS_PER_SECOND:
            problems.append(f"{dur:.1f}s for {chars} chars ({cps:.0f} chars/s): unusually long, check for repetition")
    return problems


def generate_segments(plan: Plan, cfg: Config, client: ElevenLabsClient, ledger: Ledger,
                      confirm: bool) -> list[Path]:
    todo = plan.missing
    est = estimate(todo, cfg.generation.model_id, cfg.cost.plan)
    if todo:
        enforce_limits(est.credits, len(todo), ledger.credits_this_month(), cfg.cost.limits)
        if not confirm:
            raise RenderError(
                f"{len(todo)} segments ({est.credits:,} credits) need paid generation. "
                "Re-run with --yes to approve, or --dry-run to review."
            )
    plan.seg_dir.mkdir(parents=True, exist_ok=True)
    g = cfg.generation
    for seg in todo:
        inputs = [{"text": i.text, "voice_id": plan.voice_map[i.speaker]} for i in seg.inputs]
        log.info("segment %03d: generating %d chars (%d turns)", seg.index, seg.chars, len(inputs))
        try:
            res = client.text_to_dialogue(
                inputs=inputs, model_id=g.model_id, output_format=cfg.audio.output_format,
                settings=g.settings.model_dump(), language_code=g.language_code, seed=g.seed,
                **_neighbour_context(plan, seg),
            )
        except ElevenLabsError as e:
            ledger.append(event="segment_failed", episode=plan.episode.slug, segment=seg.index, error=str(e)[:500])
            log.error("segment %03d failed: %s", seg.index, e)
            raise RenderError(
                f"Segment {seg.index:03d} failed: {e}\n{seg.index} earlier segments are saved; "
                "re-run the same command to resume from here."
            ) from e
        path = plan.seg_path(seg)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(res.audio)
        os.replace(tmp, path)
        credits = res.character_count if res.character_count is not None else seg.chars
        meta = {"index": seg.index, "fingerprint": plan.fingerprints[seg.index], "chars": seg.chars,
                "credits": credits, "credits_source": "api" if res.character_count is not None else "estimate",
                "request_id": res.request_id,
                "inputs": [{"speaker": i.speaker, "text": i.text} for i in seg.inputs]}
        path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
        ledger.append(event="segment_generated", episode=plan.episode.slug, segment=seg.index,
                      chars=seg.chars, credits=credits, credits_source=meta["credits_source"],
                      model_id=g.model_id, request_id=res.request_id)
    problems = []
    for seg in plan.segments:
        for p in check_segment_audio(plan.seg_path(seg), seg.chars):
            problems.append(f"segment {seg.index:03d}: {p}")
    for p in problems:
        log.warning("QA: %s", p)
    return [plan.seg_path(s) for s in plan.segments]


def finish_episode(plan: Plan, cfg: Config, files: list[Path], out_path: Path, ledger: Ledger,
                   episode_file: Path | None) -> dict:
    bitrate = int(cfg.audio.output_format.rsplit("_", 1)[1])
    audio.assemble(files, out_path, cfg.audio.gap_ms, cfg.audio.loudness_lufs, bitrate)
    info = audio.probe(out_path)
    silences = audio.silence_report(out_path)
    transcript = out_path.with_suffix(".transcript.md")
    write_transcript(plan, transcript)
    credits = 0
    for s in plan.segments:
        meta = plan.seg_path(s).with_suffix(".json")
        if meta.exists():
            credits += int(json.loads(meta.read_text()).get("credits", s.chars))
    report = {"audio": str(out_path), "transcript": str(transcript), "duration_s": round(info["duration"], 1),
              "sample_rate": info["sample_rate"], "bit_rate": info["bit_rate"], "segments": len(files),
              "long_silences": silences, "credits_recorded": credits}
    ledger.append(event="episode_assembled", episode=plan.episode.slug, **{k: v for k, v in report.items()
                                                                            if k != "long_silences"})
    if episode_file is not None:
        ep = plan.episode
        ep.status = "rendered"
        ep.audio_path = str(out_path)
        est = estimate(plan.segments, cfg.generation.model_id, cfg.cost.plan)
        ep.cost.estimated_credits = est.credits
        ep.cost.estimated_usd = round(est.usd_at_plan_rate, 2)
        ep.cost.actual_credits = credits
        ep.cost.actual_usd = round(est.usd_at_plan_rate * credits / est.credits, 2) if est.credits else None
        save_episode(ep, episode_file)
    return report


def write_transcript(plan: Plan, path: Path) -> None:
    ep = plan.episode
    lines = [f"# Episode {ep.number:02d}: {ep.title}", ""]
    section = None
    for seg in plan.segments:
        for i in seg.inputs:
            t = ep.dialogue[i.turn_index]
            if t.section and t.section != section:
                section = t.section
                lines += ["", f"## {section}", ""]
            lines.append(f"**{i.speaker.title()}:** {i.text}")
            lines.append("")
    path.write_text("\n".join(lines).strip() + "\n")


__all__ = ["build_plan", "describe_plan", "generate_segments", "finish_episode", "RenderError", "LimitExceeded"]
