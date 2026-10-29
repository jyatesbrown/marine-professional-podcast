from marinepod.config import HARD_MAX_CHARS_PER_REQUEST
from marinepod.episode import Turn
from marinepod.segment import segment_dialogue

from conftest import sample_episode


def flatten(segs):
    return [(i.speaker, i.text) for s in segs for i in s.inputs]


def test_all_dialogue_preserved_in_order():
    ep = sample_episode(30)
    segs = segment_dialogue(ep.dialogue, 400)
    assert flatten(segs) == [(t.speaker, t.text) for t in ep.dialogue]
    assert [s.index for s in segs] == list(range(len(segs)))


def test_segments_within_limit():
    ep = sample_episode(40)
    for limit in (300, 1000, HARD_MAX_CHARS_PER_REQUEST):
        for s in segment_dialogue(ep.dialogue, limit):
            assert 0 < s.chars <= limit


def test_long_turn_split_at_sentences_and_rejoins_exactly():
    text = " ".join(f"Sentence number {i} explains breaker coordination in detail." for i in range(60))
    segs = segment_dialogue([Turn(speaker="alex", text=text)], 500)
    assert len(segs) > 1
    assert all(s.chars <= 500 for s in segs)
    parts = [i.text for s in segs for i in s.inputs]
    assert all(p.endswith(".") for p in parts)
    assert " ".join(parts) == text
    assert {i.speaker for s in segs for i in s.inputs} == {"alex"}


def test_unbreakable_text_falls_back_to_words():
    text = "word " * 600
    segs = segment_dialogue([Turn(speaker="morgan", text=text.strip())], 300)
    assert all(s.chars <= 300 for s in segs)
    assert " ".join(i.text for s in segs for i in s.inputs) == text.strip()


def test_prefers_section_boundaries():
    turns = [Turn(speaker="alex", text="a" * 120, section="One"),
             Turn(speaker="morgan", text="b" * 120, section="One"),
             Turn(speaker="alex", text="c" * 50, section="Two")]
    segs = segment_dialogue(turns, 400)
    assert [len(s.inputs) for s in segs] == [2, 1]
