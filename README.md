# ismail

A DAW built to be operated by an AI agent. Everything goes in as text (notes, instrument patches, effect chains, automation) and everything comes back as text: levels, spectra, drum patterns, piano rolls, chords, vowels, song structure, and structured comparisons against a reference track. The agent never needs ears or images to work (a spectrogram PNG is there if you want one).

One set of operations, three ways in:

- **MCP server** for Claude Code, Cursor or any MCP client: `python -m ismail.mcp_server` (stdio, about 70 tools)
- **CLI**: `python -m ismail -p <project> <op> [args]`
- **Python**: `from ismail import api`

## Install

Python 3.10 or newer.

```bash
git clone https://github.com/newsbubbles/ismail
cd ismail
pip install -e .                      # engine, analysis, CLI, MCP server
pip install -e ".[perceptual]"        # optional: CLAP perceptual metric (torch + transformers, model about 600 MB)
pip install -e ".[separate]"          # optional: demucs stem separation for reference tracks
```

If `demucs` fights your torch install, use `pip install --no-deps demucs` and then `pip install dora-search einops julius lameenc openunmix`.

MP3 previews need `ffmpeg` on your PATH (or set `ISMAIL_FFMPEG` to the binary).

## Use it with Claude Code

1. **Tools.** Open Claude Code in this folder and the bundled `.mcp.json` registers the server; the tools show up as `mcp__ismail__*`. To use ismail from any folder instead:

   ```bash
   claude mcp add -s user ismail -- python -m ismail.mcp_server
   ```

2. **Skill (recommended).** `skills/ismail` teaches the agent how to compose with ismail: plan a Session Sheet before writing notes, write a Listening Report after every render, and judge reference matches with the comparison tools instead of by feel. Link it into your skills folder:

   ```bash
   # macOS / Linux
   ln -s "$(pwd)/skills/ismail" ~/.claude/skills/ismail
   ```
   ```powershell
   # Windows
   New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\ismail" -Target "$PWD\skills\ismail"
   ```

3. **Ask for music.** For example: "make a 16 bar deep house loop in F minor in songs/demo and render an mp3". The agent calls `guide` once for the conventions (it is a tool and a CLI op), then works through the tools.

## Use it with Cursor

1. **Tools.** Opening this folder in Cursor picks up `.cursor/mcp.json`. To use ismail in other projects, add the same entry to `~/.cursor/mcp.json`:

   ```json
   {"mcpServers": {"ismail": {"command": "python", "args": ["-m", "ismail.mcp_server"]}}}
   ```

2. **Skill.** `.cursor/rules/ismail.mdc` is an agent-requested rule that points Cursor's agent at `skills/ismail/SKILL.md`. Copy that rule (and the `skills/ismail` folder) into another project to use it there.

Any other MCP client works the same way: run `python -m ismail.mcp_server` over stdio.

## Quick start (CLI)

Every tool is also a CLI op. Arguments are `key=value` pairs (values parsed as JSON when they can be) or one JSON object.

```bash
python -m ismail guide                                # read first: workflow and conventions
python -m ismail ops                                  # list operations
python -m ismail help notes_write                     # one op's arguments and docs
python -m ismail -p songs/demo project_new bpm=124 length_bars=8
python -m ismail -p songs/demo track_add name=bass instrument='"preset:acid_bass"'
python -m ismail -p songs/demo notes_write '{"track": "bass", "bar": 1, "notes": "0 E2 0.5 110; 0.5 E3 0.25", "repeat": 8}'
python -m ismail -p songs/demo render stems=true out=v1 mp3=also
python -m ismail -p songs/demo analyze_melody source=track:bass bars=[1,2]
```

`render` writes `renders/latest.wav` (every analysis tool reads it), plus `renders/<out>.wav` when you name the render. `mp3='also'` adds `renders/<out>.mp3` for listening; `mp3='only'` writes the named render as mp3 only.

Keep your projects under `songs/` (git-ignored) or anywhere else; a project is just a folder.

## Concepts

