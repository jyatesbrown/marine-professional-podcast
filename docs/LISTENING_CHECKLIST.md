# Manual listening review

Automated checks confirm that the MP3 decodes, has the expected length, contains every line in order, and has no long dropouts. They cannot judge how it sounds. Listen to the whole episode on headphones before marking it `approved`, and do one pass at driving volume through a speaker.

| # | Check | Pass? | Notes / timestamps |
|---|-------|-------|--------------------|
| 1 | Alex always sounds like Alex and Morgan like Morgan. No voice swaps or drift, including after segment joins. | | |
| 2 | Technical terms are pronounced correctly: units (kW, kVA, Hz), acronyms (CTD, ADCP, PMS, ROV, DP), vessel and equipment names. See `pronunciation_notes`. | | |
| 3 | Numbers and units read naturally ("four hundred eighty volts", not "four eight zero V"). | | |
| 4 | Segment joins (one every ~2 minutes; the segment table from `mpod estimate` lists them): no clicks, no jumps in loudness or room tone, no change of pace, no repeated or swallowed words. | | |
| 5 | Nothing is missing or repeated. Follow along in `<slug>.transcript.md`. | | |
| 6 | The ends of turns aren't clipped, and the last word of each segment is complete. | | |
| 7 | Pacing is conversational. Neither robotic nor rushed. Pauses between speakers feel natural. | | |
| 8 | Emotional delivery is measured. No exaggerated excitement, laughter or whispering, and no audio tags read aloud. | | |
| 9 | Loudness stays steady across the episode and is comfortable on headphones and in a car. | | |
| 10 | No background music or noise. No artefacts such as metallic tone, warble or breaths cut off mid-breath. | | |

If a problem is local to one segment, delete that segment's `.mp3` in `output/<slug>/segments/` and re-run `mpod render ... --yes`. Only that segment is regenerated, at that segment's cost. For pronunciation problems, change the spelling in `episode.yaml` (e.g. "C-T-D", "kilovolt-amps"). That changes the segment's fingerprint, so it regenerates automatically.
