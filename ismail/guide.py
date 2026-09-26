GUIDE = """ismail: a DAW you operate with text. You write notes/patches/effects as data, render, and read audio back as text.

CONVENTIONS
- Every tool takes `project` (a directory). Bars are 1-indexed; ranges [a, b] are inclusive.
- Note text: '<beat> <pitch> <dur_beats> [vel]' per line or ';'-separated, beats relative to the target bar
  (0 = beat 1). Chords 'C4,E4,G4'. C4 = 60. ' #' starts a comment.
- Audio sources for analysis: render | ref | ref:drums|bass|other|vocals | track:<name> | sound:<name> | a path.
- Volume automation is an OFFSET (dB) on the track fader. Hz params automate in log space.
- Every mutation snapshots the project; `undo` walks back. `batch` applies many ops atomically.

BUILD
  project_new -> track_add(instrument = dict | 'preset:x' | 'track:y') -> notes_write / pattern_write
  -> fx_add / bus_add / track_set(sends, output) -> automation_set -> render(bars=[a,b] for fast loops)
  instrument_help(type) and fx_help list every parameter with defaults.
  Sounds: sound_make (any instrument+fx -> bank), sound_speak (TTS), sound_import, sound_extract (average a
  repeated event), audio_place; use bank sounds in a sampler, as wavetables, or as vocoder modulators.

HEAR (audio -> text), cheapest first
  analyze_structure   whole-song arrangement map (bands, stems, root per bar), sections, loop length
  analyze_bars        per-bar level/bands/onsets/chroma      analyze_envelope  level per 16th (pumping, gates)
  analyze_drums       drum lanes as step strings             analyze_pitches   notes sounding per beat
  analyze_roll        piano roll of a source (same features the comparisons score)
  analyze_melody      monophonic line -> notes               analyze_formants  vowels of a voice
  analyze_timbre / analyze_spectrum / sound_compare          spectrogram (PNG, last resort)

RECREATE A REFERENCE (what worked)
  1. analyze_grid -> project_set(bpm, offset_sec); then align(a='track:<drum>', b='ref:drums') and correct
     offset_sec by the reported lag. Timing errors poison every other metric.
  2. separate(source='ref') (or project_set reference_stems=...) and analyze_structure(source='ref').
  3. Transcribe with notes_from_audio_loop (consensus over loop repetitions). Raw notes_from_audio copies echoes,
     leakage and distortion partials as hard notes: it scores well and sounds like clutter.
     Route registers of one stem to different tracks with low/high.
  4. Sound design: sound_extract a repeated hit/stab (e.g. every=8 for one position of an 8-bar loop), then
     instrument_fit(target='sound:x', params={path: [lo, hi]}, fx=[...]) - fx params fit too ('fx.0.depth_db').
  5. stem_map_set({track: stem}) -> render(stems=True) -> cmp_run. Read cmp_summary, then drill:
     cmp_arrangement (macro), cmp_sections, cmp_worst / cmp_bars (per bar), cmp_zoom(bar) (per 16th:
     b both, r reference only, y yours only, UPPERCASE = note start). cmp_list = progress over time.
  6. For fair stem scores use cmp_run(stems='demucs') at checkpoints: your render is separated by the same
     model, so leakage is symmetric.

READING SCORES
  closeness per metric: 0 = the reference against itself half a loop off ('plausible but wrong'),
  1 = the reference against itself one loop later (its own natural variation). Groups: notes, rhythm, clean
  (clutter, loop self-consistency, extra attacks), sound (bands, level, transients, level shape),
  perceptual (CLAP embedding similarity). Handcrafted metrics can all look good while it still sounds
  different: trust the perceptual group and the warnings, and never call a match done on notes alone.
"""
