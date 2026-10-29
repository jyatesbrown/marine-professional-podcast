import logging

import httpx
import pytest

from marinepod import audio
from marinepod import render as R
from marinepod.client import ElevenLabsClient, MissingKeyError, get_api_key
from marinepod.cost import LimitExceeded
from marinepod.episode import save_episode, load_episode
from marinepod.ledger import Ledger

from conftest import FAKE_KEY, FakeElevenLabs, sample_episode


def client_for(fake, **kw):
    return ElevenLabsClient(FAKE_KEY, transport=httpx.MockTransport(fake), sleep=lambda s: None, **kw)


def test_speaker_voice_mapping_and_request_shape(cfg, tmp_path):
    ep = sample_episode(8)
    plan = R.build_plan(cfg, ep, tmp_path)
    fake = FakeElevenLabs()
    R.generate_segments(plan, cfg, client_for(fake), Ledger(tmp_path / "l.jsonl"), confirm=True)
    sent = [(i["voice_id"], i["text"]) for c in fake.dialogue_calls for i in c["body"]["inputs"]]
    expected = [({"alex": "VOICE_ALEX", "morgan": "VOICE_MORGAN"}[t.speaker], t.text) for t in ep.dialogue]
    assert sent == expected
    c = fake.dialogue_calls[0]
    assert c["body"]["model_id"] == "eleven_v4"
    assert c["params"]["output_format"] == "mp3_44100_192"
    assert c["headers"]["xi-api-key"] == FAKE_KEY
    assert "previous_text" not in c["body"] and "future_text" in c["body"]
    assert all(len(x["body"].get("previous_text", "")) <= 100 for x in fake.dialogue_calls)
    assert all(sum(len(i["text"]) for i in x["body"]["inputs"]) <= 400 for x in fake.dialogue_calls)


def test_full_render_assembles_readable_mp3(cfg, tmp_path):
    ep = sample_episode(10)
    ep_file = save_episode(ep, tmp_path / "ep")
    plan = R.build_plan(cfg, ep, tmp_path / "out")
    led = Ledger(tmp_path / "l.jsonl")
    files = R.generate_segments(plan, cfg, client_for(FakeElevenLabs()), led, confirm=True)
    out = tmp_path / "out" / "ep.mp3"
    report = R.finish_episode(plan, cfg, files, out, led, ep_file)
    info = audio.probe(out)
    expected = sum(audio.probe(f)["duration"] for f in files) + cfg.audio.gap_ms / 1000 * (len(files) - 1)
    assert info["codec"] == "mp3" and info["sample_rate"] == 44100
    assert abs(info["duration"] - expected) < 0.5
    assert report["credits_recorded"] == ep.spoken_chars
    saved = load_episode(ep_file)
    assert saved.status == "rendered" and saved.audio_path == str(out)
    assert saved.cost.actual_credits == ep.spoken_chars
    transcript = out.with_suffix(".transcript.md").read_text()
    assert all(t.text in transcript for t in ep.dialogue)


def test_resume_after_partial_failure_no_duplicates(cfg, tmp_path):
    ep = sample_episode(16)
    plan = R.build_plan(cfg, ep, tmp_path)
    n = len(plan.segments)
    assert n >= 4
    led = Ledger(tmp_path / "l.jsonl")
    fake = FakeElevenLabs(fail_on_call={3: 400})
    with pytest.raises(R.RenderError, match="resume"):
        R.generate_segments(plan, cfg, client_for(fake), led, confirm=True)
    assert len(plan.missing) == n - 2
    fake2 = FakeElevenLabs()
    R.generate_segments(plan, cfg, client_for(fake2), led, confirm=True)
    assert len(fake2.dialogue_calls) == n - 2
    first_texts = [c["body"]["inputs"][0]["text"] for c in fake.dialogue_calls[:2] + fake2.dialogue_calls]
    assert len(first_texts) == len(set(first_texts)) == n
    fake3 = FakeElevenLabs()
    R.generate_segments(plan, cfg, client_for(fake3), led, confirm=True)
    assert fake3.dialogue_calls == []
    events = [r["event"] for r in led.records()]
    assert events.count("segment_generated") == n and events.count("segment_failed") == 1


def test_changing_voice_invalidates_checkpoints(cfg, tmp_path):
    ep = sample_episode(4)
    plan = R.build_plan(cfg, ep, tmp_path)
    R.generate_segments(plan, cfg, client_for(FakeElevenLabs()), Ledger(tmp_path / "l"), confirm=True)
    cfg.voices["morgan"].voice_id = "OTHER"
    plan2 = R.build_plan(cfg, ep, tmp_path)
    assert len(plan2.missing) == len(plan2.segments)


