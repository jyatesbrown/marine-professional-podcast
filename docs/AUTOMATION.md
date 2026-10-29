# Path to daily production (not active)

Nothing here is scheduled. Daily generation and recurring paid API usage are deliberately **off**.

## Pipeline steps and where they already exist

| Step | Today |
|------|-------|
| 1. Receive a finished script | `mpod import script.md --number N ...` or a hand-written `episodes/epNNN-*/episode.yaml` |
| 2. Validate script and metadata | `mpod validate` (speakers, empty or duplicate turns, labels left in the text, length vs. target) |
| 3. Pick the configured voices | `config.yaml` → `voices` |
| 4. Estimate cost | `mpod estimate` (also enforced by `cost.limits` during a render) |
| 5. Generate audio | `mpod render ... --yes` (checkpointed, resumable) |
| 6. Automated QA | per-segment duration/character-rate check, ffprobe decode, silence detection, transcript |
| 7. Save MP3 and transcript | `output/<slug>/<slug>.mp3` and `.transcript.md` |
| 8. Update the ledger | `ledger/generation_ledger.jsonl` and the `status`/`cost` fields in `episode.yaml` |
| 9. Deliver | not built (options below) |

## Scheduling options, simplest first

1. **Cron or launchd on your own machine:** `mpod render episodes/next --yes` every morning. No new infrastructure, but the machine has to be awake.
2. **GitHub Actions on a schedule** in this (private) repo. Store `ELEVENLABS_API_KEY` as an Actions secret. Commit episode files from ChatGPT, and the workflow renders the oldest `validated` episode and uploads the MP3 as a release asset. Free within the Actions minutes quota. Keep MP3s out of git.
3. **A Devin scheduled session:** run the same command, then post the result. Useful if script writing gets automated too.

Whichever you choose, keep `cost.limits.max_credits_per_month` below your plan's monthly credits. The renderer refuses to run past it.

## Delivery options

- **Private podcast RSS feed:** upload the MP3 to object storage (e.g. Cloudflare R2) and regenerate a `feed.xml` with each episode's title, description (objectives plus review questions) and enclosure URL. Subscribe in Overcast or Pocket Casts with an unguessable URL. Works offline aboard: the app downloads episodes ahead of time.
- **Cloud drive folder** (Google Drive, Dropbox) synced to your phone. Lowest effort, but you get no listening position or episode queue.
- **Email or Telegram message** with the MP3 attached. A 15-minute MP3 at 192 kbps is about 21 MB, close to some attachment limits. 128 kbps is about 14 MB.

## Before switching it on

- Add an automated transcript check: run speech-to-text on the MP3 and diff it against the script to catch dropped or repeated lines. ElevenLabs Scribe charges per minute, so turn this on only once quality problems justify the cost.
- Add a "next episode" picker based on `mpod catalog` status, with a check against repeated subjects.
- Decide on human-in-the-loop: auto-render daily but auto-deliver only after you mark the episode `approved`, or fully automatic.
