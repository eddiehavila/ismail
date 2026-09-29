# Recreating or matching a reference recording

Learned from recreating Vitalic's "Allan Dellon". Each step exists because skipping it cost hours.

## 1. Grid first; timing errors poison everything

- Get the audio (yt-dlp; YouTube may bot-wall, SoundCloud search `scsearch:` often works).
- `project_new(..., reference=<wav>)`, `analyze_grid(source='ref')` for bpm and the time of bar 1. The downbeat pick is fragile when the kick skips beats; the tool prints the phase scores.
- Render a drum track, then `align(a='track:<snare or hats>', b='ref:drums', band='himid' or 'air')` and set `offset_sec` from its answer. A 40 ms offset made onset metrics negative.

## 2. Separate and read the whole song before writing

- `separate(source='ref')` (demucs, GPU) then `analyze_structure(source='ref')`: arrangement map per stem, sections, harmonic loop length, root per bar.
- Expect separation quirks: synth bass often lands in `other`, the `bass` stem can be near-empty (comparisons skip it and say so), vocals leak into `other` and vice versa.
- Drill into sections with `analyze_roll(source='ref:other', bars=, low=, high=)`, `analyze_drums(source='ref:drums')`, `analyze_formants(source='ref:vocals')`.

## 3. Transcribe by consensus, never raw

- `notes_from_audio_loop(track, source, bars, loop_bars=8, low, high, min_presence)` keeps notes present in most repetitions of the loop. Raw per-bar transcription copies echoes, bleed and distortion partials as hard new notes: it scores high on note metrics and sounds like random beeps. This exact failure was only caught by a human listening.
- Transcribe per section (18-33, 34-57, ...) when the arrangement evolves; one global pattern flattens the song.
- Check `analyze_structure` root row for loop VARIANTS (Allan Dellon alternates two versions of its 8-bar loop: F-Bdim-Am-C vs E-F-D-A in the second half). A consensus over all loops washes a variant out. Transcribe each variant from its own repetitions (`bars` spanning them, `write_bars` per occurrence) with `base_bars` = the whole span so shared notes stay identical.
- Route one stem's registers to different tracks with low/high (bass C2-A2, stabs A#2-B4, lead C5+). Ignore the lowest octave of a separated stem: it is mostly kick bleed and sub-octaves of distorted synths.
- Melodic, non-looping parts (a vocal phrase): read `analyze_pitches(per_bar=4)` and write the line yourself; hold notes as long as the formant view says the voice is voiced.

## 4. Sounds, one instrument and one chunk at a time

Right notes on the wrong instrument still sound wrong. Before arranging the whole song, match each lead instrument on a short passage where it is exposed (the intro, a break), following `references/instruments.md` section 4: spectrogram first, then a voice that has the mechanism the reference uses (a Polyphia guitar part turned out to be mostly touch harmonics, which no amount of note fixing could produce), then the user's ear on that chunk.

For repeated electronic events: `sound_extract` the event averaged over its loop position (`every=8`), then `instrument_fit`. Check the fitted sound in context afterwards. Keep the reference out of the render: extracted sounds are fitting targets, not samples to use.

## 5. Compare, then drill down

- `stem_map_set({track: stem})`, `render(stems=True)`, `cmp_run(label=)`.
- Read in this order: `cmp_summary` (per stem groups: notes, rhythm, clean, sound, perceptual; closeness 0 = the reference half a loop off, 1 = the reference against itself one loop later) -> `cmp_arrangement` -> `cmp_sections(stem)` -> `cmp_worst(stem)` -> `cmp_zoom(bar, stem, layers=['level','bands','notes','hits'])` (b both, r reference only, y yours only, uppercase = note start).
- `cmp_list` shows every run: keep labels meaningful (`draft7-vocoder`).

## Traps (each one fooled the scores at least once)

- **Clutter scores well.** If `cmp_summary` prints a WARNING about extra note starts or less loop self-consistency than the reference, believe it over the F1 numbers.
- **Stem perceptual in track mode is biased.** Reference stems carry bleed; yours from tracks are clean. Trust mix-level perceptual, and use `cmp_run(stems='demucs')` at checkpoints so both sides pass through the same separation.
- **Loudness buys perceptual score.** After any `track_fit`, check `cmp_bars` level columns and the limiter.
- **Averages hide the gap.** Long-window spectra can agree within 4 dB while the parts sound different; zoom per 16th, and look at a spectrogram when a section stays bad for no visible reason (a missing low-pass showed up only there).
- **Never delete a downbeat on one reading.** Before removing a kick on beat 1, confirm with `analyze_envelope(source='ref:drums', band='sub')`: a missing downbeat after a break made the beat come back "mid bar" to a listener.
- **Metrics tuned on one example lie.** Before trusting a new measure, check it ranks a known-bad draft below a known-good one (re-render old drafts from `comparisons/<id>/project.json`).

## When is it done

When the mix perceptual group is near its ceiling in every section, no WARNING lines remain, the arrangement maps match, the master is at the reference's loudness, and the user has listened and said the instruments sound right. Report the numbers against their ceilings and say plainly which parts still differ.