- **Project**: a folder with `project.json` (tempo, grid offset, tracks, buses, master, sound bank, reference) plus `sounds/`, `renders/`, `cache/`, `history/` (undo snapshots) and `comparisons/`.
- **Time**: bars are 1-indexed; note times are beats relative to the bar you write at. `offset_sec` is the time of bar 1, so a project can sit exactly on a reference recording's grid.
- **Notes**: `'<beat> <pitch> <dur> [vel]'`, one per line or `;`-separated. Drum and step patterns: `pattern_write` with strings like `X...x...X...x...` (X 127, x 100, o 70, - 45, `_` ties).
- **Instruments**: `synth` (saw, square, pulse, triangle, sine, additive, wavetable and noise oscillators, unison, FM, drive, SVF and ladder filters, envelopes, LFOs, mono glide), `sampler`, drum synths (`kick`, `snare`, `hat`, `clap`, `tom`, `noise_hit`), `kit` (pitch to instrument map) and `code` (a Python voice function for anything else). `presets_list` has starting points.
- **Effects**: eq, filter, distortion, bitcrush, compressor (with sidechain), duck, gate, delay, reverb, chorus, flanger, phaser, tremolo/autopan, width, limiter, vocoder, formant. Tracks, buses and the master fader can be automated.
- **Voices**: engineered instruments kept as Python modules, so a project stores a name instead of code (see below).
- **Sound bank**: sounds made from any instrument and effect chain (`sound_make`), speech (`sound_speak`), imported files, and averaged events cut from a recording (`sound_extract`). Bank sounds work as sampler sources, wavetables, vocoder modulators and audio clips.
- **Undo and batch**: every edit snapshots the project (`undo`); `batch` applies a list of ops atomically.

## Voices: instruments as code

Some instruments are easier to write than to patch: a measured grand piano, a dubstep bass whose note velocity picks the articulation, a set of sound effects. These live as voice modules, Python files that define `voice(freq, t, vel, gate, sr)` and return a mono `(n,)` or stereo `(2, n)` array. `freq` is in Hz, `t` is an array of seconds from the note start that covers the held time plus the instrument's `tail`, `vel` is 0 to 1, `gate` is how long the note is held in seconds, and `sr` is the sample rate.

| voice | what it is |
|---|---|
| `grand_piano` | grand piano calibrated from measured notes (partials, decay times, inharmonicity, stereo image, hammer knock, dampers); `fn: voice_sym` is an undamped sympathetic string |
| `additive_piano` | a lighter additive piano with no data file |
| `growl` | dubstep bass engine: velocity 1x yoi, 2x wub, 3x screech, 4x metal, 5x dive, 6x zap, 7x grind, 8x chop, 9x talk, 11x robot, 12x howl; the LFO rates follow the song tempo |
| `sfx` | one-shots by velocity: gunshot, reload, shell casing, bone crunch, punch, rip, gong |

Use one with `instrument={"type": "code", "voice": "grand_piano", "tail": 4.0}` or `"preset:grand_piano"`. `voices_list` shows what is available and `voice_help(name)` explains a voice's velocity mapping, functions and parameters.

Voices are looked up in this order:

1. `<project>/voices/<name>.py`: the song's own. Same name as a built-in overrides it; a song voice can also extend one (`from ismail.voices.growl import *`, then add words or articulations).
2. Each folder in `$ISMAIL_VOICES` (a path list): your personal library, outside any repo.
3. `ismail/voices/`: the built-ins.

A voice function may take extra keyword arguments: `bpm` is passed automatically, and the track's `"params"` dict is passed as keywords (`{"type": "code", "voice": "mine", "params": {"brightness": 0.3}}`). A module-level `INFO` dict documents it for `voice_help`; every key is optional: `summary` (one line for `voices_list`), `range`, `velocity` (what velocity does), `functions` (name to description), `params` (name to description) and `tail` (recommended tail). Data files sit next to the module (`grand_piano.json`) and are found through `__file__`. Editing a voice file invalidates the render cache for the tracks that use it.

To add a voice to the library, move it from a song's `voices/` folder into `ismail/voices/`, give it an `INFO` dict, and add a line to the test that renders every built-in.

## Hearing: audio as text

