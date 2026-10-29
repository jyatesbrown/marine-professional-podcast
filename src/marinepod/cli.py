from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml

from . import render as R
from .client import AuthError, ElevenLabsClient, ElevenLabsError, get_api_key
from .config import ConfigError, load_config
from .cost import LimitExceeded, estimate, monthly_projection
from .episode import Episode, EpisodeError, Turn, estimate_minutes, load_episode, save_episode, validate_episode
from .importer import import_script
from .ledger import Ledger
from .segment import segment_dialogue

log = logging.getLogger("marinepod")

PREVIEW_DIALOGUE = [
    ("alex", "Welcome aboard. Today we're tracing power on a research vessel, from the diesel generators to the switchboard."),
    ("morgan", "And from there out to the winches, the lab outlets, and the multibeam sonar. Where do we start?"),
    ("alex", "With the generator set. Four-hundred-eighty volts, sixty hertz, three-phase, synchronised onto the main bus."),
    ("morgan", "So if one generator trips during a CTD cast, the power management system sheds load before the bus collapses?"),
    ("alex", "Exactly. Non-essential loads drop first, so propulsion, steering, and the A-frame stay powered."),
    ("morgan", "Good. Let's take that one step at a time."),
]


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _client(args) -> ElevenLabsClient:
    return ElevenLabsClient(get_api_key())


def _episode_file(arg: str) -> Path:
    p = Path(arg)
    return p / "episode.yaml" if p.is_dir() else p


def cmd_validate(args, cfg) -> int:
    ep = load_episode(args.episode)
    errors, warnings = validate_episode(ep, list(cfg.voices))
    segs = segment_dialogue(ep.dialogue, cfg.generation.max_chars_per_request)
    print(f"Episode {ep.number:02d}: {ep.title}")
    print(f"  {len(ep.dialogue)} turns, speakers {ep.speakers}, {ep.spoken_chars:,} chars, "
          f"~{estimate_minutes(ep):.1f} min, {len(segs)} segments (max {max(s.chars for s in segs) if segs else 0} chars)")
    for w in warnings:
        print(f"  WARNING: {w}")
    for e in errors:
        print(f"  ERROR: {e}")
    print("  OK" if not errors else "  FAILED")
    return 1 if errors else 0


def _credits_used(client) -> int | None:
    try:
        return int(client.subscription().get("character_count"))
    except Exception:  # noqa: BLE001 - usage measurement is best-effort; key may lack User read
        return None


def cmd_render(args, cfg) -> int:
    ep_file = _episode_file(args.episode)
    ep = load_episode(ep_file)
    out_root = Path(args.output)
    plan = R.build_plan(cfg, ep, out_root, require_voices=not args.dry_run, max_segments=args.max_segments)
    for line in R.describe_plan(plan, cfg):
        print(line)
    if args.dry_run:
        per_ep = estimate(segment_dialogue(ep.dialogue, cfg.generation.max_chars_per_request),
                          cfg.generation.model_id, cfg.cost.plan).credits
        print("\nMonthly projection at this episode size:")
        for line in monthly_projection(per_ep):
            print("  " + line)
        print("\nDry run: no API calls made.")
        return 0
    sample = args.max_segments is not None
    ledger = Ledger(args.ledger)
    client = _client(args)
    try:
        before = _credits_used(client) if plan.missing else None
        files = R.generate_segments(plan, cfg, client, ledger, confirm=args.yes)
        after = _credits_used(client) if before is not None else None
    finally:
        client.close()
    delta = after - before if before is not None and after is not None and after >= before else None
    name = f"{ep.slug}.sample.mp3" if sample else f"{ep.slug}.mp3"
    report = R.finish_episode(plan, cfg, files, out_root / ep.slug / name, ledger,
                              None if sample else ep_file, account_credits=delta)
    _print_report(report)
    return 0


def cmd_preview(args, cfg) -> int:
    ep = Episode(number=0, title="Voice preview", slug="voice-preview", track="preview", subject="preview",
                 target_minutes=0.5, dialogue=[Turn(speaker=s, text=t) for s, t in PREVIEW_DIALOGUE])
    vm = cfg.voice_map(require_ids=not args.dry_run)
    ep.slug = "voice-preview-" + "-".join(v[:8] or "unset" for v in vm.values())
    plan = R.build_plan(cfg, ep, Path(args.output) / "previews", require_voices=not args.dry_run)
    est = estimate(plan.missing, cfg.generation.model_id, cfg.cost.plan)
    print(f"Preview: {len(PREVIEW_DIALOGUE)} lines, {est.chars} chars, ~{est.credits} credits "
          f"({'cached' if not plan.missing else 'to generate'})")
    for name, v in cfg.voices.items():
        print(f"  {name}: {v.voice_id or '(unset)'}  {v.role}")
    if args.dry_run:
        return 0
    ledger = Ledger(args.ledger)
    client = _client(args)
    try:
        files = R.generate_segments(plan, cfg, client, ledger, confirm=args.yes)
    finally:
        client.close()
    out = plan.seg_dir.parent / "preview.mp3"
    _print_report(R.finish_episode(plan, cfg, files, out, ledger, None))
    return 0


