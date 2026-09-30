# Changelog

## Unreleased

### Guitar rig and performers

- Rig effects (`ismail/rig.py`): `fuzz` (Fuzz Face bias shift), `univibe` (four-stage LDR phaser with lamp lag),
  `amp` (Marshall-style tone stack after Yeh and Smith 2006, push-pull power stage with sag), `cab` (min-phase
  cabinet with a mic blend), `rotary` (Leslie with ramping rotors), `tape` (head bump, wow, flutter, hiss), `wah`
  (resonant band-pass). `fx_help(type=...)` documents each. Live runs them baked into each rendered note.
- Performer voices in the studio: a voice module with `perform()` and no `voice()` renders a whole part at once
  (strings that ring on, legato, slides, whammy), with expression lanes from automation `inst.lane.<name>`. Live
  already played them from clip `expr` lanes; one mechanism now: a deck turns a song's `inst.lane.*` automation
  into its clip's `expr`, and `live_load` marks a song's performer tracks (decks had played them note by note).

## 0.2.0 (2026-09-30)

### Live

- **Live engine** (`ismail/live/`): a separate process per folder plays a queue of clips in real time while the
  agent edits it. Ops: `live_start`, `live_stop`, `live_status`, `live_track`, `live_bus`, `live_fx`,
  `live_queue`, `live_cancel`, `live_view`, `live_listen`, `live_record`.
- Clips loop until replaced; launches quantize to the beat, bar or phrase (`next_4`, `bar:N`, `after:<id>`,
  `after:#k` for a whole arc in one batch). The reply gives each clip's landing bar and the runway.
- Render ahead: worker processes render each note or phrase before the playhead (identical notes render once);
  a clip that cannot render in time lands later and the reply says so.
- Effects, send buses, sidechain, duck and vocoder from live tracks; `live_fx` ramps any automatable param.
- Safety chain on every output: trim, loudness rider, lookahead limiter, ceiling, set from the environment.
- `live_listen` analyses the last bars played, a deck, or a finished `live_record` take.
- Decks: `live_deck`, `live_load` (a whole ismail song on a cued deck), `live_transition` (blend, bass swap,
  filter, cut), a DJ strip per deck (LR4 isolator, filter knob, fader, transpose).
- Studio and live: studio code is the source of truth. Effects run live as block-by-block twins
  (`fx_blocks.py`, `dsp_blocks.py`) held to the studio versions by `tests/test_live_parity.py`; an effect with no
  twin is baked into each rendered note or phrase. Voices with `perform()` play whole phrases live, with `expr`
  lanes (bend, vibrato) on clips.
- mimic profiles and code voices play live.
- Install `.[live]` (sounddevice) to play to speakers; `device='none'` runs without audio out.
- A deck plays a song the way it renders: a bus that tracks play through keeps its reverb or delay as an insert
  (dry passes; live buses had been wet-only, which took the drums out of a song with a reverb on its drum bus),
  and the song's automation comes over (fx params and track and bus volume as ramps, instrument params rendered
  with the notes, the master fade), repeated every pass on a looping deck. A track with instrument automation
  renders its section as one event, sent to a worker one pass ahead.

### Measurement

- `analyze_grid`: the snare on 2 and 4 votes for bar 1; reports the record's tuning offset and swing.
- New ops: `ref_retune` (retuned analysis copies of an off-pitch reference), `analyze_swing`, `analyze_kit`
  (the pieces of a drum kit and each one's pattern, by NMF), `analyze_sections`, `levels_from_ref` (faders from
  the reference's stem balance).
- `analyze_sections` flags a build (2 dB or more under the climax on average, peaking within 3 dB of it), not a
  drop that goes on at the same level.

### Voices

- mimic: instruments measured from recordings (`mimic_measure`, the `mimic` instrument type), with leave-one-out
  checks; wandering vibrato, swells, measured room, attack maps, sympathetic strings.
- Voice library in family folders; measured string profiles ship built in.

### Skill

- Live reference (`references/live.md`): running a set as a DJ loop, small edits over whole sections, a runway
  before every question, metric modulation for style changes at a fixed tempo, performers and phrase voices.
- Recreation lessons: measure tuning, swing, kit pieces and fader balance; a record's drum kit as measured
  models; phrase length before tiling; one-part-at-a-time A/B.

## 0.1.0 (2026-09-26)

First public release: an agent-operated DAW with a CLI, an MCP server and a Python API. Notes, patches,
effects and automation in as text; levels, spectra, drum lanes, piano rolls, chords, structure and stored
reference comparisons out as text. Code voices, drum synths, samplers, stem separation, instrument and track
fitting, the optional music-video pipeline, and the agent skill.