| Question | Tool |
|---|---|
| Tempo and where bar 1 is | `analyze_grid`, `align` |
| Song form, what plays where | `analyze_structure` (arrangement map, sections, loop length, root per bar) |
| Levels, bands and chords per bar | `analyze_bars`, `analyze_chords`, `analyze_key` |
| Drum pattern | `analyze_drums` (step strings you can paste into `pattern_write`) |
| Notes | `analyze_pitches` (per beat), `analyze_roll` (piano roll), `analyze_melody`, `analyze_notes` |
| Rhythm of level (pumping, gating) | `analyze_envelope` |
| What a sound is | `analyze_timbre`, `analyze_spectrum`, `sound_compare` |
| Vowels of a voice | `analyze_formants` |
| A picture, if you really need one | `spectrogram` (PNG) |

Sources are `render`, `track:<name>` (after `render(stems=True)`), `ref`, `ref:<stem>`, `sound:<name>` or a file path.

## Recreating a reference track

Bring your own reference audio (`project_new(..., reference=<file>)`); none is included here.

1. `analyze_grid(source='ref')`, then `align` a rendered drum track against `ref:drums` and correct `offset_sec`.
2. `separate(source='ref')` (demucs) and read `analyze_structure(source='ref')`.
3. Transcribe with `notes_from_audio_loop`. It keeps only notes that recur across repetitions of the loop, because raw transcription copies echoes, leakage and distortion partials as hard notes. If the song alternates versions of its loop, transcribe each from its own repetitions and pass `base_bars` so the shared notes stay identical.
4. Design sounds: `sound_extract` a repeated hit or stab, then `instrument_fit` (evolution strategy over instrument and effect parameters, scored on spectrum, envelope, width and pitch clarity). `track_fit` tunes a part in context against the reference stem.
5. `stem_map_set`, `render(stems=True)`, `cmp_run`, then drill down: `cmp_summary`, `cmp_arrangement`, `cmp_sections`, `cmp_worst`, `cmp_bars`, `cmp_zoom(bar)`. `cmp_list` tracks progress across runs.

### How comparisons score

Every metric sits between two baselines computed from the reference alone: the reference against itself one loop later (its own natural variation, closeness 1) and against itself half a loop out of place (plausible but wrong, closeness 0). Metrics are grouped, and the groups count equally:

- **notes**: F1 of sounding notes per 16th step, exact pitch and pitch class
- **rhythm**: F1 and precision of note starts, drum lane hits
- **clean**: clutter (attacks sharper than the reference), loop self-consistency, loudness share of extra note starts
- **sound**: band levels, level, transient sharpness, level contour inside the bar
- **perceptual**: CLAP audio embedding similarity per 2-bar window

The perceptual group exists because the others can all look fine while the result still sounds different, and the clean group exists because note metrics reward clutter. Use `cmp_run(stems='demucs')` at checkpoints so your render goes through the same separation as the reference. Any change to the scoring should be checked against a known-bad and a known-good draft before you trust it.

## Tests

```bash
python -m pytest tests -q
```

Round trips: write known material, render it, read it back through the analysis tools.

## Layout

```
ismail/
  notation.py    note text, step patterns, piano roll
  dsp.py         oscillators, filters, dynamics, delay lines, reverb (numba)
  instruments.py synth, sampler, drums, kit, code
  fx.py          effects
  render.py      project to audio, dependency ordering, per-track cache, wav/mp3 writers
  analysis.py    audio to text (grid, bars, chords, melody, drums, timbre, formants, compare)
  features.py    16th-step feature grid shared by structure and comparisons
  structure.py   arrangement map, sections, loop detection
  cmp.py         stored comparisons and their views
  perceptual.py  CLAP similarity
  sounddesign.py one-shot rendering, sound distance, parameter fitting
  trackfit.py    in-context fitting against a reference stem
  voices/        voice modules: grand_piano, additive_piano, growl, sfx
  api.py, api_cmp.py, api_sound.py   the operations (CLI and MCP tools)
  mcp_server.py, guide.py
skills/ismail/   the agent skill (SKILL.md + references)
.mcp.json, .cursor/   MCP and rule config for Claude Code and Cursor
songs/           your projects (git-ignored)
```

## License

MIT, see `LICENSE`.