def cmd_import(args, cfg) -> int:
    meta = {"number": args.number, "title": args.title, "slug": args.slug, "track": args.track,
            "subject": args.subject, "target_minutes": args.target_minutes or cfg.podcast.target_minutes}
    ep, notes = import_script(args.script, list(cfg.voices), **meta)
    for n in notes:
        print(f"  NOTE: {n}")
    dest = Path(args.dest or f"episodes/ep{args.number:03d}-{args.slug}")
    path = save_episode(ep, dest)
    print(f"Imported {len(ep.dialogue)} turns -> {path}. Fill in objectives/references, then run validate.")
    return 0


def cmd_voices(args, cfg) -> int:
    client = _client(args)
    try:
        voices = client.voices()
    finally:
        client.close()
    for v in voices:
        labels = v.get("labels") or {}
        desc = ", ".join(str(x) for x in (labels.get("gender"), labels.get("accent"), labels.get("age"),
                                           labels.get("descriptive") or labels.get("description")) if x)
        print(f"{v.get('voice_id')}  {v.get('name', '')[:28]:<28} {v.get('category', ''):<12} {desc}")
    return 0


def cmd_account(args, cfg) -> int:
    client = _client(args)
    try:
        sub = client.subscription()
    finally:
        client.close()
    used, limit = sub.get("character_count", 0), sub.get("character_limit", 0)
    print(f"tier: {sub.get('tier')}  status: {sub.get('status')}")
    print(f"credits used this cycle: {used:,} / {limit:,}  (remaining {limit - used:,})")
    if sub.get("next_character_count_reset_unix"):
        from datetime import datetime, timezone
        print("resets:", datetime.fromtimestamp(sub["next_character_count_reset_unix"], timezone.utc).date())
    return 0


def cmd_ledger(args, cfg) -> int:
    led = Ledger(args.ledger)
    recs = led.records()
    for r in recs[-args.tail:]:
        print(r)
    print(f"credits recorded this month: {led.credits_this_month():,} "
          f"(limit {cfg.cost.limits.max_credits_per_month:,})")
    return 0


def cmd_catalog(args, cfg) -> int:
    rows = []
    for f in sorted(Path(args.episodes).glob("*/episode.yaml")):
        try:
            ep = load_episode(f)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {f}: {e}")
            continue
        rows.append(ep)
        print(f"{ep.number:03d}  {ep.status:<15} {ep.track:<24} {ep.subject:<32} {ep.title}")
    subjects = [e.subject.lower() for e in rows]
    for s in sorted({s for s in subjects if subjects.count(s) > 1}):
        print(f"  WARNING: subject repeated across episodes: {s!r}")
    return 0


def _print_report(report: dict) -> None:
    print("\nResult:")
    print(yaml.safe_dump(report, sort_keys=False).rstrip())
    if report.get("long_silences"):
        print("WARNING: long silences found; listen at those timestamps.")
    print("Automated checks passed. Now do the manual listening review (docs/LISTENING_CHECKLIST.md).")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mpod", description="The Marine Professional podcast pipeline")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--ledger", default="ledger/generation_ledger.jsonl")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("validate", help="check an episode file (free)")
    s.add_argument("episode")
    s.set_defaults(fn=cmd_validate)

    for name, helptext in (("render", "generate an episode MP3"), ("estimate", "dry run: segments and cost (free)")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("episode")
        s.add_argument("--output", default="output")
        s.add_argument("--max-segments", type=int, default=None,
                       help="only render the first N segments into <slug>.sample.mp3")
        s.add_argument("--yes", action="store_true", help="approve paid generation")
        s.add_argument("--dry-run", action="store_true", default=(name == "estimate"))
        s.set_defaults(fn=cmd_render)

    s = sub.add_parser("preview", help="short Alex/Morgan exchange with the configured voices")
    s.add_argument("--output", default="output")
    s.add_argument("--yes", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_preview)

    s = sub.add_parser("import", help="convert a 'NAME: line' script into an episode file")
    s.add_argument("script")
    s.add_argument("--number", type=int, required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--slug", required=True)
    s.add_argument("--track", required=True)
    s.add_argument("--subject", required=True)
    s.add_argument("--target-minutes", type=float)
    s.add_argument("--dest")
    s.set_defaults(fn=cmd_import)

    sub.add_parser("voices", help="list voices in your ElevenLabs account (free)").set_defaults(fn=cmd_voices)
    sub.add_parser("account", help="show plan and remaining credits (free)").set_defaults(fn=cmd_account)
    s = sub.add_parser("ledger", help="show recent generation records")
    s.add_argument("--tail", type=int, default=20)
    s.set_defaults(fn=cmd_ledger)
    s = sub.add_parser("catalog", help="list episodes, status and repeated subjects")
    s.add_argument("--episodes", default="episodes")
    s.set_defaults(fn=cmd_catalog)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    _load_dotenv()
    try:
        cfg = load_config(args.config)
        return args.fn(args, cfg)
    except (ConfigError, EpisodeError, R.RenderError, LimitExceeded, AuthError, ElevenLabsError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
