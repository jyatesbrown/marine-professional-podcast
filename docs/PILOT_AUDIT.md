# Pilot audit: `marine_professional_pilot_episode_01.zip`

Audited 2026-10-29. The ZIP contains: `episode_01_script.txt`, `elevenlabs_segment_01..10.json`, `episode_metadata.json`, `render_elevenlabs.py` and `PRODUCTION_README.md`.

## Findings

| Area | Result |
|---|---|
| Script | 75 turns, 2,343 words, 15,687 spoken characters. About 16 to 17 minutes. |
| Speakers | Only ALEX and MORGAN appear. They strictly alternate, and no turn has two consecutive lines from the same speaker. |
| Segment JSON vs script | The 75 inputs across the 10 JSON files match the script exactly in text, speaker and order. Nothing is missing, duplicated or reordered. |
| Request size | 955 to 1,786 characters per request, all under the 2,000-character reliability guideline. |
| Audio tags | None. That is fine; plain text is read naturally. |
| Content | Technically sound and carefully caveated (it is not a switching procedure). It is preserved unchanged. |

## Reused

- The full dialogue, imported verbatim into `episodes/ep001-research-vessel-power/episode.yaml`. Each blank-line-separated block becomes a section ("Part N"), so segments break at topic changes.
- Learning objectives, references, voice direction and pronunciation list, all from `PRODUCTION_README.md`.

## Renderer issues (`render_elevenlabs.py`), replaced by `mpod render`

1. **Uses `eleven_v3`.** ElevenLabs now recommends `eleven_v4` for Text to Dialogue. The model is configurable (`generation.model_id`).
2. **Cache is keyed only by file name.** `segment_NN.mp3` is reused even after the text or voice changes, so stale audio can be shipped silently. `mpod` caches segments by a hash of the text, voices and parameters.
3. **No retries.** A single 429 or 5xx response aborts the run, and `raise_for_status()` hides the API's error message.
4. **No continuity context.** It sends no `previous_text`/`future_text`, which raises the risk of audible tone jumps at the ten joins.
5. **Joins with `ffmpeg -c copy` concat.** There are no gaps, fades or loudness normalisation, and joining MP3 frames this way can leave clicks or encoder-delay gaps. `mpod` re-encodes, adds short fades and pauses, and normalises to −16 LUFS.
6. **No cost estimate, spend limit, confirmation step, ledger, or validation of the output audio.**
7. **Writes files non-atomically.** An interrupted download leaves a truncated MP3 that would be "skipped" as finished on the next run.
8. **Fixed 128 kbps.** `mpod` uses 192 kbps when the plan allows it (`audio.quality`).

## Decisions not covered by the brief

- **Title.** The brief says "How a Research Vessel Makes, Distributes, and Protects Electrical Power". The ZIP says "From Generator to Instrument: How a Research Vessel Manages Electrical Power". I kept the ZIP's title; changing it is a one-line edit in `episode.yaml`.
- **Segmentation.** `mpod` splits the episode into 11 requests at section boundaries rather than the ZIP's 10. Character count, and therefore cost, is unchanged.
- **Pronunciation.** "HVAC" is ambiguous: it can be spelled out or said "aitch-vac". It is left as written. Listen for it in the sample.
