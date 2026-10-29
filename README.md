# The Marine Professional: podcast pipeline

This pipeline turns a two-speaker educational script (Alex and Morgan) into one polished MP3, using the ElevenLabs **Text to Dialogue** API. It's a CLI over plain files: there's no server and no database.

```
episode.yaml ──validate──► segments (≤1,800 chars) ──estimate──► Text to Dialogue (checkpointed)
                                                                       │
             ledger.jsonl ◄── transcript.md + <slug>.mp3 ◄── assemble + loudness-normalise + QA
```

## Install

You need Python 3.10+ and ffmpeg (`sudo apt install ffmpeg` or `brew install ffmpeg`).

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env        # then put your key in .env (git-ignored), or export ELEVENLABS_API_KEY
```

## One-time voice setup

1. In ElevenLabs, audition voices under **Voices** (Explore / My Voices). Library voices on your plan cost nothing beyond the credits used to generate audio. Don't buy or clone voices without deciding to. `mpod voices` lists the voices already in your account, with their IDs.
2. Paste the two IDs into `config.yaml` under `voices.alex.voice_id` and `voices.morgan.voice_id`. No code changes are needed.
3. `mpod preview --dry-run` shows the cost (about 600 credits). Then run `mpod preview --yes` and listen to `output/previews/<ids>/preview.mp3`. Each voice pair gets its own folder, so earlier previews are kept for comparison.

## Producing an episode

```bash
mpod validate  episodes/ep001-research-vessel-power        # free: structure, speakers, length
mpod estimate  episodes/ep001-research-vessel-power        # free: segments, credits, $ and monthly projection
mpod render    episodes/ep001-research-vessel-power --max-segments 1 --yes   # paid: ~2 min sample
mpod render    episodes/ep001-research-vessel-power --yes  # paid: full episode (sample segment is reused)
```

The output goes to `output/<slug>/<slug>.mp3` and `<slug>.transcript.md`. The command also updates the episode's `status`, `audio_path` and `cost`, and appends to `ledger/generation_ledger.jsonl`. Afterwards, go through [docs/LISTENING_CHECKLIST.md](docs/LISTENING_CHECKLIST.md).

Paid generation never runs without `--yes`. It also refuses to exceed `cost.limits` (credits per run, credits per month counted from the ledger, segments per run). `mpod account` shows your plan and remaining credits.

### New episodes from ChatGPT

Ask ChatGPT for `ALEX: ...` / `MORGAN: ...` lines, with `## Section` headings. Then run:

```bash
mpod import script.md --number 2 --title "..." --slug ballast-water --track "Vessel Operations" --subject "Ballast water management"
```

The importer joins continuation lines into the turn above, keeps headings as section names, and skips unknown speakers and stage-direction-only lines like `[MUSIC]`, reporting each one it skips. Fill in objectives, references and review questions in the generated `episode.yaml`. See [episodes/_template/episode.yaml](episodes/_template/episode.yaml) for the full format. `mpod catalog` lists every episode with its status and warns about repeated subjects.

## How it works

- **Segmentation** (`segment.py`) packs consecutive turns into requests of at most `max_chars_per_request` characters (ElevenLabs advises ≤2,000). It never reorders turns. A turn is split only when it's longer than the limit on its own, and then at sentence boundaries. Segments break at section boundaries where possible, so joins fall on topic changes.
- **Continuity:** each request carries up to 100 characters of the neighbouring segments' text (`previous_text` / `future_text`) to smooth prosody across joins. `continuity: request_ids` uses the previous request IDs instead. ElevenLabs notes that both are "not supported by every model", so judge the joins by ear.
- **Checkpoints:** each segment is saved as `output/<slug>/segments/NNN_<fingerprint>.mp3`. The fingerprint is a hash of the text, speakers, voice IDs, model, settings and output format. Re-running skips segments that already exist, so a failed run resumes where it stopped, and editing one line regenerates only that segment.
- **Retries:** 429, 5xx, 408 and network errors are retried with exponential backoff (honouring `Retry-After`), 5 attempts in total. 401/403 and 4xx validation errors stop immediately with the API's message. Every failure is written to the ledger.
- **Assembly** (`audio.py`): ffmpeg decodes every segment, adds 10 ms edge fades and `gap_ms` of silence between segments, applies EBU R128 loudness normalisation (`loudness_lufs`, −16 LUFS by default), and encodes one MP3 at the configured bitrate.
- **Automated QA:** checks that each segment decodes, and flags any segment whose length doesn't match its character count (likely truncated, or unusually long). Also runs ffprobe on the final file and detects silences longer than 2.5 s.
- **Secrets:** the key is read only from `ELEVENLABS_API_KEY` (environment or the git-ignored `.env`). It's redacted from all log output, and tests check that it never appears in logs or output files.

## Configuration (`config.yaml`)

| Key | Meaning |
|-----|---------|
| `voices.<name>.voice_id` | ElevenLabs voice ID per speaker. Speaker names in episodes must match these keys |
| `audio.quality` | `high` = MP3 44.1 kHz 192 kbps (Creator plan or above); `standard` = 128 kbps (any plan) |
| `audio.gap_ms`, `audio.loudness_lufs` | Silence between segments; loudness target of the final file |
| `generation.model_id` | `eleven_v4` (default) or `eleven_v3`. These are the only models Text to Dialogue accepts |
| `generation.settings` | `stability` (lower = more expressive), `similarity` |
| `generation.seed` | Set an integer for more repeatable output |
| `cost.plan` | Your plan name, used only for $ estimates |
| `cost.limits.*` | Spending guards |

## Tests

```bash
pytest -q
```

All tests run against a mocked API that returns real synthetic MP3s, so they cost nothing and need no key. They cover: speaker-to-voice mapping; that all dialogue is sent in order; segment limits; assembly and duration; resume after a failure with no duplicate requests; retries; invalid or missing keys; cost limits; MP3 readability; and that secrets never reach logs or tracked files.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ELEVENLABS_API_KEY is not set` | Export it or add it to `.env`. Dry runs don't need it |
| `rejected the API key (401)` | Key revoked or mistyped. Create a new one in ElevenLabs → Developers → API keys |
| `No voice_id configured` | Fill in `config.yaml` voices |
| 422 mentioning `output_format` | Your plan doesn't allow 192 kbps. Set `audio.quality: standard` |
| `exceeds max_credits_per_*` | Intentional guard. Raise the limit in `config.yaml` if you mean it |
| A segment flagged `likely truncated` | Delete that segment's `.mp3` and re-run. Only it is regenerated |
| Bad pronunciation | Respell the term in `episode.yaml` (e.g. "C-T-D"). The affected segment regenerates |
| `ffmpeg not found` | Install ffmpeg |

## Further docs

- [docs/COSTS.md](docs/COSTS.md): pricing, pilot and monthly estimates, model comparison, cost reduction
- [docs/AUTOMATION.md](docs/AUTOMATION.md): options for scheduling and delivery towards daily production
- [docs/LISTENING_CHECKLIST.md](docs/LISTENING_CHECKLIST.md): manual quality review
