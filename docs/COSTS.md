# ElevenLabs cost notes

Sources, checked 2026-10-29: <https://elevenlabs.io/pricing>, <https://elevenlabs.io/pricing/api>, <https://elevenlabs.io/docs/overview/capabilities/text-to-dialogue>, <https://elevenlabs.io/docs/overview/models>. Prices change. Re-check them before relying on these numbers. `mpod account` shows your real plan and remaining credits.

## Facts from the documentation

- Text to Dialogue (`POST /v1/text-to-dialogue`) runs only on **`eleven_v4`** (recommended by ElevenLabs) and **`eleven_v3`**.
- For reliable generation, ElevenLabs advises at most **2,000 characters** of `inputs[].text` per request. Longer requests can end early. The pipeline uses 1,800 by default.
- Credits: Text to Speech costs about 1 credit per character on the v4/v3 class of models. Audio tags such as `[laughs]` are characters too.
- The API pay-as-you-go price is **$0.08 per 1K characters** for both v4 and v3.
- MP3 at 192 kbps needs **Creator** or above. 128 kbps works on every plan.
- Commercial use needs a paid plan. Free-plan output is for non-commercial use only, with attribution.

| Plan | $/month | Credits/month |
|------|--------:|--------------:|
| Free | 0 | 10,000 |
| Starter | 6 | 30,000 |
| Creator | 22 | 121,000 |
| Pro | 99 | 600,000 |
| Scale | 299 | 1,800,000 |

## Estimates (these are my assumptions, not measurements)

A 15-minute two-host episode at about 150 words per minute is roughly 2,250 words, or **about 13,000–14,000 characters**. `mpod estimate <episode>` replaces this with the exact count for a real script.

- **Pilot:** about 14,000 credits for one full render. Add about 600 for `mpod preview` and about 1,800 for a one-segment sample (`--max-segments 1`). Budget about 20,000 credits so a couple of segments can be regenerated. Free (10k) can't render the pilot. Starter (30k) can, once. Creator gives the most headroom.
- **Daily, 30 episodes a month:** about 420,000 credits/month. **Pro (600k, $99)** is the smallest plan that fits, with room for regenerations. Creator (121k) covers about 8 episodes. At the PAYG list price, 420k characters would cost about $34. The billing docs say PAYG credits are converted at the plan's rate, so check the actual top-up price in your account before planning around it.

## Model comparison

| Option | Dialogue quality | Relative cost | Notes |
|--------|------------------|--------------:|-------|
| `eleven_v4` Text to Dialogue (default) | Best. Recommended by ElevenLabs for dialogue | 1x | |
| `eleven_v3` Text to Dialogue | Previous generation | 1x (same list price) | Fallback if a chosen voice works better on v3 |
| `eleven_v4_turbo` via the Text to Dialogue **WebSocket** | Close to v4, tuned for latency | ~0.5x ($0.04/1K) | Not implemented. Needs the streaming WebSocket. Worth testing once daily volume justifies it |
| Per-turn Text to Speech on Flash v2.5 | Noticeably less natural turn-taking | ~0.5x | Not recommended. Gives up the conversational flow that is the point of the format |

## Ways to keep costs down

1. Never regenerate what's already good. Segment checkpoints are content-addressed, so editing one line regenerates only that segment.
2. Approve voices on the ~600-character preview and a single segment, not on full episodes.
3. Keep scripts tight. Every character costs, including stage directions and audio tags. `mpod validate` flags episodes that run far over target length.
4. Use the dashboard's free regenerations (2 per generation, dashboard only) for one-off fixes, instead of API calls.
5. For daily production, an annual Pro plan includes two free months.
6. `cost.limits` in `config.yaml` caps credits per run, per month (counted from the ledger) and segments per run.
