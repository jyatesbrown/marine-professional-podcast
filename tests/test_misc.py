import subprocess
from pathlib import Path

from marinepod.cli import main
from marinepod.cost import estimate, monthly_projection
from marinepod.episode import load_episode, validate_episode
from marinepod.importer import parse_script
from marinepod.segment import segment_dialogue

from conftest import sample_episode

ROOT = Path(__file__).parent.parent


def test_importer_chatgpt_style():
    text = """# Episode 1
## Opening
**ALEX:** Welcome aboard.
This line continues Alex.
MORGAN: Thanks, Alex.
[MUSIC FADES]
NARRATOR: should be skipped
## Generators
Alex: Four hundred eighty volts.
"""
    turns, notes = parse_script(text, ["alex", "morgan"])
    assert [(t.speaker, t.text, t.section) for t in turns] == [
        ("alex", "Welcome aboard. This line continues Alex.", "Opening"),
        ("morgan", "Thanks, Alex.", "Opening"),
        ("alex", "Four hundred eighty volts.", "Generators"),
    ]
    assert len(notes) == 2


def test_validation_flags_repetition():
    ep = sample_episode(3)
    ep.dialogue[2].text = ep.dialogue[1].text
    errors, _ = validate_episode(ep, ["alex", "morgan"])
    assert any("identical" in e for e in errors)


def test_estimate_and_projection():
    segs = segment_dialogue(sample_episode(10).dialogue, 400)
    est = estimate(segs, "eleven_v4", "creator")
    assert est.credits == est.chars == sum(s.chars for s in segs)
    assert abs(est.usd_payg - est.chars / 1000 * 0.08) < 1e-9
    lines = monthly_projection(14000)
    assert "420,000" in lines[0]


def test_template_episode_valid():
    ep = load_episode(ROOT / "episodes/_template")
    assert ep.dialogue


def test_cli_dry_run_needs_no_key(cfg_path, tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    from marinepod.episode import save_episode
    save_episode(sample_episode(10), tmp_path / "ep")
    assert main(["--config", str(cfg_path), "estimate", str(tmp_path / "ep")]) == 0
    out = capsys.readouterr().out
    assert "Dry run: no API calls made." in out and "estimated credits" in out
    assert main(["--config", str(cfg_path), "render", str(tmp_path / "ep"), "--yes"]) == 2
    assert "ELEVENLABS_API_KEY is not set" in capsys.readouterr().err


def test_no_secrets_in_tracked_files():
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT,
                           capture_output=True, text=True).stdout.split()
    import re
    pat = re.compile(r"sk_[0-9a-f]{40,}|xi-api-key\s*[:=]\s*['\"][A-Za-z0-9_]{20,}")
    for f in files:
        p = ROOT / f
        if p.suffix in {".mp3"} or not p.is_file():
            continue
        assert not pat.search(p.read_text(errors="ignore")), f
    assert ".env" in (ROOT / ".gitignore").read_text()