def test_retries_rate_limit_and_server_errors(cfg, tmp_path):
    ep = sample_episode(2)
    plan = R.build_plan(cfg, ep, tmp_path)
    fake = FakeElevenLabs(fail_on_call={1: 429, 2: 503})
    R.generate_segments(plan, cfg, client_for(fake), Ledger(tmp_path / "l"), confirm=True)
    assert len(fake.calls) == 3 and not plan.missing


def test_gives_up_after_max_attempts(cfg, tmp_path):
    plan = R.build_plan(cfg, sample_episode(2), tmp_path)
    fake = FakeElevenLabs(fail_on_call={i: 500 for i in range(1, 10)})
    with pytest.raises(R.RenderError):
        R.generate_segments(plan, cfg, client_for(fake, max_attempts=3), Ledger(tmp_path / "l"), confirm=True)
    assert len(fake.calls) == 3


def test_invalid_key_not_retried(cfg, tmp_path):
    plan = R.build_plan(cfg, sample_episode(2), tmp_path)
    fake = FakeElevenLabs(fail_on_call={1: 401})
    with pytest.raises(R.RenderError, match="rejected the API key"):
        R.generate_segments(plan, cfg, client_for(fake), Ledger(tmp_path / "l"), confirm=True)
    assert len(fake.calls) == 1


def test_missing_key():
    with pytest.raises(MissingKeyError):
        get_api_key({})
    with pytest.raises(MissingKeyError):
        get_api_key({"ELEVENLABS_API_KEY": "  "})


def test_requires_confirmation_and_makes_no_calls(cfg, tmp_path):
    plan = R.build_plan(cfg, sample_episode(4), tmp_path)
    fake = FakeElevenLabs()
    with pytest.raises(R.RenderError, match="--yes"):
        R.generate_segments(plan, cfg, client_for(fake), Ledger(tmp_path / "l"), confirm=False)
    assert fake.calls == []


@pytest.mark.parametrize("field,value", [("max_credits_per_run", 100), ("max_segments_per_run", 1),
                                         ("max_credits_per_month", 100)])
def test_cost_limits_enforced(cfg, tmp_path, field, value):
    setattr(cfg.cost.limits, field, value)
    plan = R.build_plan(cfg, sample_episode(6), tmp_path)
    fake = FakeElevenLabs()
    with pytest.raises(LimitExceeded):
        R.generate_segments(plan, cfg, client_for(fake), Ledger(tmp_path / "l"), confirm=True)
    assert fake.calls == []


def test_monthly_limit_counts_ledger(cfg, tmp_path):
    led = Ledger(tmp_path / "l")
    led.append(event="segment_generated", credits=cfg.cost.limits.max_credits_per_month - 10)
    plan = R.build_plan(cfg, sample_episode(2), tmp_path)
    with pytest.raises(LimitExceeded, match="this month"):
        R.generate_segments(plan, cfg, client_for(FakeElevenLabs()), led, confirm=True)


def test_missing_voice_ids_block_paid_render(cfg, tmp_path):
    cfg.voices["alex"].voice_id = ""
    with pytest.raises(Exception, match="voice_id"):
        R.build_plan(cfg, sample_episode(2), tmp_path)
    R.build_plan(cfg, sample_episode(2), tmp_path, require_voices=False)


def test_unknown_speaker_fails_validation(cfg, tmp_path):
    ep = sample_episode(2)
    ep.dialogue[1].speaker = "jordan"
    with pytest.raises(R.RenderError, match="jordan"):
        R.build_plan(cfg, ep, tmp_path)


def test_truncated_segment_flagged(tmp_path):
    from conftest import make_mp3
    p = tmp_path / "x.mp3"
    p.write_bytes(make_mp3(1.0))
    assert any("truncated" in m for m in R.check_segment_audio(p, 1000))
    assert R.check_segment_audio(p, 15) == []


def test_key_never_logged_or_saved(cfg, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    ep = sample_episode(4)
    plan = R.build_plan(cfg, ep, tmp_path / "out")
    led = Ledger(tmp_path / "l.jsonl")
    fake = FakeElevenLabs(fail_on_call={1: 429})
    client = client_for(fake)
    logging.getLogger("marinepod.test").info("key is %s", FAKE_KEY)
    files = R.generate_segments(plan, cfg, client, led, confirm=True)
    R.finish_episode(plan, cfg, files, tmp_path / "out" / "e.mp3", led, None)
    assert FAKE_KEY not in caplog.text
    for f in tmp_path.rglob("*"):
        if f.is_file():
            assert FAKE_KEY.encode() not in f.read_bytes(), f
